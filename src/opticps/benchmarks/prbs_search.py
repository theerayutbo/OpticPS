"""B2B-only search for the transmitted pattern (plan R.2 characterisation; P1 to P7).

The design is fixed in `docs/benchmarks/teriphic_prbs/prbs_search_prereg.md`, committed before this
module read any data; the thresholds of `verify` are the ones Fable wrote (advice section 7, P6) and
are constants here, not parameters of a run. Everything is deterministic: there are no seeds.

What this module does and does not do.

* `open_b2b_only` is the only route to a file. It refuses the 10 km name, then the 2 km name, then
  any name that is not the registered B2B name, before anything is opened or hashed, and then goes
  through `teriphic.open_b2b`.
* The search works on a normalised sample array, so the tests run on synthetic streams and never
  touch a capture.
* A recovered sequence is never returned as data. The result holds the generator, the mapping, the
  seed state with its position, and statistics. The status is `INFERRED_REFERENCE (B2B only)` or
  `REFERENCE_SEQUENCE_NOT_RECOVERED`; in both cases BER and SER stay `REFERENCE_SEQUENCE_MISSING`
  (`holdout.require_reference_for_ber` is not touched and refuses an inferred sequence).
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from opticps.benchmarks import teriphic
from opticps.benchmarks.external_capture import ExternalCapture
from opticps.benchmarks.provenance import BenchmarkError, ErrorCode

FloatArray = NDArray[np.float64]
BitArray = NDArray[np.uint8]
IntArray = NDArray[np.int64]
ComplexArray = NDArray[np.complex128]

TWO_KM_NAME = "50G_PAM4_PD1_2km_Subassembly1.bin"
TEN_KM_NAME = "50G_PAM4_PD1_10km_Subassembly1.bin"

# ---------------------------------------------------------------------------- the fixed design
ID_SAMPLES = 8_388_608  # P1: identification window is samples [0, ID_SAMPLES)
TIMING_BLOCK = 32_768  # P3
OFFSET_STEP = 0.25  # P3, samples
EM_ITERATIONS = 100  # P3
PERIOD_MIN_SYMBOLS = 100  # P2
PERIOD_MAX_SYMBOLS = 500_000
PERIOD_PEAK = 0.5
R13_CENTROIDS = (
    -1.5111921833272839, -0.4729772250912633, 0.4953615917438358, 1.4888078166726444,
)  # fmt: skip  # teriphic_e2/b2b_model.yaml, b2b_centroids_normalised
BM_STRETCH_SYMBOLS = 64  # P5
BM_STRETCHES = 8
BM_MIN_AGREE = 3
BM_MAX_COMPLEXITY = 31
VOTE_MIN_PERIODS = 3
SEED_STRETCHES = 16  # P6
# P6 thresholds, as Fable wrote them; not revisited after the run
MISMATCH_FACTOR = 2.0
MISMATCH_MAX = 0.1
LOW_MARGIN_QUANTILE = 0.2
LOW_MARGIN_SHARE = 0.9
SYNDROME_WINNER_MAX = 0.1
SYNDROME_OTHER_MIN = 0.4
PERIODIC_ENTRY_SYNDROME = 0.1  # P4: the periodic candidate enters only if no LFSR is below this
# Amendment A1: a candidate whose recurrence the winner's own regenerated (noise-free) sequence
# satisfies is another description of that sequence, not an "other" candidate for P6 (c).
EQUIVALENT_SYNDROME = 0.01
LANE_DELAY_MAX = 64

STATUS_INFERRED = "INFERRED_REFERENCE (B2B only)"
STATUS_NOT_RECOVERED = "REFERENCE_SEQUENCE_NOT_RECOVERED"
BER_STATUS = "REFERENCE_SEQUENCE_MISSING"
PROXY_NAME = "symbol_mismatch_vs_inferred_sequence"

# Relation a[m] = XOR a[m - l] over the lags l.
GENERATORS: dict[str, tuple[int, ...]] = {
    "PRBS7": (7, 6),
    "PRBS9": (9, 5),
    "PRBS11": (11, 9),
    "PRBS13": (13, 12, 2, 1),
    "PRBS15": (15, 14),
    "PRBS20": (20, 3),
    "PRBS23": (23, 18),
    "PRBS31": (31, 28),
}
# Symbol (ascending level) to a 2-bit code, hi bit first.
MAP_CODES: dict[str, tuple[int, int, int, int]] = {
    "gray": (0, 1, 3, 2),
    "natural": (0, 1, 2, 3),
    "swapped": (0, 2, 1, 3),
}
MODES = ("serial", "lanes")


def default_generators() -> dict[str, tuple[int, ...]]:
    """The named generators of P4 (amendment A1: no reciprocals; BM in P5 covers the rest)."""
    return dict(GENERATORS)


def map_names() -> tuple[str, ...]:
    return tuple(f"{m}{suffix}" for m in MAP_CODES for suffix in ("", "-inv"))


# ---------------------------------------------------------------------------- the file route
def refuse_unless_b2b_name(path: Path) -> Path:
    """The resolved path when both its given and resolved names are the registered B2B name.

    Refuses the 10 km name first, then the 2 km name, then every other name. Opens, hashes and
    stats nothing; resolving a path reads directory entries and link targets only.
    """
    given = teriphic.fold_name(Path(path).name)
    resolved = Path(path).resolve()
    target = teriphic.fold_name(resolved.name)
    for forbidden, label in ((TEN_KM_NAME, "10 km"), (TWO_KM_NAME, "2 km")):
        if teriphic.fold_name(forbidden) in (given, target):
            raise BenchmarkError(
                f"{Path(path).name}: the {label} file is not used by the B2B pattern search;"
                " refused before any open",
                ErrorCode.LEAKAGE_DETECTED,
            )
    b2b = teriphic.fold_name(teriphic.B2B_FILENAME)
    if given != b2b or target != b2b:
        raise BenchmarkError(
            f"{Path(path).name}: the pattern search opens only {teriphic.B2B_FILENAME}; refused",
            ErrorCode.LEAKAGE_DETECTED,
        )
    return resolved


def open_b2b_only(path: Path) -> ExternalCapture:
    """Open the B2B capture read-only after the name checks and the teriphic gate."""
    return teriphic.open_b2b(refuse_unless_b2b_name(Path(path)))


# ---------------------------------------------------------------------------- P2 period scan
@dataclass(frozen=True)
class PeriodScan:
    period_symbols: int | None
    lag_samples: int | None
    peak_at_period: float | None
    largest_peak: float
    largest_peak_lag_samples: int
    lags_searched_samples: tuple[int, int]

    def as_dict(self) -> dict[str, Any]:
        return {
            "period_symbols": self.period_symbols,
            "lag_samples": self.lag_samples,
            "r_at_period": _round(self.peak_at_period),
            "largest_r": _round(self.largest_peak),
            "largest_r_lag_samples": self.largest_peak_lag_samples,
            "lags_searched_samples": list(self.lags_searched_samples),
            "rule": f"smallest local maximum with r/r0 >= {PERIOD_PEAK}",
        }


def period_scan(x: FloatArray, spp: float) -> PeriodScan:
    """Autocorrelation of the mean-removed waveform (biased), lags 100 to 500000 symbols."""
    n = int(x.size)
    max_lag = min(int(PERIOD_MAX_SYMBOLS * spp), n // 2)
    min_lag = int(math.ceil(PERIOD_MIN_SYMBOLS * spp))
    if max_lag <= min_lag + 2:
        raise BenchmarkError("period scan: the record is too short for the lag range")
    size = 1 << int(math.ceil(math.log2(n + max_lag)))
    spectrum = np.fft.rfft(x - x.mean(), size)
    power = spectrum.real**2 + spectrum.imag**2
    del spectrum
    r = np.fft.irfft(power, size)[: max_lag + 1]
    del power
    r = r / r[0]
    window = int(math.ceil(spp))
    zone = r[min_lag : max_lag + 1]
    largest_at = int(np.argmax(zone)) + min_lag
    found: int | None = None
    for candidate in np.flatnonzero(zone >= PERIOD_PEAK) + min_lag:
        lo, hi = max(int(candidate) - window, 0), int(candidate) + window + 1
        if r[candidate] >= r[lo:hi].max():
            found = int(candidate)
            break
    return PeriodScan(
        period_symbols=None if found is None else int(round(found / spp)),
        lag_samples=found,
        peak_at_period=None if found is None else float(r[found]),
        largest_peak=float(r[largest_at]),
        largest_peak_lag_samples=largest_at,
        lags_searched_samples=(min_lag, max_lag),
    )


# ---------------------------------------------------------------------------- P3 timing, decisions
@dataclass(frozen=True)
class Timing:
    spp: float
    line_phase: float  # radians at sample 0
    offset: float  # samples, chosen on the identification window
    line_strength: float
    base_instants: FloatArray  # sample instants of the line peaks, before the offset

    def instants(self) -> FloatArray:
        return self.base_instants + self.offset


def _line_blocks(x: FloatArray, start: int, blocks: int, block: int, f0: float) -> ComplexArray:
    out = np.empty(blocks, dtype=np.complex128)
    for k in range(blocks):
        a = start + k * block
        seg = x[a : a + block]
        s = (seg - seg.mean()) ** 2
        s = s - s.mean()
        out[k] = np.dot(s, np.exp(-2j * np.pi * f0 * np.arange(a, a + block)))
    return out


def fit_line(x: FloatArray, id_samples: int, spp0: float, block: int) -> tuple[float, float, float]:
    """(line frequency in cycles per sample, phase at sample 0, strength) from the squared signal.

    Block demodulation at 1/spp0, the unwrapped block phases fitted by a weighted straight line.
    """
    blocks = id_samples // block
    if blocks < 4:
        raise BenchmarkError("timing: the identification window holds fewer than 4 blocks")
    f0 = 1.0 / spp0
    c = _line_blocks(x, 0, blocks, block, f0)
    t = np.arange(blocks) * block + (block - 1) / 2.0
    phase = np.unwrap(np.angle(c))
    slope, intercept = np.polyfit(t, phase, 1, w=np.abs(c))
    ref = x[: blocks * block]
    strength = float(np.abs(c).mean() / (block * np.std((ref - ref.mean()) ** 2)))
    return f0 + float(slope) / (2.0 * np.pi), float(intercept), strength


def hold_residual_symbols(
    x: FloatArray, id_samples: int, f: float, phase0: float, spp0: float, block: int
) -> float | None:
    """Reported only: RMS (symbols) of the verification block line phases against the held line."""
    blocks = (x.size - id_samples) // block
    if blocks < 1:
        return None
    f0 = 1.0 / spp0
    c = _line_blocks(x, id_samples, blocks, block, f0)
    t = id_samples + np.arange(blocks) * block + (block - 1) / 2.0
    predicted = phase0 + 2.0 * np.pi * (f - f0) * t
    wrapped = np.angle(np.exp(1j * (np.angle(c) - predicted)))
    return float(np.sqrt(np.mean(wrapped**2)) / (2.0 * np.pi))


def centre_samples(x: FloatArray, t: FloatArray) -> FloatArray:
    """Linear interpolation of x at the sample instants t."""
    i0 = np.floor(t).astype(np.int64)
    frac = t - i0
    return np.asarray(x[i0] * (1.0 - frac) + x[i0 + 1] * frac, dtype=np.float64)


def thresholds(centroids: Sequence[float] = R13_CENTROIDS) -> FloatArray:
    c = np.asarray(centroids, dtype=np.float64)
    return np.asarray((c[1:] + c[:-1]) / 2.0, dtype=np.float64)


def decide(
    values: FloatArray, centroids: Sequence[float] = R13_CENTROIDS
) -> tuple[IntArray, FloatArray]:
    """Nearest-centroid symbols (0 to 3) and the margin: distance to the nearest threshold."""
    th = thresholds(centroids)
    symbols = np.searchsorted(th, values).astype(np.int64)
    margin = np.min(np.abs(values[:, None] - th[None, :]), axis=1)
    return symbols, margin


def recover_timing(x: FloatArray, fs: float, baud: float, id_samples: int, block: int) -> Timing:
    spp0 = fs / baud
    f, phase0, strength = fit_line(x, id_samples, spp0, block)
    spp = 1.0 / f
    n_min = int(math.ceil(phase0 / (2.0 * np.pi)))
    n_max = int(math.floor(f * (x.size - 2 - spp) + phase0 / (2.0 * np.pi)))
    base = (np.arange(n_min, n_max + 1) - phase0 / (2.0 * np.pi)) / f
    base = base[(base >= 0.0) & (base + spp <= x.size - 2)]
    ident = np.asarray(base[base < id_samples - spp], dtype=np.float64)
    if ident.size < 1000:
        raise BenchmarkError("timing: fewer than 1000 symbols in the identification window")
    cents = np.asarray(R13_CENTROIDS)
    best_cost, best_offset = math.inf, 0.0
    for j in range(int(spp / OFFSET_STEP)):
        offset = j * OFFSET_STEP
        v = centre_samples(x, ident + offset)
        cost = float(np.sum(np.min((v[:, None] - cents[None, :]) ** 2, axis=1)))
        if cost < best_cost:
            best_cost, best_offset = cost, offset
    return Timing(spp, phase0, best_offset, strength, np.asarray(base, dtype=np.float64))


def decision_error_estimate(
    values: FloatArray, symbols: IntArray, centroids: Sequence[float] = R13_CENTROIDS
) -> dict[str, Any]:
    """P3: Gaussian-mixture estimate of the symbol error rate from the centre samples."""
    th = thresholds(centroids)
    pi = np.empty(4)
    mu = np.empty(4)
    var = np.empty(4)
    for j in range(4):
        v = values[symbols == j]
        if v.size < 10:
            raise BenchmarkError(f"decision estimate: level {j} has fewer than 10 samples")
        pi[j], mu[j], var[j] = v.size / values.size, v.mean(), max(v.var(), 1e-12)
    for _ in range(EM_ITERATIONS):
        log_p = -0.5 * (values[:, None] - mu) ** 2 / var - 0.5 * np.log(var) + np.log(pi)
        log_p -= log_p.max(axis=1, keepdims=True)
        resp = np.exp(log_p)
        resp /= resp.sum(axis=1, keepdims=True)
        nk = resp.sum(axis=0)
        pi = nk / values.size
        mu = (resp * values[:, None]).sum(axis=0) / nk
        var = np.maximum((resp * (values[:, None] - mu) ** 2).sum(axis=0) / nk, 1e-12)
    estimate = 0.0
    for j in range(4):
        sigma = math.sqrt(var[j])
        for k in (j - 1, j):
            if 0 <= k < 3:
                estimate += (
                    float(pi[j]) * 0.5 * math.erfc(abs(th[k] - mu[j]) / sigma / math.sqrt(2))
                )
    return {
        "estimate": float(estimate),
        "means": [float(v) for v in mu],
        "sigmas": [math.sqrt(float(v)) for v in var],
        "shares": [float(v) for v in pi],
    }


# ---------------------------------------------------------------------------- bits and syndromes
def _code_table(name: str) -> tuple[tuple[int, int, int, int], bool]:
    inverted = name.endswith("-inv")
    base = name.removesuffix("-inv")
    if base not in MAP_CODES:
        raise BenchmarkError(f"unknown mapping {name!r}")
    return MAP_CODES[base], inverted


def symbols_to_bits(symbols: IntArray, name: str) -> tuple[BitArray, BitArray]:
    """(hi, lo) bit streams of the decided symbols under the named mapping."""
    codes, inverted = _code_table(name)
    s = 3 - symbols if inverted else symbols
    code = np.asarray(codes, dtype=np.int64)[s]
    return (code >> 1).astype(np.uint8), (code & 1).astype(np.uint8)


def bits_to_symbols(hi: BitArray, lo: BitArray, name: str) -> IntArray:
    codes, inverted = _code_table(name)
    inverse = np.empty(4, dtype=np.int64)
    for symbol, code in enumerate(codes):
        inverse[code] = symbol
    s = inverse[hi.astype(np.int64) * 2 + lo.astype(np.int64)]
    return np.asarray(3 - s if inverted else s, dtype=np.int64)


def serial_stream(hi: BitArray, lo: BitArray) -> BitArray:
    out = np.empty(hi.size * 2, dtype=np.uint8)
    out[0::2], out[1::2] = hi, lo
    return out


def syndrome(bits: BitArray, lags: Sequence[int], start: int, stop: int) -> float:
    """Fraction of positions in bits[start:stop] violating a[m] = XOR a[m - l]."""
    n = max(lags)
    seg = bits[start:stop]
    if seg.size <= n + 16:
        raise BenchmarkError("syndrome: the window is too short")
    v = seg[n:].copy()
    for lag in lags:
        v ^= seg[n - lag : seg.size - lag]
    return float(v.mean())


def berlekamp_massey(bits: Sequence[int]) -> tuple[int, tuple[int, ...]]:
    """Linear complexity and the lags of the shortest recurrence a[m] = XOR a[m - l] over GF(2)."""
    n = len(bits)
    c = [0] * (n + 1)
    b = [0] * (n + 1)
    c[0] = b[0] = 1
    length, shift = 0, 1
    for i in range(n):
        d = bits[i]
        for j in range(1, length + 1):
            d ^= c[j] & bits[i - j]
        if d == 0:
            shift += 1
            continue
        previous = c.copy()
        for j in range(n + 1 - shift):
            c[j + shift] ^= b[j]
        if 2 * length <= i:
            length = i + 1 - length
            b = previous
            shift = 1
        else:
            shift += 1
    return length, tuple(j for j in range(length, 0, -1) if c[j])


def lfsr_extend(
    lags: Sequence[int], seed: Sequence[int] | BitArray, position: int, lo: int, hi: int
) -> BitArray:
    """Bits [lo, hi) of the recurrence that has `seed` (n = max lag bits) at `position`."""
    n = max(lags)
    if len(seed) != n or not lo <= position <= hi - n:
        raise BenchmarkError("lfsr_extend: seed outside the requested range")
    buf = [0] * (hi - lo)
    buf[position - lo : position - lo + n] = [int(v) for v in seed]
    for m in range(position + n - lo, hi - lo):
        v = 0
        for lag in lags:
            v ^= buf[m - lag]
        buf[m] = v
    others = [lag for lag in lags if lag != n]
    for j in range(position - lo - 1, -1, -1):
        v = buf[j + n]
        for lag in others:
            v ^= buf[j + n - lag]
        buf[j] = v
    return np.asarray(buf, dtype=np.uint8)


def sliding_min(values: FloatArray, width: int) -> FloatArray:
    if values.size < width:
        raise BenchmarkError("sliding_min: the window is shorter than the stretch")
    view = np.lib.stride_tricks.sliding_window_view(values, width)
    return np.asarray(view.min(axis=1), dtype=np.float64)


def best_stretches(margin: FloatArray, width: int, count: int) -> list[int]:
    """Starts of the `count` disjoint stretches with the largest minimum margin (greedy)."""
    window_min = sliding_min(margin, width)
    order = np.argsort(-window_min, kind="stable")
    chosen: list[int] = []
    for start in order:
        s = int(start)
        if all(abs(s - other) >= width for other in chosen):
            chosen.append(s)
            if len(chosen) == count:
                break
    return chosen


# ---------------------------------------------------------------------------- candidates
@dataclass(frozen=True)
class Candidate:
    generator: str
    lags: tuple[int, ...]
    mapping: str
    mode: str

    @property
    def name(self) -> str:
        return f"{self.generator}|{self.mapping}|{self.mode}"


def bm_candidates(
    symbols: IntArray, margin: FloatArray, id_symbols: int, maps: Sequence[str]
) -> list[tuple[str, tuple[int, ...], int]]:
    """P5: (mapping, lags, stretches agreeing) for every polynomial seen in >= 3 stretches."""
    starts = best_stretches(margin[:id_symbols], BM_STRETCH_SYMBOLS, BM_STRETCHES)
    found: list[tuple[str, tuple[int, ...], int]] = []
    for name in maps:
        hi, lo = symbols_to_bits(symbols[:id_symbols], name)
        stream = serial_stream(hi, lo)
        counts: dict[tuple[int, ...], int] = {}
        for s in starts:
            piece = [int(v) for v in stream[2 * s : 2 * (s + BM_STRETCH_SYMBOLS)]]
            length, lags = berlekamp_massey(piece)
            if 0 < length <= BM_MAX_COMPLEXITY and lags:
                counts[lags] = counts.get(lags, 0) + 1
        for lags, count in sorted(counts.items()):
            if count >= BM_MIN_AGREE:
                found.append((name, lags, count))
    return found


def build_candidates(
    generators: Mapping[str, tuple[int, ...]],
    maps: Sequence[str],
    bm: Sequence[tuple[str, tuple[int, ...], int]],
) -> list[Candidate]:
    out: list[Candidate] = []
    seen: set[tuple[tuple[int, ...], str, str]] = set()
    entries: list[tuple[str, tuple[int, ...], str | None]] = [
        (name, lags, None) for name, lags in generators.items()
    ]
    entries += [(f"BM{lags}", lags, mapping) for mapping, lags, _ in bm]
    for generator, lags, only_map in entries:
        for mapping in maps:
            if only_map is not None and mapping != only_map:
                continue
            for mode in MODES:
                key = (tuple(lags), mapping, mode)
                if key in seen:
                    continue
                seen.add(key)
                out.append(Candidate(generator, tuple(lags), mapping, mode))
    return out


@dataclass(frozen=True)
class Streams:
    hi: dict[str, BitArray]
    lo: dict[str, BitArray]
    serial: dict[str, BitArray]

    @classmethod
    def build(cls, symbols: IntArray, maps: Sequence[str]) -> Streams:
        hi, lo, serial = {}, {}, {}
        for name in maps:
            hi[name], lo[name] = symbols_to_bits(symbols, name)
            serial[name] = serial_stream(hi[name], lo[name])
        return cls(hi, lo, serial)


def candidate_syndrome(cand: Candidate, streams: Streams, first: int, last: int) -> float:
    """Syndrome of one candidate on the symbol window [first, last)."""
    if cand.mode == "serial":
        return syndrome(streams.serial[cand.mapping], cand.lags, 2 * first, 2 * last)
    return max(
        syndrome(streams.hi[cand.mapping], cand.lags, first, last),
        syndrome(streams.lo[cand.mapping], cand.lags, first, last),
    )


# ---------------------------------------------------------------------------- P6 verification
def _regenerate_stream(
    obs: BitArray, lags: tuple[int, ...], margin: FloatArray, id_symbols: int, bps: int
) -> tuple[BitArray, dict[str, Any]]:
    """Seed from the best stretches of the identification window; the stream over all symbols."""
    n = max(lags)
    width = -(-n // bps)
    total_bits = obs.size
    starts = best_stretches(margin[:id_symbols], width, SEED_STRETCHES)
    id_bits = id_symbols * bps
    best: tuple[int, int] | None = None
    for s in starts:
        reg = lfsr_extend(lags, obs[s * bps : s * bps + n], s * bps, 0, id_bits)
        wrong = int((reg != obs[:id_bits]).reshape(-1, bps).any(axis=1).sum())
        if best is None or wrong < best[0]:
            best = (wrong, s)
    assert best is not None
    start = best[1]
    seed = obs[start * bps : start * bps + n]
    full = lfsr_extend(lags, seed, start * bps, 0, total_bits)
    info = {
        "seed_stretch_symbol": start,
        "seed_bits": "".join(str(int(v)) for v in seed),
        "id_window_symbol_mismatches": best[0],
    }
    return full, info


def lane_delay(hi: BitArray, lo: BitArray) -> int | None:
    """Reported only: d in 0..64 with one regenerated lane an exact shift of the other, or None."""
    span, base = 4096, LANE_DELAY_MAX
    for d in range(LANE_DELAY_MAX + 1):
        if np.array_equal(hi[base : base + span], lo[base - d : base + span - d]):
            return d
        if np.array_equal(lo[base : base + span], hi[base - d : base + span - d]):
            return d
    return None


def regenerate_lfsr(
    cand: Candidate,
    streams: Streams,
    symbols: IntArray,
    margin: FloatArray,
    id_symbols: int,
) -> tuple[IntArray, dict[str, Any]]:
    """The symbols the candidate regenerates over all positions, and the seed record."""
    if cand.mode == "serial":
        full, serial_info = _regenerate_stream(
            streams.serial[cand.mapping], cand.lags, margin, id_symbols, 2
        )
        return bits_to_symbols(full[0::2], full[1::2], cand.mapping), serial_info
    hi, info_hi = _regenerate_stream(streams.hi[cand.mapping], cand.lags, margin, id_symbols, 1)
    lo, info_lo = _regenerate_stream(streams.lo[cand.mapping], cand.lags, margin, id_symbols, 1)
    delay = lane_delay(hi, lo) if hi.size > 2 * (LANE_DELAY_MAX + 4096) else None
    lane_info: dict[str, Any] = {
        "hi_lane": info_hi,
        "lo_lane": info_lo,
        "lane_delay_0_to_64": delay,
    }
    return bits_to_symbols(hi, lo, cand.mapping), lane_info


def majority_vote(symbols: IntArray, period: int, id_symbols: int) -> IntArray:
    """Per-position majority over the identification window (ties to the smaller symbol)."""
    pattern = np.empty(period, dtype=np.int64)
    for r in range(period):
        counts = np.bincount(symbols[r:id_symbols:period], minlength=4)
        pattern[r] = int(np.argmax(counts))
    return pattern


def mismatch_stats(
    regenerated: IntArray, symbols: IntArray, margin: FloatArray, first: int
) -> dict[str, Any]:
    """P6 (a) and (b) inputs on the verification window [first, end)."""
    wrong = regenerated[first:] != symbols[first:]
    m = margin[first:]
    low = float(np.quantile(m, LOW_MARGIN_QUANTILE))
    count = int(wrong.sum())
    in_low = int((wrong & (m <= low)).sum())
    return {
        "symbols": int(m.size),
        "mismatches": count,
        "mismatch_rate": count / m.size,
        "low_margin_cutoff": low,
        "mismatches_in_lowest_20pct_margin": in_low,
        "share_in_lowest_20pct_margin": (in_low / count) if count else None,
        "median_margin_of_mismatches": float(np.median(m[wrong])) if count else None,
    }


def _round(v: float | None, digits: int = 6) -> float | None:
    return None if v is None else round(float(v), digits)


# ---------------------------------------------------------------------------- the whole search
def run_search(
    x: FloatArray,
    fs: float,
    baud: float,
    *,
    id_samples: int = ID_SAMPLES,
    timing_block: int = TIMING_BLOCK,
    generators: Mapping[str, tuple[int, ...]] | None = None,
    maps: Sequence[str] | None = None,
) -> dict[str, Any]:
    """P1 to P7 on a normalised waveform. Returns the result record (no sequence)."""
    gens = dict(default_generators() if generators is None else generators)
    map_list = tuple(map_names() if maps is None else maps)
    x = np.asarray(x, dtype=np.float64)
    if x.size <= id_samples + 4 * timing_block:
        raise BenchmarkError("search: the record is too short for the identification window")

    spp0 = fs / baud
    scan = period_scan(x, spp0)

    timing = recover_timing(x, fs, baud, id_samples, timing_block)
    instants = timing.instants()
    centre = centre_samples(x, instants)
    symbols, margin = decide(centre)
    id_symbols = int(np.searchsorted(instants, id_samples))
    total = int(symbols.size)
    if id_symbols < 1000 or total - id_symbols < 1000:
        raise BenchmarkError("search: a window holds fewer than 1000 symbols")
    estimate = decision_error_estimate(centre[:id_symbols], symbols[:id_symbols])
    f_line = 1.0 / timing.spp
    hold = hold_residual_symbols(x, id_samples, f_line, timing.line_phase, spp0, timing_block)

    bm = bm_candidates(symbols, margin, id_symbols, map_list)
    candidates = build_candidates(gens, map_list, bm)
    streams = Streams.build(symbols, map_list)
    rows: list[dict[str, Any]] = []
    for cand in candidates:
        rows.append(
            {
                "candidate": cand.name,
                "lags": list(cand.lags),
                "syndrome_identification": candidate_syndrome(cand, streams, 0, id_symbols),
                "syndrome_verification": candidate_syndrome(cand, streams, id_symbols, total),
            }
        )

    best_id = min(range(len(rows)), key=lambda i: rows[i]["syndrome_identification"])
    periodic = (
        scan.period_symbols is not None
        and rows[best_id]["syndrome_identification"] >= PERIODIC_ENTRY_SYNDROME
        and scan.period_symbols * VOTE_MIN_PERIODS <= id_symbols
    )

    outcome: dict[str, Any]
    winner_record: dict[str, Any] | None = None
    if periodic:
        assert scan.period_symbols is not None
        p = scan.period_symbols
        pattern = majority_vote(symbols, p, id_symbols)
        regenerated = pattern[np.arange(total) % p]
        lag_violation = float(np.mean(symbols[id_symbols:] != symbols[id_symbols - p : total - p]))
        stats = mismatch_stats(regenerated, symbols, margin, id_symbols)
        equivalent = _equivalent(candidates, regenerated, map_list, total)
        others = [
            r["syndrome_verification"] for r, eq in zip(rows, equivalent, strict=True) if not eq
        ]
        winner_record = {
            "kind": "periodic",
            "period_symbols": p,
            "syndrome_verification": lag_violation,
            "periodic_syndrome_is": "fraction of symbols differing from the symbol P earlier",
        }
        outcome = verdict(stats, estimate["estimate"], lag_violation, others)
    else:
        winner = candidates[best_id]
        regenerated, seed_info = regenerate_lfsr(winner, streams, symbols, margin, id_symbols)
        stats = mismatch_stats(regenerated, symbols, margin, id_symbols)
        equivalent = _equivalent(candidates, regenerated, map_list, total)
        others = [
            r["syndrome_verification"]
            for i, (r, eq) in enumerate(zip(rows, equivalent, strict=True))
            if i != best_id and not eq
        ]
        winner_record = {
            "kind": "lfsr",
            "candidate": winner.name,
            "generator": winner.generator,
            "lags": list(winner.lags),
            "mapping": winner.mapping,
            "mode": winner.mode,
            "seed": seed_info,
            "syndrome_identification": rows[best_id]["syndrome_identification"],
            "syndrome_verification": rows[best_id]["syndrome_verification"],
            "equivalent_descriptions": [
                c.name for c, eq in zip(candidates, equivalent, strict=True) if eq
            ],
            "named_description": next(
                (
                    c.name
                    for c, eq in zip(candidates, equivalent, strict=True)
                    if eq and not c.generator.startswith("BM")
                ),
                None,
            ),
        }
        outcome = verdict(
            stats, estimate["estimate"], rows[best_id]["syndrome_verification"], others
        )

    verified = outcome["verified"]
    result: dict[str, Any] = {
        "status": STATUS_INFERRED if verified else STATUS_NOT_RECOVERED,
        "provenance": "INFERRED" if verified else None,
        "reference_sequence": BER_STATUS,
        "ber_and_ser": BER_STATUS,
        "proxy_name": PROXY_NAME,
        "p2_period_scan": scan.as_dict(),
        "p3_timing": {
            "spp_nominal": spp0,
            "spp_fitted": timing.spp,
            "offset_samples": timing.offset,
            "line_strength": _round(timing.line_strength),
            "symbols_total": total,
            "symbols_identification": id_symbols,
            "symbols_verification": total - id_symbols,
            "verification_line_phase_rms_symbols": _round(hold),
        },
        "p3_decision_error_estimate": {
            k: ([_round(v) for v in val] if isinstance(val, list) else _round(val))
            for k, val in estimate.items()
        },
        "p5_bm_candidates": [
            {"mapping": m, "lags": list(lags), "stretches_agreeing": c} for m, lags, c in bm
        ],
        "p6": outcome,
        "winner": winner_record if verified else _failing_winner(winner_record),
        "p4_table": [
            {
                "candidate": r["candidate"],
                "lags": r["lags"],
                "syndrome_identification": _round(r["syndrome_identification"]),
                "syndrome_verification": _round(r["syndrome_verification"]),
            }
            for r in rows
        ],
    }
    return result


def _equivalent(
    candidates: Sequence[Candidate], regenerated: IntArray, maps: Sequence[str], total: int
) -> list[bool]:
    """Amendment A1: which candidates the winner's regenerated sequence satisfies exactly."""
    clean = Streams.build(regenerated, maps)
    return [candidate_syndrome(c, clean, 0, total) < EQUIVALENT_SYNDROME for c in candidates]


def _failing_winner(record: dict[str, Any] | None) -> dict[str, Any] | None:
    """The lowest-syndrome candidate, named for the record; no seed when not verified."""
    if record is None:
        return None
    return {k: v for k, v in record.items() if k != "seed"}


def verdict(
    stats: Mapping[str, Any], estimate: float, winner_syndrome: float, others: Sequence[float]
) -> dict[str, Any]:
    rate = float(stats["mismatch_rate"])
    share = stats["share_in_lowest_20pct_margin"]
    a = rate <= MISMATCH_FACTOR * estimate and rate <= MISMATCH_MAX
    b = True if share is None else float(share) >= LOW_MARGIN_SHARE
    others_min = min(others) if others else math.inf
    c_winner = winner_syndrome < SYNDROME_WINNER_MAX
    c_others = others_min > SYNDROME_OTHER_MIN
    not_unique = c_winner and any(v < SYNDROME_WINNER_MAX for v in others)
    return {
        "verified": bool(a and b and c_winner and c_others),
        "a_mismatch_rate_within_limits": bool(a),
        "b_mismatches_at_low_margin": bool(b),
        "c_winner_syndrome_below_0.1": bool(c_winner),
        "c_every_other_syndrome_above_0.4": bool(c_others),
        "not_unique": bool(not_unique),
        "mismatch_rate": _round(rate),
        "decision_error_estimate": _round(estimate),
        "mismatch_limit_2x_estimate": _round(MISMATCH_FACTOR * estimate),
        "other_candidates_lowest_verification_syndrome": _round(others_min),
        "stats": {k: (_round(v) if isinstance(v, float) else v) for k, v in stats.items()},
        "thresholds": {
            "mismatch_factor": MISMATCH_FACTOR,
            "mismatch_max": MISMATCH_MAX,
            "low_margin_quantile": LOW_MARGIN_QUANTILE,
            "low_margin_share": LOW_MARGIN_SHARE,
            "winner_syndrome_max": SYNDROME_WINNER_MAX,
            "other_syndrome_min": SYNDROME_OTHER_MIN,
        },
    }
