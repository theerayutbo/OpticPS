"""Gate E3, source 3: what can be said about Ran et al. (Nat. Commun. 16, 6268, 2025) here.

The article is CC BY-NC-ND 4.0 and this repository is MIT, so nothing of the article is carried
here except bibliographic strings and cited numeric facts (docs/benchmarks/SOURCE_REGISTER.md,
section "Licence conflict"). The cited facts are read from `configs/benchmarks/ran_2025_g652d.yaml`
(wavelength, measured dispersion) and from two constants below (the two published link lengths).

Three things are provided:

1. `source_data_status`: whether the Source Data spreadsheet exists locally (it is never fetched).
2. `chirp_model_gap`: the list of parameters a chirped Mach-Zehnder / complex-field model would
   need and that the cited facts do not give. With these missing the model is not built.
3. An ANALYTICAL subcase from our own derivation, not a reproduction of any published rate.

Derivation of the subcase (our notation). Chirp-free intensity modulation with a small tone at
modulation frequency f puts two optical sidebands at +-f around the carrier. Dispersion gives the
sideband at offset Omega = 2 pi f the phase phi(f) = beta2 L Omega^2 / 2, with
beta2 = -D lambda^2 / (2 pi c). Square-law detection of carrier plus the two sidebands (equal
amplitude, symmetric phases for a real-valued, chirp-free envelope) gives a photocurrent tone of
relative amplitude |cos phi(f)|, so

    H(f) = |cos(pi D L lambda^2 f^2 / c)|,

with nulls where pi |D| L lambda^2 f^2 / c = pi/2 + k pi:

    f_k = sqrt( c (2k + 1) / (2 |D| L lambda^2) ),  k = 0, 1, 2, ...

and the -3 dB (electrical power) point, cos^2 = 1/2, at f_3dB = f_0 / sqrt(2). The real link of
the article is chirped (the authors control chirp on purpose), which replaces cos(phi) by
cos(phi) - alpha sin(phi) for a linear chirp parameter alpha; these chirp-free nulls therefore
are NOT a prediction of the experiment. No wavelength or dispersion default is used anywhere:
every function needs both.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from opticps.benchmarks.catalog import load_source_config
from opticps.benchmarks.comparison import ComparisonResult, ComparisonStatus, Row, refuse

SPEED_OF_LIGHT_M_PER_S = 299_792_458.0
CONFIG_PATH = Path("configs/benchmarks/ran_2025_g652d.yaml")
# Published link lengths with the per-lane rates reported for them (cited facts; register,
# Source 3).
LINK_LENGTHS_KM = (5.0, 10.0)
HEADLINE_RATES_GBPS = {5.0: 256.0, 10.0: 200.0}

# Parameters of a chirped MZM / complex-field model that the cited facts do not state.
CHIRP_MODEL_MISSING = (
    "chirp parameter of the silicon MZM (value and sign)",
    "bias point of the MZM",
    "drive swing and Vpi, and the electrical driver bandwidth",
    "MZM electro-optic bandwidth",
    "symbol rate per lane (only bit rates are cited)",
    "gross versus net definition of the 256 and 200 Gb/s rates",
    "BER definition",
    "launch and received optical power per figure, and link loss",
    "photodiode responsivity, receiver bandwidth and noise",
    "laser relative intensity noise and linewidth",
    "receiver sampling and equaliser training details beyond the tap count",
    "MLSD memory length",
    "settings of the on-chip adaptive dispersion compensation",
    "Source Data spreadsheet (not obtained; licence unverified)",
)


@dataclass(frozen=True)
class SourceDataStatus:
    present: bool
    status: str
    files_listed: tuple[str, ...]


def source_data_status(external_root: Path) -> SourceDataStatus:
    """Look for the Source Data spreadsheet by file name only; nothing is opened or fetched."""
    candidates = tuple(
        sorted(
            str(p.relative_to(external_root))
            for p in external_root.rglob("*")
            if p.is_file() and ("41467_2025_61408" in p.name or "moesm3" in p.name.lower())
        )
    )
    if candidates:
        return SourceDataStatus(
            True, "PRESENT: schema inspection allowed after rights review", candidates
        )
    return SourceDataStatus(
        False,
        "BLOCKED: SOURCE DATA XLSX NOT OBTAINED (LICENCE/REUSE TERMS UNVERIFIED)",
        (),
    )


def chirp_model_gap() -> ComparisonResult:
    """`MODEL GAP: CHIRP` with the parameters the cited facts do not give."""
    return refuse(
        "MODEL GAP: CHIRP. Missing: " + "; ".join(CHIRP_MODEL_MISSING),
        ComparisonStatus.NOT_COMPARABLE,
    )


@dataclass(frozen=True)
class CitedLink:
    wavelength_nm: float
    dispersion_ps_per_nm_km: float


def cited_link(root: Path = Path(".")) -> CitedLink:
    """Wavelength and measured dispersion exactly as the config records them."""
    parameters = load_source_config(root / CONFIG_PATH).parameters
    wavelength = parameters["wavelength_nm"].value
    dispersion = parameters["dispersion_ps_per_nm_km"].value
    if wavelength is None or dispersion is None:
        raise ValueError("config has no wavelength or dispersion for the Ran source")
    return CitedLink(float(wavelength), float(dispersion))


def _check(d_ps_per_nm_km: float, length_km: float, wavelength_nm: float) -> None:
    if not all(math.isfinite(v) for v in (d_ps_per_nm_km, length_km, wavelength_nm)):
        raise ValueError("dispersion, length and wavelength must be finite")
    if wavelength_nm <= 0 or length_km <= 0:
        raise ValueError("wavelength and length must be positive")


def accumulated_dispersion_ps_per_nm(d_ps_per_nm_km: float, length_km: float) -> float:
    """D L in ps/nm."""
    return d_ps_per_nm_km * length_km


def small_signal_response(
    f_hz: float | np.ndarray, d_ps_per_nm_km: float, length_km: float, wavelength_nm: float
) -> np.ndarray:
    """|cos(pi D L lambda^2 f^2 / c)|: chirp-free small-signal IM/DD amplitude response."""
    _check(d_ps_per_nm_km, length_km, wavelength_nm)
    d_si = d_ps_per_nm_km * 1e-6  # s/m^2
    wavelength_m = wavelength_nm * 1e-9
    f = np.asarray(f_hz, dtype=float)
    return np.abs(
        np.cos(math.pi * d_si * length_km * 1e3 * wavelength_m**2 * f**2 / SPEED_OF_LIGHT_M_PER_S)
    )


def null_frequencies_hz(
    d_ps_per_nm_km: float, length_km: float, wavelength_nm: float, count: int = 3
) -> list[float]:
    """First `count` nulls f_k = sqrt(c (2k + 1) / (2 |D| L lambda^2)), in Hz."""
    _check(d_ps_per_nm_km, length_km, wavelength_nm)
    if d_ps_per_nm_km == 0:
        raise ValueError("no null exists without dispersion")
    d_si = abs(d_ps_per_nm_km) * 1e-6
    wavelength_m = wavelength_nm * 1e-9
    base = SPEED_OF_LIGHT_M_PER_S / (2 * d_si * length_km * 1e3 * wavelength_m**2)
    return [math.sqrt(base * (2 * k + 1)) for k in range(count)]


def half_power_frequency_hz(d_ps_per_nm_km: float, length_km: float, wavelength_nm: float) -> float:
    """-3 dB electrical-power frequency, f_0 / sqrt(2)."""
    return null_frequencies_hz(d_ps_per_nm_km, length_km, wavelength_nm, 1)[0] / math.sqrt(2.0)


def ran_rows(root: Path = Path(".")) -> list[Row]:
    """E3 rows for source 3. The headline rates are not reproduced; nothing here is fitted."""
    link = cited_link(root)
    data = source_data_status(root / "data" / "external")
    gap = chirp_model_gap()
    rows = []
    for row_id, length in (("R1", 5.0), ("R2", 10.0)):
        rows.append(
            Row(
                row_id,
                "abstract and Experimental results (cited fact, register Source 3)",
                f"PAM4 lane rate {HEADLINE_RATES_GBPS[length]:.0f} Gb/s over {length:.0f} km, "
                f"{link.wavelength_nm:.0f} nm, rate definition and BER definition not stated",
                "not computed: the transmitter is chirped and no chirp model is built",
                gap,
            )
        )
    rows.append(
        Row(
            "R3",
            "Source Data spreadsheet (figure-linked BER points)",
            "published BER against the FEC thresholds 2.4e-2 (SD, 20% overhead) and "
            "3.8e-3 (HD, 6.7%)",
            "not computed",
            refuse(
                data.status
                if not data.present
                else "BLOCKED: file present but its licence is unverified and E3 did not "
                "inspect it: " + ", ".join(data.files_listed),
                ComparisonStatus.BLOCKED,
            ),
        )
    )
    nulls = {
        length: null_frequencies_hz(link.dispersion_ps_per_nm_km, length, link.wavelength_nm, 1)[0]
        for length in LINK_LENGTHS_KM
    }
    rows.append(
        Row(
            "R4",
            "none: the cited facts give no null or fading frequency",
            "no published null frequency",
            "ANALYTICAL chirp-free first null at "
            + ", ".join(f"{nulls[k] / 1e9:.2f} GHz ({k:.0f} km)" for k in LINK_LENGTHS_KM),
            refuse(
                "NOT COMPARABLE: no published counterpart, and the real link is chirped, "
                "so a chirp-free null is not a prediction of the experiment"
            ),
        )
    )
    return rows
