"""Leakage guards: training and test acquisitions must be independent.

Independent reasoning: the cases are built from first principles (a hash is a function of the
bytes, so equal bytes under two names must collide; a seed spawn must give streams with no
shared draws) and every rejection has a matching acceptance, so a guard that rejects everything
cannot pass.
"""

import hashlib
import inspect

import numpy as np
import pytest

from opticps.modulation.pam import pam_levels
from opticps.optimization import adaptive
from opticps.optimization.adaptive import (
    Acquisition,
    AcquisitionId,
    DataLeakageError,
    assert_disjoint,
    assert_independent,
    best_fixed,
    content_digest,
    optimise_symmetric,
    select_on_acquisitions,
    simulate_acquisitions,
)

H = [hashlib.sha256(str(i).encode()).hexdigest() for i in range(8)]


def aid(name: str, split: str, digest: str, source: str = "lab") -> AcquisitionId:
    return AcquisitionId(source, name, split, digest)


# ------------------------------------------------------------------------ AcquisitionId


def test_acquisition_id_validates_its_fields_and_is_hashable():
    ok = aid("a", "training", H[0])
    assert {ok, aid("a", "training", H[0])} == {ok}
    for bad in (
        lambda: AcquisitionId("lab", "", "training", H[0]),
        lambda: AcquisitionId("", "a", "training", H[0]),
        lambda: AcquisitionId("lab", "a", "validation", H[0]),
        lambda: AcquisitionId("lab", "a", "training", "abc"),
        lambda: AcquisitionId("lab", "a", "training", H[0].upper()),
    ):
        with pytest.raises(ValueError):
            bad()


def test_content_digest_is_a_function_of_the_samples_only():
    idx = np.arange(8) % 4
    rx = np.linspace(-3, 3, 8)
    assert content_digest(idx, rx) == content_digest(idx.copy(), rx.copy())
    assert content_digest(idx, rx) != content_digest(idx, rx + 1e-12)
    assert content_digest(idx, rx) != content_digest(idx[::-1], rx)
    assert content_digest(idx.astype(np.int32), rx) == content_digest(idx, rx)  # dtype-normalised


# ------------------------------------------------------------------------ assert_independent


def test_independent_sets_are_accepted():
    assert_independent(
        [aid("t0", "training", H[0]), aid("t1", "training", H[1])],
        [aid("x0", "test", H[2]), aid("x1", "test", H[3], source="other")],
    )
    assert_independent([aid("t0", "training", H[0])], [])  # an empty test set leaks nothing


def test_id_overlap_is_rejected_whatever_the_split_label_or_source():
    train = [aid("run7", "training", H[0])]
    with pytest.raises(DataLeakageError, match="run7"):
        assert_independent(train, [aid("run7", "test", H[1])])
    with pytest.raises(DataLeakageError, match="run7"):
        assert_independent(train, [aid("run7", "test", H[1], source="another instrument")])


def test_content_overlap_under_distinct_ids_is_rejected():
    train = [aid("run1", "training", H[0])]
    with pytest.raises(DataLeakageError, match="Identical content") as caught:
        assert_independent(train, [aid("renamed", "test", H[0])])
    assert "run1" in str(caught.value) and "renamed" in str(caught.value)


def test_wrong_split_labels_are_rejected():
    with pytest.raises(DataLeakageError, match="not training"):
        assert_independent([aid("a", "test", H[0])], [aid("b", "test", H[1])])
    with pytest.raises(DataLeakageError, match="not test"):
        assert_independent([aid("a", "training", H[0])], [aid("b", "training", H[1])])


def test_one_acquisition_counted_twice_within_a_set_is_rejected():
    with pytest.raises(DataLeakageError, match="twice"):
        assert_independent([aid("a", "training", H[0]), aid("a", "training", H[1])], [])
    with pytest.raises(DataLeakageError, match="identical content"):
        assert_independent([aid("a", "training", H[0]), aid("b", "training", H[0])], [])
    with pytest.raises(DataLeakageError, match="identical content"):
        assert_independent(
            [aid("t", "training", H[0])], [aid("a", "test", H[1]), aid("b", "test", H[1])]
        )


def test_legacy_assert_disjoint_sees_identifiers_only():
    """Documented limit: the legacy check cannot see the same content under another name."""
    assert_disjoint(["t0"], ["x0"])
    with pytest.raises(DataLeakageError):
        assert_disjoint(["a", "b"], ["b"])
    # the same acquisition under two names passes the legacy check, and fails the new one
    assert_disjoint(["run1"], ["renamed"])
    with pytest.raises(DataLeakageError):
        assert_independent([aid("run1", "training", H[0])], [aid("renamed", "test", H[0])])
    assert "identifiers only" in inspect.getdoc(assert_disjoint)


# ------------------------------------------------------------------------ simulation


def test_simulated_acquisitions_are_independent_noise_realisations_of_one_payload():
    train, test = simulate_acquisitions(14.0, 4, 20000, 42, 3, 2)
    assert len(train) == 3 and len(test) == 2
    everyone = train + test
    assert all(a.label == "noise-realisation, single payload" for a in everyone)
    assert all(np.array_equal(a.indices, everyone[0].indices) for a in everyone)  # one payload
    assert (
        len({a.id.id for a in everyone}) == 5 and len({a.id.content_sha256 for a in everyone}) == 5
    )
    assert all(a.id.content_sha256 == content_digest(a.indices, a.received) for a in everyone)
    assert [a.id.split for a in everyone] == ["training"] * 3 + ["test"] * 2
    assert_independent([a.id for a in train], [a.id for a in test])
    # the noise realisations are uncorrelated: residual correlation ~ 1/sqrt(N)
    clean = pam_levels(4)[everyone[0].indices]
    noise = np.array([a.received - clean for a in everyone])
    corr = np.corrcoef(noise)
    assert np.abs(corr[~np.eye(5, dtype=bool)]).max() < 5 / np.sqrt(20000)
    # reproducible from the seed, different for another seed
    again, _ = simulate_acquisitions(14.0, 4, 20000, 42, 3, 2)
    assert [a.id for a in again] == [a.id for a in train]
    other, _ = simulate_acquisitions(14.0, 4, 20000, 43, 3, 2)
    assert other[0].id.content_sha256 != train[0].id.content_sha256


def test_seed_streams_do_not_collide_with_the_legacy_stream_at_the_same_seed():
    """Seed 42 is used in several places; the generic path draws from SeedSequence([42, key])."""
    legacy = np.random.default_rng(42).integers(0, 4, 5000)
    train, _ = simulate_acquisitions(14.0, 4, 5000, 42, 1, 0)
    assert not np.array_equal(train[0].indices, legacy)
    keys = {
        adaptive.STREAM_SIM_PAYLOAD,
        adaptive.STREAM_SIM_NOISE,
        adaptive.STREAM_DIRICHLET_STARTS,
    }
    assert len(keys) == 3 and 77 not in keys  # demo.py uses [seed, 77]
    draws = [
        np.random.default_rng(np.random.SeedSequence([42, k])).random(1000) for k in sorted(keys)
    ]
    for i in range(3):
        for j in range(i + 1, 3):
            assert abs(np.corrcoef(draws[i], draws[j])[0, 1]) < 0.15


def test_simulate_acquisitions_rejects_bad_arguments():
    with pytest.raises(ValueError):
        simulate_acquisitions(14.0, 3, 1000, 1, 1, 1)
    with pytest.raises(ValueError):
        simulate_acquisitions(14.0, 4, 1000, 1, 0, 1)


# ------------------------------------------------------------------------ selection path


def test_selection_refuses_overlap_by_id_and_by_hash():
    train, test = simulate_acquisitions(14.0, 4, 8000, 5, 2, 2)
    by_id = AcquisitionId(test[0].id.source, train[0].id.id, "test", test[0].id.content_sha256)
    by_hash = AcquisitionId("lab", "copy-of-train-0", "test", train[0].id.content_sha256)
    for held_out in ([by_id], [by_hash]):
        with pytest.raises(DataLeakageError):
            select_on_acquisitions(train, held_out, 4, "smd", 1024, 1)
    outcome = select_on_acquisitions(train, [a.id for a in test], 4, "smd", 1024, 1)
    assert outcome.selection.family == adaptive.GENERIC_FAMILY
    assert outcome.training_ids == [a.id for a in train]


def test_a_renamed_test_acquisition_with_a_made_up_hash_is_refused():
    """QA repro: test samples passed as 'training' under a new name and a made-up hash used to
    enter selection (the declared hash was never recomputed)."""
    train, test = simulate_acquisitions(14.0, 4, 8000, 5, 2, 1)
    te = test[0]
    disguised = Acquisition(
        AcquisitionId("lab", "renamed", "training", "a" * 64), te.indices, te.received
    )
    with pytest.raises(DataLeakageError, match="does not match its samples"):
        select_on_acquisitions([train[0], disguised], [te.id], 4, "smd", 1024, 1)
    # a hash taken over other bytes is refused the same way
    other_bytes = content_digest(te.indices, te.received + 1.0)
    wrong = Acquisition(
        AcquisitionId("lab", "renamed", "training", other_bytes), te.indices, te.received
    )
    with pytest.raises(DataLeakageError, match="does not match its samples"):
        select_on_acquisitions([train[0], wrong], [te.id], 4, "smd", 1024, 1)
    # the honest declaration of the same samples carries the test hash and is caught by overlap
    honest = Acquisition(
        AcquisitionId("lab", "renamed", "training", te.id.content_sha256), te.indices, te.received
    )
    with pytest.raises(DataLeakageError, match="Identical content"):
        select_on_acquisitions([train[0], honest], [te.id], 4, "smd", 1024, 1)
    # assert_independent verifies Acquisition items too, and trusts bare ids (documented)
    with pytest.raises(DataLeakageError, match="does not match its samples"):
        assert_independent([train[0], disguised], [te.id])
    assert_independent([train[0].id, disguised.id], [te.id])  # an id alone cannot be checked
    assert_independent(train, test)  # genuine acquisitions on both sides pass


def test_the_documented_limit_a_truncated_copy_passes_the_guard():
    """Not a guarantee: one sample fewer changes the bytes, so the copy is a different
    acquisition to the guard. The docstring says so; this test pins the limit."""
    train, test = simulate_acquisitions(14.0, 4, 8000, 5, 2, 1)
    te = test[0]
    idx, rx = te.indices[:-1], te.received[:-1]
    copy = Acquisition(AcquisitionId("lab", "trunc", "training", content_digest(idx, rx)), idx, rx)
    outcome = select_on_acquisitions([train[0], copy], [te.id], 4, "smd", 1024, 1)
    assert outcome.training_ids[1].id == "trunc"  # accepted: nothing detects the re-export
    assert "truncated" in (adaptive.__doc__ or "") and "documented limit" in (
        adaptive.__doc__ or ""
    )
    assert "can never enter" not in (adaptive.__doc__ or "")


def test_a_test_split_acquisition_cannot_be_passed_as_training():
    train, test = simulate_acquisitions(14.0, 4, 8000, 5, 2, 1)
    with pytest.raises(DataLeakageError, match="not training"):
        select_on_acquisitions([train[0], test[0]], [], 4, "smd", 1024, 1)
    with pytest.raises(ValueError, match="At least one"):
        select_on_acquisitions([], [], 4, "smd", 1024, 1)


def test_test_data_cannot_reach_the_optimiser(monkeypatch):
    """The held-out argument carries identifiers only, and selection ignores everything in it."""
    train, test = simulate_acquisitions(14.0, 4, 8000, 5, 2, 3)
    seen = []
    real = adaptive.estimate_channel

    def spy(indices, received, order=4):
        seen.append((np.array(indices), np.array(received)))
        return real(indices, received, order)

    monkeypatch.setattr(adaptive, "estimate_channel", spy)
    first = select_on_acquisitions(train, [a.id for a in test], 4, "bmd", 512, 3)
    # the optimiser saw exactly the concatenated training samples and nothing else
    assert len(seen) == 1
    assert np.array_equal(seen[0][0], np.concatenate([a.indices for a in train]))
    assert np.array_equal(seen[0][1], np.concatenate([a.received for a in train]))
    # an entirely different (but independent) held-out set changes nothing in the result
    other_ids = [AcquisitionId("lab", f"other-{i}", "test", H[i]) for i in range(4)]
    second = select_on_acquisitions(train, other_ids, 4, "bmd", 512, 3)
    assert first.selection.to_dict() == second.selection.to_dict()
    assert first.best_fixed.to_dict() == second.best_fixed.to_dict()
    # held-out samples are not even a parameter: the identifiers are the only held-out input
    params = inspect.signature(select_on_acquisitions).parameters
    assert params["held_out"].annotation.endswith("Iterable[AcquisitionId]")
    for fn in (optimise_symmetric, best_fixed):
        names = set(inspect.signature(fn).parameters)
        assert not names & {"test", "held_out", "test_indices", "test_received"}
    assert not any(isinstance(v, Acquisition) for v in vars(first.selection).values())
    assert first.selection.channel == real(
        np.concatenate([a.indices for a in train]), np.concatenate([a.received for a in train])
    )


def test_best_fixed_refuses_an_acquisition_listed_twice_or_under_two_names():
    """`_training_channel` must reject duplicates: one capture counted twice doubles its weight
    in the fitted channel."""
    from dataclasses import replace

    train, _ = simulate_acquisitions(14.0, 4, 8000, 3, 2, 0)
    with pytest.raises(DataLeakageError, match="appears twice"):
        best_fixed([train[0], train[0]], 4, "bmd", 1024)
    renamed = replace(train[0], id=replace(train[0].id, id="copy-of-0"))
    with pytest.raises(DataLeakageError, match="identical content"):
        best_fixed([train[0], renamed], 4, "bmd", 1024)
    assert best_fixed(train, 4, "bmd", 1024).name  # two distinct captures are accepted


def test_selected_on_says_declared_for_the_split_label_and_a_relabelled_test_capture_passes():
    """The digest is recomputed; the split label is only read. A test capture relabelled
    training with its true hash is accepted, so the text must not say the split was checked."""
    from dataclasses import replace

    train, test = simulate_acquisitions(14.0, 4, 8000, 3, 1, 1)
    relabelled = replace(test[0], id=replace(test[0].id, split="training"))
    chosen = best_fixed([train[0], relabelled], 4, "bmd", 1024)
    assert (
        "split label declared" in chosen.selected_on
        and "content hash recomputed" in chosen.selected_on
    )
    assert "checked" not in chosen.selected_on
