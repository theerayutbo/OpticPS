"""NANF literature benchmark, Gate N2: Fig. 1 recomputed and Fig. 5 read (LITERATURE BENCHMARK /
CALIBRATION ONLY).

Nothing here validates a fibre. Benchmark A recomputes the paper's own numerical model (the Fig. 1
curves) with this project's propagation code, as the plan section 2 allows (Fig. 1 is cross-check
only, "not a measurement"). Benchmark C reads the Fig. 5 columns, which the plan classes as
calibration inputs (operating points and link loss, not performance results). No holdout series
(Fig. 4 NANF and SSMF, Fig. 6 to 12) is read or touched by anything in this module.

The Fig. 1 curves come from a local workbook at an explicit path, read through
`nanf_import.read_nanf_workbook`; none of their values is stored in Git.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from opticps.measurement.nanf_import import DataRole, NanfSeries, NanfWorkbook, series_key
from opticps.optical_channel.fiber import (
    UNSUPPORTED_EFFECTS,
    FiberProfile,
    OutOfValidityRangeError,
    ParameterProvenance,
    ProfileValue,
    ProvenanceCategory,
    ResolvedFiber,
    WavelengthTable,
    resolve_profile,
)
from opticps.optical_channel.link import group_delay_s, propagate_profile_field

SPEED_OF_LIGHT = 299_792_458.0
FloatArray = NDArray[np.float64]

CITATION = (
    "Hong et al. 2021, J. Lightwave Technol. 39(19) 6167, Sec. II and Fig. 1 (manuscript p.2-3)"
)
NUMERICAL = ProvenanceCategory.PUBLISHED_NUMERICAL_ASSUMPTION
BAND_NM = (1400.0, 1625.0)  # the Fig. 1 axis; the only range the paper's curves cover

# The paper's stated numerical assumptions (Sec. II). D at 1550 nm in ps/(nm km); group index.
# The indices are called "(effective) refractive indices" in the paper and used as group indices.
PAPER_ASSUMPTIONS: dict[str, tuple[float, float]] = {
    "SSMF": (15.95, 1.4682),
    "NZ-DSF": (4.50, 1.4693),
    "NANF": (2.04, 1.003),
}
# Workbook header of each fibre, per Fig. 1 block (headers differ between blocks).
FIG1_HEADERS = {
    "cd": {"SSMF": "SSMF", "NZ-DSF": "NZ-DSF", "NANF": "NANF"},
    "bandwidth": {"SSMF": "SMF@5km", "NZ-DSF": "NZ-DSF@5km", "NANF": "NANF@5km"},
    "fading": {"SSMF": "SMF", "NZ-DSF": "NZ-DSF", "NANF": "NANF"},
    "latency": {"SSMF": "SSMF", "NZ-DSF": "NZ-DSF", "NANF": "NANF"},
}
FIG1_BLOCKS = {
    "cd": "a-CD",
    "bandwidth": "b-bandwidth",
    "fading": "c-fading",
    "latency": "d-latency",
}
# Plan Amendment 1, A1.3: pre-registered zero-chirp first nulls (GHz) and the tolerance on the
# simulator's own null, a disagreement above which is a simulator defect.
PREREGISTERED_NULLS_GHZ = {"SSMF 4.53 km": 29.39, "SSMF 5 km": 27.97, "NANF 4.76 km": 80.2}
NULL_TOLERANCE_GHZ = 0.3
PAPER_LATENCY_SAVING_US = 8.0  # "~8 us" (Sec. II)
PAPER_LATENCY_SAVING_FRACTION = 0.30  # "~30%" is the project's own reading, see the Sources doc


def _known(value: float, unit: str, **prov: object) -> ProfileValue:
    return ProfileValue(
        value,
        unit,
        ParameterProvenance(NUMERICAL, CITATION, **prov),  # type: ignore[arg-type]
    )


def _unknown(unit: str) -> ProfileValue:
    return ProfileValue(None, unit, ParameterProvenance(ProvenanceCategory.UNKNOWN, "none"))


def numerical_profile(
    name: str,
    *,
    length_km: float = 5.0,
    d_ps_per_nm_km: float | None = None,
    d_table: WavelengthTable | None = None,
) -> FiberProfile:
    """The paper's numerical fibre: loss excluded (Sec. II), D stated at 1550 nm or from a table.

    Exactly one of `d_ps_per_nm_km` and `d_table` is given. Loss and lumped losses are zero because
    the paper says fibre loss was excluded from these simulations (a published numerical
    assumption, not a property of any fibre).
    """
    if (d_ps_per_nm_km is None) == (d_table is None):
        raise ValueError("give exactly one of d_ps_per_nm_km and d_table")
    group_index = PAPER_ASSUMPTIONS[name][1]
    zero = _known(0.0, "dB", validity_range_nm=BAND_NM)
    d = (
        _unknown("ps/(nm km)")
        if d_ps_per_nm_km is None
        else _known(
            d_ps_per_nm_km,
            "ps/(nm km)",
            measurement_wavelength_nm=1550.0,
            validity_range_nm=BAND_NM,
        )
    )
    return FiberProfile(
        profile_id=f"HONG-2021-FIG1-{name}",
        fiber_type=f"{name} as assumed in the paper's numerical comparison (Fig. 1)",
        sample_id=None,
        length_km=_known(length_km, "km"),
        reference_wavelength_nm=_known(1550.0, "nm"),
        attenuation_db_per_km=_known(
            0.0, "dB/km", measurement_wavelength_nm=1550.0, validity_range_nm=BAND_NM
        ),
        connector_loss_db=zero,
        pigtail_loss_db=zero,
        splice_loss_db=zero,
        dispersion_ps_per_nm_km=d,
        dispersion_slope_ps_per_nm2_km=_unknown("ps/(nm^2 km)"),
        group_index=_known(group_index, "1"),
        gamma_per_w_km=_unknown("1/(W km)"),
        effects={k: "off" for k in UNSUPPORTED_EFFECTS},
        dispersion_table=d_table,
    )


# --- small-signal response through the propagation code -----------------------------------------


def tone_response(resolved: ResolvedFiber, frequency_hz: float, depth: float = 1e-3) -> float:
    """Return |H(f)| of the intensity tone after propagation and square-law detection.

    A chirp-free intensity-modulated field sqrt(1 + depth cos(2 pi f t)) goes through
    `propagate_profile_field` (all-pass dispersion; loss is part of the resolved fibre) and is
    detected as |E|^2. The ratio of the output to the input amplitude at f, divided by the loss
    factor, is the response. It follows |cos(pi lambda^2 D L f^2 / c)| for small depth; the
    simulation is what is reported, and the closed form is only used as a bracket.
    """
    if frequency_hz <= 0 or not math.isfinite(frequency_hz):
        raise ValueError("frequency must be positive and finite")
    per_cycle, cycles = 16, 16
    n = per_cycle * cycles
    sample_rate = per_cycle * frequency_hz
    phase = 2 * np.pi * np.arange(n) / per_cycle
    field = np.sqrt(1.0 + depth * np.cos(phase)).astype(np.complex128)
    out = propagate_profile_field(field, sample_rate, resolved).field
    intensity = np.abs(out) ** 2
    loss = 10 ** (-resolved.total_loss_db / 10)
    amplitude = 2.0 * abs(np.sum(intensity * np.exp(-1j * phase))) / n
    return float(amplitude / (depth * loss))


def response_db(resolved: ResolvedFiber, frequency_hz: float) -> float:
    return 20.0 * math.log10(max(tone_response(resolved, frequency_hz), 1e-300))


def first_null_bracket_ghz(resolved: ResolvedFiber) -> float:
    """Closed-form first null in GHz, used only to bracket a search (inf if D L is zero)."""
    dl = abs(resolved.dispersion_ps_per_nm_km * 1e-6) * resolved.length_km * 1e3
    if dl < 1e-18:
        return math.inf
    lam = resolved.wavelength_nm * 1e-9
    return math.sqrt(SPEED_OF_LIGHT / (2 * lam**2 * dl)) / 1e9


def first_null_ghz(
    resolved: ResolvedFiber, *, half_window_ghz: float = 3.0, step_ghz: float = 0.01
) -> float:
    """Find the first spectral null by scanning the simulated response near the bracket.

    The scan covers bracket +- half_window at step_ghz and takes the minimum (parabolic refine).
    """
    centre = first_null_bracket_ghz(resolved)
    grid = np.arange(max(centre - half_window_ghz, step_ghz), centre + half_window_ghz, step_ghz)
    values = np.array([tone_response(resolved, g * 1e9) for g in grid])
    i = int(np.argmin(values))
    if i in (0, len(grid) - 1):
        raise ValueError("no interior null in the scan window")
    y0, y1, y2 = values[i - 1], values[i], values[i + 1]
    denom = y0 - 2 * y1 + y2
    shift = 0.0 if denom == 0 else 0.5 * (y0 - y2) / denom
    return float(grid[i] + shift * step_ghz)


def bandwidth_3db_ghz(resolved: ResolvedFiber) -> float:
    """First frequency at which the simulated response is -3 dB (20 log10 |H|), by bisection."""
    high = first_null_bracket_ghz(resolved)
    if not math.isfinite(high) or high > 5e3:
        return math.inf
    low = 0.0
    for _ in range(50):
        mid = 0.5 * (low + high)
        if response_db(resolved, mid * 1e9) > -3.0:
            low = mid
        else:
            high = mid
    return 0.5 * (low + high)


# --- Benchmark A: Fig. 1 -------------------------------------------------------------------------


def _series(wb: NanfWorkbook, kind: str, fibre: str) -> NanfSeries:
    s = wb[series_key("Fig.1", FIG1_BLOCKS[kind], FIG1_HEADERS[kind][fibre])]
    if s.role is not DataRole.CROSS_CHECK:
        raise ValueError("Fig. 1 series are the cross-check class")
    return s


def d_table_from_workbook(wb: NanfWorkbook, fibre: str) -> WavelengthTable:
    """The paper's own D(lambda) curve for one fibre as a table in nm (from the local workbook)."""
    s = _series(wb, "cd", fibre)
    return WavelengthTable(
        f"Fig.1(a) {fibre}",
        tuple(round(x * 1000.0, 6) for x in s.x),
        s.y,
        "ps/(nm km)",
        ParameterProvenance(
            NUMERICAL, "Hong et al. 2021 Fig. 1(a); dataset DOI 10.5258/SOTON/D1889 sheet Fig.1"
        ),
    )


@dataclass(frozen=True)
class FadingResult:
    fibre: str
    max_abs_diff_db: float  # over grid points where the model response is above -25 dB
    rms_diff_db: float  # over those points
    n_compared: int
    n_excluded_deep: int  # points with the model below -25 dB (a 1 GHz grid is not sampling a null)
    max_abs_diff_with_workbook_d_db: float  # same, with the workbook's own D (not the rounded one)
    model_at_deepest_published_db: float
    published_min_db: float
    published_min_freq_ghz: float


@dataclass(frozen=True)
class Fig1Report:
    """The numbers of Benchmark A. There is no predeclared tolerance except the null one."""

    stated_cd_vs_workbook_at_1550: dict[str, tuple[float, float]]  # stated, workbook table
    fading: dict[str, FadingResult]
    first_null_ghz: dict[str, float]  # simulated, per fibre at 5 km
    published_null_ghz_grid: dict[str, float | None]  # workbook minimum if interior, else None
    preregistered_null_check: dict[str, tuple[float, float, bool]]  # simulated, expected, within
    bandwidth: dict[str, tuple[float, float, int]]  # max abs diff GHz, max rel diff, n compared
    bandwidth_at_1550_ghz: dict[str, tuple[float, float]]  # simulated, workbook
    latency: dict[str, tuple[float, float]]  # max abs diff in us, max rel diff
    latency_saving_5km_us: tuple[float, float]  # simulated, workbook (SSMF minus NANF)
    latency_saving_5km_fraction: float
    nanf_bandwidth_min_ghz: tuple[float, float]  # over 1.4 to 1.625 um: simulated, workbook
    nanf_over_ssmf_bandwidth_min_ratio: tuple[float, float]  # simulated, workbook
    nz_dsf_wider_than_nanf_nm: tuple[tuple[float, float] | None, tuple[float, float] | None]
    conventions: str


def _resolved_at(profile: FiberProfile, wavelength_nm: float = 1550.0) -> ResolvedFiber:
    return resolve_profile(profile, wavelength_nm)


def fig1_report(wb: NanfWorkbook) -> Fig1Report:
    """Recompute the paper's Fig. 1 with the propagation code and compare with the workbook."""
    cd_check: dict[str, tuple[float, float]] = {}
    fading: dict[str, FadingResult] = {}
    nulls: dict[str, float] = {}
    published_nulls: dict[str, float | None] = {}
    bandwidth: dict[str, tuple[float, float, int]] = {}
    bw1550: dict[str, tuple[float, float]] = {}
    latency: dict[str, tuple[float, float]] = {}
    sim_bw: dict[str, FloatArray] = {}
    pub_bw: dict[str, FloatArray] = {}
    wl_um = np.array([])
    latency_sim: dict[str, float] = {}
    latency_pub: dict[str, float] = {}
    for fibre, (d_stated, _) in PAPER_ASSUMPTIONS.items():
        table = d_table_from_workbook(wb, fibre)
        cd_check[fibre] = (d_stated, table.at(1550.0)[0])
        # fading profile at 1550 nm and 5 km with the stated D (the paper's assumption)
        stated = _resolved_at(numerical_profile(fibre, d_ps_per_nm_km=d_stated))
        pub = _series(wb, "fading", fibre)
        model = np.array([0.0 if f == 0 else response_db(stated, f * 1e9) for f in pub.x])
        ref = np.array(pub.y)
        keep = model > -25.0
        diff = np.abs(model - ref)[keep]
        deepest = int(np.argmin(ref))
        own_d = _resolved_at(numerical_profile(fibre, d_table=table))
        own = np.array([0.0 if f == 0 else response_db(own_d, f * 1e9) for f in pub.x])
        fading[fibre] = FadingResult(
            fibre,
            float(diff.max()),
            float(np.sqrt(np.mean(diff**2))),
            int(keep.sum()),
            int((~keep).sum()),
            float(np.abs(own - ref)[keep].max()),
            float(model[deepest]),
            float(ref[deepest]),
            float(pub.x[deepest]),
        )
        interior = 0 < deepest < len(ref) - 1
        published_nulls[fibre] = float(pub.x[deepest]) if interior else None
        nulls[fibre] = first_null_ghz(
            stated, half_window_ghz=min(3.0, 0.25 * first_null_bracket_ghz(stated))
        )
        # 3-dB bandwidth versus wavelength with the paper's own D(lambda) curve
        profile = numerical_profile(fibre, d_table=table)
        bw = _series(wb, "bandwidth", fibre)
        sims, pubs = [], []
        for wavelength_um, published in zip(bw.x, bw.y, strict=True):
            sims.append(
                bandwidth_3db_ghz(resolve_profile(profile, round(wavelength_um * 1000.0, 6)))
            )
            pubs.append(published)
        sim_a, pub_a = np.array(sims), np.array(pubs)
        sim_bw[fibre], pub_bw[fibre], wl_um = sim_a, pub_a, np.array(bw.x)
        finite = np.isfinite(sim_a)
        absd = np.abs(sim_a - pub_a)[finite]
        reld = (np.abs(sim_a - pub_a) / pub_a)[finite]
        bandwidth[fibre] = (float(absd.max()), float(reld.max()), int(finite.sum()))
        i1550 = int(np.argmin(np.abs(np.array(bw.x) - 1.55)))
        bw1550[fibre] = (float(sim_a[i1550]), float(pub_a[i1550]))
        # latency n L / c over the published lengths
        lat = _series(wb, "latency", fibre)
        sim_lat = np.array(
            [
                group_delay_s(
                    _resolved_at(numerical_profile(fibre, length_km=L, d_ps_per_nm_km=d_stated))
                )
                * 1e6
                for L in lat.x
            ]
        )
        pub_lat = np.array(lat.y)
        latency[fibre] = (
            float(np.abs(sim_lat - pub_lat).max()),
            float((np.abs(sim_lat - pub_lat) / pub_lat).max()),
        )
        latency_sim[fibre], latency_pub[fibre] = float(sim_lat[-1]), float(pub_lat[-1])
    pre: dict[str, tuple[float, float, bool]] = {}
    for label, fibre, length in (
        ("SSMF 4.53 km", "SSMF", 4.53),
        ("SSMF 5 km", "SSMF", 5.0),
        ("NANF 4.76 km", "NANF", 4.76),
    ):
        resolved = _resolved_at(
            numerical_profile(fibre, length_km=length, d_ps_per_nm_km=PAPER_ASSUMPTIONS[fibre][0])
        )
        centre = first_null_bracket_ghz(resolved)
        sim = first_null_ghz(resolved, half_window_ghz=min(3.0, 0.25 * centre))
        expected = PREREGISTERED_NULLS_GHZ[label]
        pre[label] = (sim, expected, abs(sim - expected) <= NULL_TOLERANCE_GHZ)

    def wider(table: dict[str, FloatArray]) -> tuple[float, float] | None:
        idx = np.nonzero(table["NZ-DSF"] > table["NANF"])[0]
        return None if idx.size == 0 else (float(wl_um[idx[0]] * 1e3), float(wl_um[idx[-1]] * 1e3))

    saving_sim = latency_sim["SSMF"] - latency_sim["NANF"]
    saving_pub = latency_pub["SSMF"] - latency_pub["NANF"]
    return Fig1Report(
        stated_cd_vs_workbook_at_1550=cd_check,
        fading=fading,
        first_null_ghz=nulls,
        published_null_ghz_grid=published_nulls,
        preregistered_null_check=pre,
        bandwidth=bandwidth,
        bandwidth_at_1550_ghz=bw1550,
        latency=latency,
        latency_saving_5km_us=(saving_sim, saving_pub),
        latency_saving_5km_fraction=1.0 - latency_sim["NANF"] / latency_sim["SSMF"],
        nanf_bandwidth_min_ghz=(float(sim_bw["NANF"].min()), float(pub_bw["NANF"].min())),
        nanf_over_ssmf_bandwidth_min_ratio=(
            float((sim_bw["NANF"] / sim_bw["SSMF"]).min()),
            float((pub_bw["NANF"] / pub_bw["SSMF"]).min()),
        ),
        nz_dsf_wider_than_nanf_nm=(wider(sim_bw), wider(pub_bw)),
        conventions=(
            "response = 20 log10 |H|, H the small-signal intensity response of a chirp-free link; "
            "3-dB bandwidth = first -3 dB crossing of that response"
        ),
    )


# --- Benchmark C: Fig. 5 -------------------------------------------------------------------------


@dataclass(frozen=True)
class LinkLossSummary:
    """What the Fig. 5 loss column says and what it cannot separate."""

    n_points: int
    wavelength_range_nm: tuple[float, float]
    loss_min_db: float
    loss_min_wavelength_nm: float
    loss_max_db: float
    loss_max_wavelength_nm: float
    distributed_upper_bound_db_per_km: float  # min loss / length, valid at the wavelength below
    distributed_upper_bound_wavelength_nm: float  # the wavelength of the minimum (1610 nm)
    distributed_loss: str  # always "unknown": see the text of `DISTRIBUTED_LOSS_NOT_SEPARABLE`
    rop_nanf_range_dbm: tuple[float, float]
    rop_ssmf_range_dbm: tuple[float, float]


DISTRIBUTED_LOSS_NOT_SEPARABLE = (
    "The column is the insertion loss of the whole assembled link (two NANF pieces, their splice "
    "and the SSMF pigtails). The paper says it includes about 2 dB of pigtail and splice loss "
    "('around 2 dB') and about 0.1 dB for the NANF-NANF splice ('around 0.1 dB'): both are "
    "approximate, "
    "with no uncertainty, no method and no wavelength dependence stated. Subtracting them would "
    "turn two rounded prose numbers into a per-kilometre loss and a spectrum, so the distributed "
    "attenuation stays unknown. What holds is a bound at each wavelength: "
    "distributed(lambda) <= total(lambda) / L, with lumped loss at least 0 and L the stated "
    "length of about 4.76 km (itself approximate, so the bound is not exact either). At the "
    "wavelength of the minimum total, 1610 nm, it is 1.355 dB/km; at 1460 nm, where the total is "
    "largest, it is 1.75 dB/km. A bound taken at "
    "one wavelength says nothing about another."
)


def link_loss_summary(wb: NanfWorkbook, length_km: float = 4.76) -> LinkLossSummary:
    """Summarise Fig. 5 (calibration input). The distributed loss is left unknown."""
    loss = wb[series_key("Fig.5", "link", "NANF loss")]
    rop_nanf = wb[series_key("Fig.5", "link", "ROP@NANF")]
    rop_ssmf = wb[series_key("Fig.5", "link", "ROP@SSMF")]
    for s in (loss, rop_nanf, rop_ssmf):
        if s.role is not DataRole.CALIBRATION_INPUT:
            raise ValueError("Fig. 5 series are calibration inputs")
    y = np.array(loss.y)
    lo, hi = int(np.argmin(y)), int(np.argmax(y))
    return LinkLossSummary(
        n_points=len(loss),
        wavelength_range_nm=(loss.x[0], loss.x[-1]),
        loss_min_db=float(y[lo]),
        loss_min_wavelength_nm=loss.x[lo],
        loss_max_db=float(y[hi]),
        loss_max_wavelength_nm=loss.x[hi],
        distributed_upper_bound_db_per_km=float(y[lo]) / length_km,
        distributed_upper_bound_wavelength_nm=loss.x[lo],
        distributed_loss="unknown",
        rop_nanf_range_dbm=(min(rop_nanf.y), max(rop_nanf.y)),
        rop_ssmf_range_dbm=(min(rop_ssmf.y), max(rop_ssmf.y)),
    )


def distributed_loss_bound_db_per_km(
    wb: NanfWorkbook, wavelength_nm: float, length_km: float = 4.76
) -> float:
    """Upper bound of the distributed loss at one wavelength: total(lambda) / L (lumped >= 0).

    Valid at that wavelength only. L is the stated length (about 4.76 km), itself approximate.
    """
    return link_loss_at(wb, wavelength_nm) / length_km


def link_loss_at(wb: NanfWorkbook, wavelength_nm: float) -> float:
    """Total link loss in dB at a wavelength, linear inside the measured span; never outside.

    This is the loss of the whole link as one number. It is not split into distributed and lumped
    parts and must not be added to the pigtail loss of a profile (that would count it twice).
    """
    loss = wb[series_key("Fig.5", "link", "NANF loss")]
    if not loss.x[0] <= wavelength_nm <= loss.x[-1]:
        raise OutOfValidityRangeError(
            f"{wavelength_nm:g} nm is outside the measured span "
            f"{loss.x[0]:g} to {loss.x[-1]:g} nm; "
            "no extrapolation"
        )
    return float(np.interp(wavelength_nm, loss.x, loss.y))
