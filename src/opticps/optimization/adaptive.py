"""Select a symmetric M-PAM distribution from training data only.

Two paths share this module.

Legacy PAM4 path (`select_distribution`, `design_point_selection`, `assert_disjoint`): a
one-parameter grid over P(+-3) with the unchanged PAM4 draw order. Its output is pinned by the
byte anchor and is left exactly as it was.

Generic path (`optimise_symmetric`, `select_on_acquisitions`): M = 4, 8, 16 over the pair
probabilities q_j = P(+-x_j), sum q_j = 1/2, with every q_j in [1/n, 1/2], n the block
length (so every pair can quantise to a nonzero count; a bound that neither PLAN nor the
roadmap states). The generic
path forces `quadrature="common_grid"` in `gaussian_rates` whenever the channel estimate has
unequal per-level sigma, M = 4 included (a fitted channel never has exactly equal sigma). The
legacy path does not: at M = 4 it keeps the Gauss-Hermite kernel, so a legacy and a generic
result at M = 4 agree to the Gauss-Hermite error (about 1e-8 bit at the committed spread
1.005), not bit for bit.

What the generic optimiser claims, and no more. Every optimum below is an optimum over the
constrained set q_j >= 1/n, not over the whole simplex; the selection reports when the floor is
active at the continuous optimum (`parameters["floor_active_pairs"]`).
- metric "smd": I(X;Y) at fixed channel is concave in P and the symmetric box is a linear image
  of a convex set, so a local maximum of the continuous objective over that set is global
  (concavity holds on the convex subset). The continuous
  optimum is therefore "global for the unquantised SMD objective over the constrained set, on
  this channel estimate", and only that. Concavity is checked numerically on midpoints in the
  tests, and a multistart agreement check is run and logged.
- metric "bmd": R_BMD is not shown to be concave. The continuous optimum is "best of N starts",
  where N and every start (start point, final q, objective, iterations, status) are logged.
- The deliverable objective is rate(P) - rate_loss(quantize_symmetric_composition(P, n)). The
  second term depends on P only through integer counts, so it is piecewise constant and the
  objective is a staircase. The continuous rate is optimised, then the exact quantised
  objective is evaluated at every start endpoint, at uniform and on a Maxwell-Boltzmann grid
  (both signs), and the argmax over those logged candidates is selected. That argmax is the
  best of the candidates tried, not a proven optimum of the staircase. A candidate whose
  quantisation gives a positive probability a zero count raises in the matcher; it is logged
  as infeasible and is never selected.
- The uniform candidate is the direct (unshaped) mapping at M a power of two: it maps bits
  straight onto labels as `frame.py` `direct_uniform` does and pays no matcher loss, so its
  objective is its rate. This holds for every uniform PMF seen by the generic path
  (candidates, `evaluate_menu`, `fixed_menu`, `best_fixed`). The legacy `select_distribution`
  is not changed and still charges its uniform member the CCDM loss, a known limitation of the
  committed v1.x PAM4 result (see docs/ROADMAP_STATUS.md).

Seed streams. The legacy path uses `np.random.default_rng(seed)` directly (training capture)
and `[seed, 77]` in demo.py. The generic path draws only from `SeedSequence([seed, key])`:
key 1 simulated payload, key 2 simulated noise (spawned one child per acquisition), key 3
Dirichlet starts. Equal seeds across these streams are therefore independent.

Simulated acquisitions are noise realisations of ONE payload (the symbol sequence is drawn once
and shared); any interval computed over them reflects noise only, not payload variation.

Leakage guard: `select_on_acquisitions` takes training acquisitions plus only the identifiers of
held-out acquisitions. It recomputes the SHA-256 of every training acquisition's samples and
raises when it differs from the declared `content_sha256`, then refuses overlapping ids or
content hashes. What it cannot see: a truncated, re-exported or re-acquired copy of a test
capture has different bytes and passes; that is a documented limit of the guard, not a
guarantee that no test-derived samples enter selection.
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize

from opticps.distribution_matching.ccdm import (
    ConstantCompositionMatcher,
    DistributionMatcherError,
)
from opticps.modulation.pam import SUPPORTED_ORDERS, pam_levels
from opticps.optimization.rates import gaussian_rates, noise_sigma_from_psnr_db, psnr_for_rate
from opticps.shaping.distributions import (
    OUTER70,
    PS70,
    PS80,
    UNIFORM,
    lambda_of_symmetric_pam4,
    mb_for_entropy,
    pairs_of,
    symmetric_from_pairs,
    symmetric_pam4,
)

LEGACY_FAMILY = "symmetric_pam4_p_outer"
GENERIC_FAMILY = "symmetric_pairs"

# SeedSequence stream keys of the generic path (see the module docstring).
STREAM_SIM_PAYLOAD = 1
STREAM_SIM_NOISE = 2
STREAM_DIRICHLET_STARTS = 3

SIMULATION_LABEL = "noise-realisation, single payload"
_SIGMA_EQUAL_TOL = 1e-12  # same tolerance as rates._SPREAD_EQUAL_TOL


class DataLeakageError(ValueError):
    """A capture was used for both tuning and final evaluation."""


def assert_disjoint(training_ids: Iterable[str], test_ids: Iterable[str]) -> None:
    """Raise if any capture identifier appears in both sets (legacy; identifiers only).

    This compares names. It cannot see the same acquisition under two different names, so
    new code uses `assert_independent` on `AcquisitionId`, which also compares content hashes.
    """
    overlap = set(training_ids) & set(test_ids)
    if overlap:
        raise DataLeakageError(f"Captures used for both tuning and test: {sorted(overlap)}")


@dataclass(frozen=True)
class ChannelEstimate:
    """Per-level Gaussian model fitted to training data."""

    means: list[float]
    sigmas: list[float]
    samples: int


def estimate_channel(
    indices: NDArray[np.integer], received: NDArray[np.floating], order: int = 4
) -> ChannelEstimate:
    """Fit a mean and standard deviation for each of the `order` levels (default 4)."""
    indices = np.asarray(indices)
    received = np.asarray(received, dtype=float)
    if indices.size != received.size:
        raise ValueError("Reference and received lengths differ")
    means, sigmas = [], []
    for level in range(order):
        values = received[indices == level]
        if values.size < 2:
            raise ValueError(f"Training data has too few samples of level {level}")
        means.append(float(values.mean()))
        sigmas.append(float(values.std(ddof=1)))
    return ChannelEstimate(means, sigmas, int(indices.size))


def simulate_training_capture(
    psnr_db: float, samples: int, seed: int, order: int = 4
) -> tuple[NDArray[np.int64], NDArray[np.float64]]:
    """Return simulated, uniformly sent training symbols through peak-limited AWGN.

    The levels are the odd integers of `pam_levels(order)` (spacing 2) and sigma is twice the
    unipolar sigma of `noise_sigma_from_psnr_db`. The draw order is the legacy one: indices
    first, then noise, from `default_rng(seed)`; order 4 reproduces the old stream exactly.
    """
    rng = np.random.default_rng(seed)
    indices = rng.integers(0, order, samples)
    sigma = 2.0 * noise_sigma_from_psnr_db(psnr_db, order)
    return indices, pam_levels(order)[indices] + rng.normal(0.0, sigma, samples)


_LEGACY_SELECTION_KEYS = (
    "p_outer",
    "probabilities",
    "lambda_value",
    "objective",
    "metric",
    "block_length",
    "source",
    "channel",
    "candidates",
)


@dataclass(frozen=True)
class Selection:
    """Chosen distribution, with the full record of how it was chosen.

    `p_outer` is P(+-(M-1)) and is set only for M = 4 (None otherwise); `lambda_value` is the
    Maxwell-Boltzmann lambda of the PMF where one exists (M = 4) and None otherwise. `order`,
    `family`, `parameters`, `starts` and `claim` describe the generic path. With the legacy
    family `to_dict` returns exactly the legacy keys, so committed PAM4 output is unchanged.
    """

    p_outer: float | None
    probabilities: list[float]
    lambda_value: float | None
    objective: float
    metric: str
    block_length: int
    source: str
    channel: ChannelEstimate
    candidates: list[dict[str, Any]]
    order: int = 4
    family: str = LEGACY_FAMILY
    parameters: dict[str, Any] = field(default_factory=dict)
    starts: list[dict[str, Any]] = field(default_factory=list)
    claim: str = ""

    def to_dict(self) -> dict[str, object]:
        full = asdict(self)
        if self.family == LEGACY_FAMILY:
            return {key: full[key] for key in _LEGACY_SELECTION_KEYS}
        return full


def select_distribution(
    training_indices: NDArray[np.integer],
    training_received: NDArray[np.floating],
    source: str,
    metric: str = "bmd",
    block_length: int = 1024,
    grid_step: float = 0.005,
) -> Selection:
    """Maximize rate minus finite-block matcher loss over the symmetric family."""
    channel = estimate_channel(training_indices, training_received)
    candidates = []
    for p_outer in np.arange(0.05, 0.4951, grid_step):
        p_outer = round(float(p_outer), 6)
        probabilities = symmetric_pam4(p_outer)
        rates = gaussian_rates(probabilities, channel.means, channel.sigmas)
        loss = ConstantCompositionMatcher.from_probabilities(probabilities, block_length).rate_loss
        rate = rates.bmd if metric == "bmd" else rates.smd
        candidates.append(
            {
                "p_outer": p_outer,
                "lambda": lambda_of_symmetric_pam4(p_outer),
                "entropy": rates.entropy,
                "rate": rate,
                "matcher_loss": loss,
                "objective": rate - loss,
            }
        )
    best = max(candidates, key=lambda c: c["objective"])
    return Selection(
        p_outer=best["p_outer"],
        probabilities=symmetric_pam4(best["p_outer"]).tolist(),
        lambda_value=best["lambda"],
        objective=best["objective"],
        metric=metric,
        block_length=block_length,
        source=source,
        channel=channel,
        candidates=candidates,
    )


def design_point_selection(
    design_rate: float, metric: str, samples: int, seed: int, block_length: int, grid_step: float
) -> tuple[float, Selection]:
    """Select at the PSNR where uniform PAM4 reaches the declared design rate."""
    psnr_db = psnr_for_rate(UNIFORM, design_rate, metric)
    indices, received = simulate_training_capture(psnr_db, samples, seed)
    selection = select_distribution(
        indices,
        received,
        source=f"simulated AWGN training, peak-limited, PSNR {psnr_db:.3f} dB; not measured",
        metric=metric,
        block_length=block_length,
        grid_step=grid_step,
    )
    return psnr_db, selection


# ---------------------------------------------------------------------------------------
# Acquisitions and leakage guard (generic path)
# ---------------------------------------------------------------------------------------

_SHA256 = re.compile(r"[0-9a-f]{64}")
_SPLITS = ("training", "test")


@dataclass(frozen=True)
class AcquisitionId:
    """Identity of one acquisition: where it came from, its name, its split and its content.

    `content_sha256` is the SHA-256 of the acquisition's samples (see `content_digest`), so
    the same acquisition under two names is recognised. `uxr_ingest` keeps its registry on
    capture ids and on file and sample digests in the same way.
    """

    source: str
    id: str
    split: str
    content_sha256: str

    def __post_init__(self) -> None:
        if not self.id or not self.source:
            raise ValueError("An acquisition needs a non-empty source and id")
        if self.split not in _SPLITS:
            raise ValueError(f"split must be one of {_SPLITS}, got {self.split!r}")
        if not _SHA256.fullmatch(self.content_sha256):
            raise ValueError("content_sha256 must be 64 lowercase hexadecimal characters")


def content_digest(indices: NDArray[np.integer], received: NDArray[np.floating]) -> str:
    """SHA-256 over the int64 symbol indices and the float64 received samples."""
    digest = hashlib.sha256()
    digest.update(np.ascontiguousarray(indices, dtype="<i8").tobytes())
    digest.update(np.ascontiguousarray(received, dtype="<f8").tobytes())
    return digest.hexdigest()


@dataclass(frozen=True, eq=False)
class Acquisition:
    """One training acquisition: symbols sent, samples received, identity.

    `label` says what independence the acquisition has. Simulated ones are
    "noise-realisation, single payload": the payload is shared, only the noise differs.
    """

    id: AcquisitionId
    indices: NDArray[np.int64]
    received: NDArray[np.float64]
    label: str = ""


def verify_acquisition(acquisition: Acquisition) -> AcquisitionId:
    """Return the acquisition's id after recomputing the digest of its samples.

    Raises DataLeakageError if `content_digest(indices, received)` differs from the declared
    `content_sha256`. A truncated or re-exported copy has a different digest under its own
    (honest) declaration and is not detectable here.
    """
    actual = content_digest(acquisition.indices, acquisition.received)
    if actual != acquisition.id.content_sha256:
        raise DataLeakageError(
            f"Acquisition {acquisition.id.id!r}: declared content_sha256 "
            f"{acquisition.id.content_sha256[:12]}... does not match its samples ({actual[:12]}...)"
        )
    return acquisition.id


def _identity(item: AcquisitionId | Acquisition) -> AcquisitionId:
    return verify_acquisition(item) if isinstance(item, Acquisition) else item


def _assert_unique(ids: Sequence[AcquisitionId], name: str) -> None:
    """One acquisition must not be listed twice, under one id or under several."""
    seen_id: dict[str, AcquisitionId] = {}
    seen_hash: dict[str, AcquisitionId] = {}
    for item in ids:
        if item.id in seen_id:
            raise DataLeakageError(f"Acquisition id {item.id!r} appears twice in the {name} set")
        other = seen_hash.get(item.content_sha256)
        if other is not None:
            raise DataLeakageError(
                f"{name} acquisitions {other.id!r} and {item.id!r} have identical content: "
                "one acquisition would be counted as several"
            )
        seen_id[item.id] = item
        seen_hash[item.content_sha256] = item


def assert_independent(
    train: Iterable[AcquisitionId | Acquisition], test: Iterable[AcquisitionId | Acquisition]
) -> None:
    """Raise DataLeakageError unless the training and test acquisitions are independent.

    Items may be `AcquisitionId` (declared hash trusted) or `Acquisition`; for an `Acquisition`
    the digest is recomputed from its samples and a mismatch with the declared
    `content_sha256` raises. Checked: the split labels are training and test respectively; no
    acquisition is listed twice within a set (by id, or by content under different ids); no id
    is in both sets (the id alone, whatever the source, as in the capture registry of
    `uxr_ingest`); and no content hash is in both sets even under distinct ids. Identical
    hashes mean identical samples. Not detectable: an `AcquisitionId` whose declared hash does
    not describe its samples (pass the `Acquisition` to have it verified), and a truncated,
    re-exported or re-acquired copy, which has different bytes. `assert_disjoint` is the legacy
    id-only check.
    """
    training = [_identity(item) for item in train]
    held_out = [_identity(item) for item in test]
    for item in training:
        if item.split != "training":
            raise DataLeakageError(f"{item.id!r} is labelled {item.split!r}, not training")
    for item in held_out:
        if item.split != "test":
            raise DataLeakageError(f"{item.id!r} is labelled {item.split!r}, not test")
    _assert_unique(training, "training")
    _assert_unique(held_out, "test")
    shared_ids = {a.id for a in training} & {a.id for a in held_out}
    if shared_ids:
        raise DataLeakageError(
            f"Acquisition ids used for both tuning and test: {sorted(shared_ids)}"
        )
    hashes = {a.content_sha256: a.id for a in training}
    clashes = [(hashes[a.content_sha256], a.id) for a in held_out if a.content_sha256 in hashes]
    if clashes:
        raise DataLeakageError(
            "Identical content under different ids in training and test "
            f"(training id, test id): {sorted(clashes)}"
        )


def simulate_acquisitions(
    psnr_db: float, order: int, samples: int, seed: int, n_training: int, n_test: int
) -> tuple[list[Acquisition], list[Acquisition]]:
    """Return simulated training and test acquisitions: noise realisations of one payload.

    The payload (uniform symbol indices) is drawn once from stream key 1; the noise of every
    acquisition comes from its own child of `SeedSequence([seed, 2]).spawn(...)`, so the
    streams do not overlap. Intervals over these acquisitions describe noise only.
    """
    if order not in SUPPORTED_ORDERS:
        raise ValueError(f"PAM order must be one of {SUPPORTED_ORDERS}, got {order}")
    if n_training < 1 or n_test < 0 or samples < 2 * order:
        raise ValueError("Need at least one training acquisition and 2 samples per level")
    payload = np.random.default_rng(np.random.SeedSequence([seed, STREAM_SIM_PAYLOAD]))
    indices = payload.integers(0, order, samples)
    children = np.random.SeedSequence([seed, STREAM_SIM_NOISE]).spawn(n_training + n_test)
    sigma = 2.0 * noise_sigma_from_psnr_db(psnr_db, order)
    clean = pam_levels(order)[indices]
    source = f"simulated AWGN, peak-limited, PSNR {psnr_db:.3f} dB, PAM{order}; not measured"
    out: list[Acquisition] = []
    for k, child in enumerate(children):
        split = "training" if k < n_training else "test"
        received = clean + np.random.default_rng(child).normal(0.0, sigma, samples)
        name = f"sim-pam{order}-s{seed}-{split}-{k if split == 'training' else k - n_training}"
        ident = AcquisitionId(source, name, split, content_digest(indices, received))
        out.append(Acquisition(ident, indices.copy(), received, SIMULATION_LABEL))
    return out[:n_training], out[n_training:]


# ---------------------------------------------------------------------------------------
# Generic symmetric optimiser
# ---------------------------------------------------------------------------------------

DEFAULT_START_DEFICITS = (0.12, 0.28, 0.6)  # bits below log2 M, Maxwell-Boltzmann starts
DEFAULT_GRID_DEFICITS = (0.04, 0.08, 0.12, 0.2, 0.28, 0.4, 0.55, 0.7, 0.85, 0.95)
DEFAULT_FIXED_DEFICITS = (0.12, 0.28)
_AGREEMENT_RATE_TOL = 1e-6  # bit; concave-objective multistart agreement
_BOUND_TOL = 1e-9
_UNIFORM_TOL = 1e-12  # a PMF this close to 1/M is the direct uniform mapping
_FLOOR_TOL = 1e-5  # a pair within this of the floor 1/n counts as at the floor


def pair_bounds(order: int, block_length: int) -> tuple[float, float]:
    """Return (lower, upper) of every pair probability q_j: [1/n, 1/2], n the block length.

    The lower bound 1/n is the smallest probability whose composition count can be nonzero, so
    an optimum at the floor is representable (a floor of 1/(4n) quantised to a zero count and
    made every endpoint infeasible). Needs n >= M so that the box is not empty (n = M leaves
    only the uniform PMF). Neither PLAN nor the roadmap states this bound; it is a recorded
    decision (docs/ROADMAP_STATUS.md).
    """
    if order not in SUPPORTED_ORDERS or order < 4:
        raise ValueError(f"optimise_symmetric supports M = 4, 8, 16, got {order}")
    if block_length <= 0:
        raise ValueError(f"block_length must be positive, got {block_length}")
    if block_length < order:
        raise ValueError(
            f"block_length {block_length} is below M = {order}: the box q_j >= 1/n is empty; "
            "increase block_length"
        )
    return 1.0 / block_length, 0.5


def _quadrature_for(channel: ChannelEstimate) -> str:
    """common_grid whenever sigma is unequal (always, in practice); auto only if exactly equal."""
    sigmas = np.asarray(channel.sigmas, dtype=float)
    return "common_grid" if sigmas.max() / sigmas.min() > 1.0 + _SIGMA_EQUAL_TOL else "auto"


def _into_box(q: NDArray[np.float64], lower: float) -> NDArray[np.float64]:
    """Map a pair vector summing to 1/2 into the box; unchanged if it is already inside."""
    n = q.size
    room = 0.5 - n * lower
    excess = np.maximum(q - lower, 0.0)
    if excess.sum() <= 0:
        return np.full(n, 0.5 / n)
    return lower + excess * (room / excess.sum())


class _Problem:
    """One channel estimate, metric and block length: evaluates PMFs and counts calls."""

    def __init__(
        self, channel: ChannelEstimate, order: int, metric: str, block_length: int
    ) -> None:
        if metric not in ("smd", "bmd"):
            raise ValueError(f"metric must be smd or bmd, got {metric!r}")
        if block_length <= 0 or block_length % 2:
            raise ValueError(f"block_length must be positive and even, got {block_length}")
        if len(channel.means) != order or len(channel.sigmas) != order:
            raise ValueError(f"channel estimate must have {order} levels")
        self.channel, self.order, self.metric, self.n = channel, order, metric, block_length
        self.lower, self.upper = pair_bounds(order, block_length)
        self.quadrature = _quadrature_for(channel)
        self.calls = 0

    def is_direct_uniform(self, p: NDArray[np.float64]) -> bool:
        """True for the uniform PMF, which is sent unshaped (bits to labels, no matcher)."""
        return bool(np.max(np.abs(p - 1.0 / self.order)) <= _UNIFORM_TOL)

    def rates(self, p: NDArray[np.float64]) -> Any:
        self.calls += 1
        return gaussian_rates(
            p, self.channel.means, self.channel.sigmas, self.order, quadrature=self.quadrature
        )

    def smooth_rate(self, q: NDArray[np.float64]) -> float:
        """The continuous objective: SMD, or bmd_raw (the clip at 0 would make a flat region)."""
        # Finite differences step off the plane sum q = 1/2; renormalising leaves the objective
        # unchanged on the plane and its tangential gradient correct (the normal part is
        # absorbed by the equality-constraint multiplier).
        r = self.rates(symmetric_from_pairs(q * (0.5 / q.sum())))
        return float(r.smd if self.metric == "smd" else r.bmd_raw)

    def evaluate(self, p: NDArray[np.float64], name: str, kind: str) -> dict[str, Any]:
        """Exact objective rate(P) - rate_loss(quantised composition); infeasible is logged."""
        q = pairs_of(p)
        r = self.rates(p)
        rate = float(r.smd if self.metric == "smd" else r.bmd)
        record: dict[str, Any] = {
            "name": name,
            "kind": kind,
            "q": q.tolist(),
            "probabilities": p.tolist(),
            "entropy": float(r.entropy),
            "rate": rate,
            "in_bounds": bool(np.all(q >= self.lower - _BOUND_TOL) and np.all(q <= self.upper)),
        }
        if self.is_direct_uniform(p):
            # M is a power of two: bits map straight onto labels, exactly log2 M bits per
            # symbol, no composition constraint and so no matcher loss (frame.py direct_uniform)
            record.update(
                status="ok",
                reason="direct uniform mapping: no matcher",
                direct=True,
                matcher_loss=0.0,
                counts=None,
                objective=rate,
            )
            return record
        record["direct"] = False
        try:
            matcher = ConstantCompositionMatcher.from_symmetric_probabilities(p, self.n)
        except DistributionMatcherError as error:
            record.update(
                status="infeasible",
                reason=f"{type(error).__name__}: {error}",
                matcher_loss=None,
                counts=None,
                objective=None,
            )
            return record
        loss = matcher.rate_loss
        record.update(
            status="ok",
            reason="",
            matcher_loss=float(loss),
            counts=list(matcher.counts),
            objective=rate - float(loss),
        )
        return record


def _starts(
    problem: _Problem, seed: int, deficits: Sequence[float], dirichlet: int
) -> list[tuple[str, NDArray[np.float64], bool]]:
    """Start points: uniform, MB +-lambda at each entropy deficit, seeded Dirichlet draws.

    Returns (name, q, mapped) where `mapped` says a Maxwell-Boltzmann PMF had to be moved
    into the bound box. Dirichlet draws use stream key 3 of `seed`.
    """
    order, n = problem.order, problem.order // 2
    out = [("uniform", np.full(n, 0.5 / n), False)]
    top = float(np.log2(order))
    for sign, label in ((1, "inner"), (-1, "outer")):
        for deficit in deficits:
            entropy = top - deficit
            q = pairs_of(mb_for_entropy(entropy, order, sign))
            mapped = bool(np.any(q < problem.lower - _BOUND_TOL))
            out.append((f"mb_{label}_H{round(100 * entropy)}", _into_box(q, problem.lower), mapped))
    rng = np.random.default_rng(np.random.SeedSequence([seed, STREAM_DIRICHLET_STARTS]))
    room = 0.5 - n * problem.lower
    for k in range(dirichlet):
        out.append((f"dirichlet_{k}", problem.lower + room * rng.dirichlet(np.ones(n)), False))
    return out


def _run_start(problem: _Problem, q0: NDArray[np.float64]) -> tuple[NDArray[np.float64], Any]:
    """SLSQP over x = 2q (sums to 1), bounds scaled alike; returns (q, scipy result)."""
    n = q0.size
    calls_before = problem.calls

    def negative_rate(x: NDArray[np.float64]) -> float:
        return -problem.smooth_rate(0.5 * x)

    result = minimize(
        negative_rate,
        2.0 * q0,
        method="SLSQP",
        bounds=[(2.0 * problem.lower, 2.0 * problem.upper)] * n,
        constraints=[
            {"type": "eq", "fun": lambda x: float(x.sum() - 1.0), "jac": lambda x: np.ones(n)}
        ],
        options={"ftol": 1e-12, "maxiter": 300, "eps": 1e-6},
    )
    result.rate_calls = problem.calls - calls_before
    q = np.clip(0.5 * result.x, problem.lower, problem.upper)
    return q * (0.5 / q.sum()), result


def optimise_symmetric(
    channel: ChannelEstimate,
    order: int,
    metric: str,
    block_length: int,
    seed: int,
    *,
    source: str = "estimated channel",
    start_deficits: Sequence[float] = DEFAULT_START_DEFICITS,
    dirichlet_starts: int = 4,
    grid_deficits: Sequence[float] = DEFAULT_GRID_DEFICITS,
    multistart_check: bool = True,
) -> Selection:
    """Choose a symmetric PMF for M = 4, 8, 16, q_j in [1/n, 1/2] (n the block length).

    Quadrature: `gaussian_rates(..., quadrature="common_grid")` whenever the estimate has
    unequal sigma, M = 4 included (otherwise "auto"). The legacy `select_distribution` is not
    changed and keeps its Gauss-Hermite kernel at M = 4.

    Procedure: SLSQP on the continuous rate from the uniform start; with `multistart_check`
    (default) also from Maxwell-Boltzmann PMFs of both signs at `start_deficits` bits below
    log2 M and `dirichlet_starts` seeded Dirichlet draws. For "smd" the continuous objective is
    concave on this set, so the continuous optimum is global for the unquantised SMD
    objective over the constrained set q_j >= 1/n, on this channel estimate, and the other
    starts are an agreement check. For "bmd"
    (optimised as the smooth bmd_raw, reported clipped) the claim is "best of N starts".
    Every start is logged: start q, final q, objective, iterations, evaluations, status.

    The deliverable objective rate(P) - rate_loss(quantize_symmetric_composition(P, n)) is a
    staircase in P, so after the continuous runs it is evaluated exactly at every start
    endpoint, at uniform and on a Maxwell-Boltzmann grid (both signs, `grid_deficits`). The
    selected PMF is the argmax of that exact objective over the logged, in-bounds, feasible
    candidates. It is the best candidate tried, not a proven optimum of the staircase. A PMF
    whose quantisation gives a zero count is logged as infeasible and never selected.
    """
    problem = _Problem(channel, order, metric, block_length)
    starts = _starts(problem, seed, start_deficits, dirichlet_starts)
    if not multistart_check:
        starts = starts[:1]
    start_log: list[dict[str, Any]] = []
    candidates: list[dict[str, Any]] = []
    finals: list[tuple[NDArray[np.float64], float]] = []
    for name, q0, mapped in starts:
        q, result = _run_start(problem, q0)
        continuous = problem.smooth_rate(q)
        finals.append((q, continuous))
        start_log.append(
            {
                "name": name,
                "start_q": q0.tolist(),
                "mapped_into_bounds": mapped,
                "final_q": q.tolist(),
                "objective_metric": "smd" if metric == "smd" else "bmd_raw",
                "objective": continuous,
                "iterations": int(result.nit),
                "rate_evaluations": int(result.rate_calls),
                "status": int(result.status),
                "message": str(result.message),
                "success": bool(result.success),
            }
        )
        candidates.append(
            problem.evaluate(symmetric_from_pairs(q), f"optimised_from:{name}", "endpoint")
        )
    candidates.append(problem.evaluate(np.full(order, 1.0 / order), "uniform", "uniform"))
    top = float(np.log2(order))
    for sign, label in ((1, "inner"), (-1, "outer")):
        for deficit in grid_deficits:
            entropy = top - deficit
            p = mb_for_entropy(entropy, order, sign)
            candidates.append(problem.evaluate(p, f"mb_{label}_H{round(100 * entropy)}", "mb_grid"))

    eligible = [c for c in candidates if c["status"] == "ok" and c["in_bounds"]]
    if not eligible:
        raise ValueError("No feasible in-bounds candidate; increase block_length")
    best = max(eligible, key=lambda c: c["objective"])

    rates = np.array([r for _, r in finals])
    best_start = int(np.argmax(rates))
    gap = float(rates.max() - rates.min())
    q_gap = float(max(np.abs(q - finals[best_start][0]).max() for q, _ in finals))
    agreement = {
        "n_starts": len(finals),
        "max_objective_gap_bit": gap,
        "max_q_gap_to_best_start": q_gap,
        "best_start": start_log[best_start]["name"],
    }
    floor_continuous = [
        i for i, v in enumerate(finals[best_start][0]) if v <= problem.lower + _FLOOR_TOL
    ]
    q_selected = np.asarray(best["q"])
    floor_selected = [i for i, v in enumerate(q_selected) if v <= problem.lower + _FLOOR_TOL]
    floor_text = (
        f"floor q_j >= 1/n = {problem.lower:.3g} active at pair(s) {floor_continuous} "
        "(inner first) of the continuous optimum"
        if floor_continuous
        else f"floor q_j >= 1/n = {problem.lower:.3g} inactive at the continuous optimum"
    )
    domain = "over the constrained set q_j >= 1/n"
    if metric == "smd" and multistart_check and gap <= _AGREEMENT_RATE_TOL:
        claim = (
            f"global for the unquantised SMD objective {domain}, on this channel estimate "
            f"({len(finals)} starts agree to {gap:.1e} bit); {floor_text}; the selected PMF "
            "maximises the quantised objective over the logged candidates only"
        )
    elif metric == "smd" and multistart_check:
        claim = (
            f"best of {len(finals)} starts {domain}: the unquantised SMD starts disagree by "
            f"{gap:.1e} bit although the objective is concave; treat as a numerical failure; "
            f"{floor_text}"
        )
    elif metric == "smd":
        claim = (
            f"one start only (uniform), unquantised SMD {domain}: concavity makes a converged "
            "local maximum global on this channel estimate, but no multistart cross-check was "
            f"run and convergence is not confirmed; {floor_text}"
        )
    else:
        claim = (
            f"best of {len(finals)} starts for the continuous rate {domain}; {floor_text}; the "
            f"selected PMF is the argmax of the exact quantised objective over {len(eligible)} "
            "feasible candidates"
        )

    q_best = q_selected
    p_outer = float(q_best[-1]) if order == 4 else None
    return Selection(
        p_outer=p_outer,
        probabilities=list(best["probabilities"]),
        lambda_value=lambda_of_symmetric_pam4(p_outer) if p_outer is not None else None,
        objective=float(best["objective"]),
        metric=metric,
        block_length=block_length,
        source=source,
        channel=channel,
        candidates=candidates,
        order=order,
        family=GENERIC_FAMILY,
        parameters={
            "pair_probabilities": q_best.tolist(),
            "pair_bounds": [problem.lower, problem.upper],
            "floor_active_pairs": floor_continuous,
            "floor_active_selected_pairs": floor_selected,
            "quadrature": problem.quadrature,
            "selected": best["name"],
            "continuous_optimum": {
                "q": finals[best_start][0].tolist(),
                "objective_metric": "smd" if metric == "smd" else "bmd_raw",
                "objective": float(rates.max()),
            },
            "agreement": agreement,
            "seed": seed,
            "stream_keys": {"dirichlet_starts": STREAM_DIRICHLET_STARTS},
            "grid_deficits_bits": list(grid_deficits),
            "start_deficits_bits": list(start_deficits),
            "rate_evaluations": problem.calls,
            "infeasible_candidates": sum(1 for c in candidates if c["status"] == "infeasible"),
        },
        starts=start_log,
        claim=claim,
    )


# ---------------------------------------------------------------------------------------
# Best-fixed baseline, declared before any test data is seen
# ---------------------------------------------------------------------------------------


class BaselineOverrideError(ValueError):
    """A reported best-fixed baseline would differ from the pinned menu."""


class ExploratoryMenu(dict[str, tuple[float, ...]]):
    """A menu built with non-pinned deficits: usable for exploration, never a reported baseline."""

    reportable = False


def fixed_menu(
    order: int,
    entropy_deficits: Sequence[float] | None = None,
    *,
    exploratory: bool = False,
) -> dict[str, tuple[float, ...]]:
    """Return the declared fixed PMFs: Uniform and Inner/Outer at entropy deficits.

    M = 8 and 16 give entropy-matched Maxwell-Boltzmann PMFs at log2 M - 0.12 and - 0.28 bit,
    on each side, named PAM{M}_Fixed_{Inner|Outer}_H{centibits} (H288/H272 at M = 8,
    H388/H372 at M = 16). PAM4 with the default deficits is the exact legacy set Uniform, PS70,
    PS80 and Outer70 (their entropies are 1.88, 1.72 bit, about the same deficits).

    The deficits are pinned (`DEFAULT_FIXED_DEFICITS`, declared in configs/mpam_profiles.yaml
    and checked by its loader). Passing different ones raises `BaselineOverrideError`, so a
    reported baseline cannot be changed by an argument; with `exploratory=True` an
    `ExploratoryMenu` is returned instead, which `best_fixed` marks non-reportable.
    """
    if order not in SUPPORTED_ORDERS or order < 4:
        raise ValueError(f"fixed_menu supports M = 4, 8, 16, got {order}")
    deficits = DEFAULT_FIXED_DEFICITS if entropy_deficits is None else tuple(entropy_deficits)
    pinned = deficits == DEFAULT_FIXED_DEFICITS
    if not pinned and not exploratory:
        raise BaselineOverrideError(
            f"entropy deficits {deficits} differ from the pinned {DEFAULT_FIXED_DEFICITS}; a "
            "reported baseline cannot be overridden (pass exploratory=True for a non-reportable "
            "menu)"
        )
    menu: dict[str, tuple[float, ...]] = {} if pinned else ExploratoryMenu()
    menu[f"PAM{order}_Uniform"] = tuple([1.0 / order] * order)
    if order == 4 and pinned:
        menu["PAM4_Fixed_PS70"] = PS70
        menu["PAM4_Fixed_PS80"] = PS80
        menu["PAM4_Fixed_Outer70"] = OUTER70
        return menu
    top = float(np.log2(order))
    for sign, label in ((1, "Inner"), (-1, "Outer")):
        for deficit in deficits:
            entropy = top - deficit
            pmf = mb_for_entropy(entropy, order, sign)
            menu[f"PAM{order}_Fixed_{label}_H{round(100 * entropy)}"] = tuple(pmf.tolist())
    return menu


def _menu_is_pinned(order: int, menu: Mapping[str, Sequence[float]] | None) -> bool:
    """True if `menu` is None or is exactly the pinned menu of this order (names and PMFs)."""
    if menu is None:
        return True
    if getattr(menu, "reportable", True) is False:
        return False
    pinned = fixed_menu(order)
    return list(menu) == list(pinned) and all(
        tuple(float(x) for x in menu[name]) == pinned[name] for name in pinned
    )


@dataclass(frozen=True)
class BestFixed:
    """The fixed PMF with the highest objective on training acquisitions.

    `selected_on` names the acquisitions used. Their content hash was recomputed; their
    split label was only read (declared), see `best_fixed`. `reportable` has no True default:
    only `best_fixed` over the pinned menu sets it, so an object built by hand is not a
    reportable baseline, and the M-PAM export refuses it.
    """

    name: str
    probabilities: list[float]
    objective: float
    metric: str
    block_length: int
    order: int
    table: list[dict[str, Any]]
    selected_on: str
    reportable: bool = False
    reportable_reason: str = "NON-REPORTABLE: not derived from the pinned menu"

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def evaluate_menu(
    channel: ChannelEstimate,
    order: int,
    metric: str,
    block_length: int,
    menu: Mapping[str, Sequence[float]] | None = None,
) -> list[dict[str, Any]]:
    """Exact objective of every menu entry on one channel estimate, infeasible ones logged.

    The uniform entry is the direct mapping and is charged no matcher loss.
    """
    problem = _Problem(channel, order, metric, block_length)
    entries = fixed_menu(order) if menu is None else menu
    return [
        problem.evaluate(np.asarray(p, dtype=float), name, "fixed") for name, p in entries.items()
    ]


def _argmax_menu(
    channel: ChannelEstimate,
    order: int,
    metric: str,
    block_length: int,
    menu: Mapping[str, Sequence[float]] | None,
    selected_on: str,
) -> BestFixed:
    table = evaluate_menu(channel, order, metric, block_length, menu)
    feasible = [row for row in table if row["status"] == "ok" and row["in_bounds"]]
    if not feasible:
        raise ValueError(
            "No feasible in-bounds entry in the fixed menu (every probability must be at "
            "least 1/block_length and the composition must quantise); increase block_length"
        )
    best = max(feasible, key=lambda row: row["objective"])
    pinned = _menu_is_pinned(order, menu)
    return BestFixed(
        name=best["name"],
        probabilities=list(best["probabilities"]),
        objective=float(best["objective"]),
        metric=metric,
        block_length=block_length,
        order=order,
        table=table,
        selected_on=selected_on,
        reportable=pinned,
        reportable_reason=(
            "the pinned menu of configs/mpam_profiles.yaml"
            if pinned
            else "NON-REPORTABLE: the menu differs from the pinned one"
        ),
    )


def _training_channel(training: Sequence[Acquisition], order: int) -> tuple[ChannelEstimate, str]:
    """Check split labels and digests of the training acquisitions; fit the channel on them."""
    if not training:
        raise ValueError("At least one training acquisition is required")
    for acquisition in training:
        ident = verify_acquisition(acquisition)
        if ident.split != "training":
            raise DataLeakageError(f"{ident.id!r} is labelled {ident.split!r}, not training")
    _assert_unique([a.id for a in training], "training")
    channel = estimate_channel(
        np.concatenate([a.indices for a in training]),
        np.concatenate([a.received for a in training]),
        order,
    )
    label = "training acquisitions (content hash recomputed, split label declared): " + ", ".join(
        a.id.id for a in training
    )
    return channel, label


def best_fixed(
    training: Sequence[Acquisition],
    order: int,
    metric: str,
    block_length: int,
    menu: Mapping[str, Sequence[float]] | None = None,
) -> BestFixed:
    """BestFixed = argmax of the objective over the declared menu, on training acquisitions.

    The input is a set of `Acquisition`s, not a bare channel: every one must carry
    split label "training" and a digest that matches its samples, else DataLeakageError. The
    channel is fitted here and `selected_on` names the acquisitions: the digest is recomputed
    from the samples, but the split label is only declared by the caller (a test capture
    relabelled "training" with its true hash passes). This does not prove the samples are not
    test-derived under an honest-looking label.

    `menu` defaults to the pinned menu. Any other menu (names or PMFs) is allowed for
    exploration but the result has `reportable=False` and a reason that says so, and must not
    be reported as the baseline. The uniform member is charged no matcher loss.
    Values computed on test data are an oracle and are reported by `oracle_not_a_baseline`.
    """
    channel, label = _training_channel(training, order)
    return _argmax_menu(channel, order, metric, block_length, menu, label)


def oracle_not_a_baseline(
    evaluation_channel: ChannelEstimate,
    order: int,
    metric: str,
    block_length: int,
    menu: Mapping[str, Sequence[float]] | None = None,
) -> dict[str, Any]:
    """Best menu entry on an evaluation (e.g. test) channel: an oracle, not a baseline.

    Choosing the fixed PMF with knowledge of the evaluation data is optimistic for the
    baseline and is not what a deployed system can do. The key says so.
    """
    chosen = _argmax_menu(
        evaluation_channel,
        order,
        metric,
        block_length,
        menu,
        "evaluation data; not a baseline",
    )
    return {
        "oracle_not_a_baseline": {
            "name": chosen.name,
            "objective": chosen.objective,
            "table": chosen.table,
            "selected_on": chosen.selected_on,
        }
    }


@dataclass(frozen=True)
class AdaptiveOutcome:
    """Adaptive selection and best-fixed baseline, both chosen on training data only."""

    selection: Selection
    best_fixed: BestFixed
    training_ids: list[AcquisitionId]
    held_out_ids: list[AcquisitionId]


def select_on_acquisitions(
    training: Sequence[Acquisition],
    held_out: Iterable[AcquisitionId],
    order: int,
    metric: str,
    block_length: int,
    seed: int,
    menu: Mapping[str, Sequence[float]] | None = None,
) -> AdaptiveOutcome:
    """Select the adaptive PMF and the best-fixed baseline from training acquisitions only.

    `held_out` carries identifiers only, so test samples cannot reach the optimiser. The digest
    of every training acquisition is recomputed from its samples and must equal the declared
    `content_sha256`; the independence check then refuses overlap by id or by content hash
    (`assert_independent`). Declared hashes of held-out identifiers are trusted, and a
    truncated or re-exported copy of a test capture is not detectable: those are documented
    limits, not guarantees.
    """
    if not training:
        raise ValueError("At least one training acquisition is required")
    held_out_ids = list(held_out)
    assert_independent(training, held_out_ids)  # recomputes the training digests
    channel, label = _training_channel(training, order)
    source = f"{len(training)} training acquisitions: " + "; ".join(
        sorted({a.id.source for a in training})
    )
    selection = optimise_symmetric(channel, order, metric, block_length, seed, source=source)
    fixed = _argmax_menu(channel, order, metric, block_length, menu, label)
    return AdaptiveOutcome(selection, fixed, [a.id for a in training], held_out_ids)
