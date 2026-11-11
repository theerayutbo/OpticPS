"""Stage 3A gate E0: provenance schema, strict catalog loader, plan pin, holdout guards, importer.

Everything here is offline and synthetic. No external dataset is read or needed. Lists of field
names, statuses and metrics are written out literally in the tests, on purpose: a test that
loops over the implementation's own constant cannot notice that the constant lost an entry.
"""

import copy
import dataclasses
import hashlib
import json
import math
import os
import pickle
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
import yaml

from opticps.benchmarks import catalog, holdout, provenance
from opticps.benchmarks.catalog import load_source_config, parse_source, require_local_asset
from opticps.benchmarks.holdout import (
    HoldoutState,
    SequenceCheck,
    ValidationStage,
    Verdict,
    allowed_verdicts,
    require_frozen_criterion,
    require_reference_for_ber,
)
from opticps.benchmarks.provenance import (
    ASSET_FIELDS,
    SOURCE_FIELDS,
    AssetRecord,
    BenchmarkError,
    Checksum,
    ErrorCode,
    LicenseRecord,
    LicenseStatus,
    Md5State,
    ParameterValue,
    Permission,
    Provenance,
    SourceRecord,
    Split,
    assert_no_split_overlap,
    verify_local_asset,
)
from opticps.measurement.uxr_import import UxrImportError, read_bin, read_scope_file
from opticps.transmitter.mpam_config import ConfigError, load_mpam_config

CONFIGS = Path("configs/benchmarks")
TERIPHIC = CONFIGS / "teriphic_pd1_pam4.yaml"
RAN = CONFIGS / "ran_2025_g652d.yaml"
WIEGART = CONFIGS / "wiegart_2021_peak_pam4.yaml"
PLAN = Path("docs/benchmarks/FIT_HOLDOUT_PLAN.md")
REGISTER = Path("docs/benchmarks/SOURCE_REGISTER.md")
# Pinned for Revision 13 of the plan (2026-11-11, Gate E2 part a round after the failed re-review
# of Revision 12; Revision 12 is REVISION_12_PLAN_SHA256, frozen at 04360ec; Revision 11 is
# REVISION_11_PLAN_SHA256 at 9976d3b; Revision 10 is REVISION_10_PLAN_SHA256 at 1b496d2; Revision 9 is
# REVISION_9_PLAN_SHA256 at 1e1e90a; Revision 8 is
# REVISION_8_PLAN_SHA256 at 9778ce8; Revision 7 is
# REVISION_7_PLAN_SHA256 at 936337d; Revision 6 is
# REVISION_6_PLAN_SHA256 at 536b3ec; Revision 5, before any sample was read, is REVISION_5_PLAN_SHA256 at 57643ca; Revision 4 is
# REVISION_4_PLAN_SHA256 at d52149a, Revision 3 REVISION_3_PLAN_SHA256 at 8b84914). Revision 2 hashed to
# PREVIOUS_PLAN_SHA256 (commit 0424e9c), Revision 1 to REVISION_1_PLAN_SHA256 (commit 8f57af9) and
# the first version to ORIGINAL_PLAN_SHA256 (commit 8900748). A deliberate amendment must change
# this line, the plan_sha256 in the TERIPHIC config and add a dated section.
PROMISE = (
    "The guard catches accidents and casual re-tuning by ordinary commits. It does not stop"
    " deliberate tampering by someone who controls the repository, and it gives no date proof."
    " Only an external timestamp can."
)
PLAN_SHA256 = "73884278d316b48323685f98ab5c2dd5768aa565a308bd544195ba829161564f"  # Revision 13
REVISION_12_PLAN_SHA256 = (
    "7b02c1938823173cd94e27c29ee5ae3067cdc225b7589c873bdecfa212d8898b"  # freeze 04360ec
)
REVISION_11_PLAN_SHA256 = (
    "554fd2b624878eee7d0599d323ab8a4788e7bdf22d8cb6200fab5ea6df887d4d"  # commit 9976d3b
)
REVISION_10_PLAN_SHA256 = (
    "1bd5bbad62efbc92f8a54e67e0e08de208a1d455247a512a592e196f7a8a4f3e"  # commit 1b496d2
)
REVISION_9_PLAN_SHA256 = (
    "9e7b51adade3a3ecdc4ca855f5f919747b1aab27ca8e2f857884fb1345feef24"  # commit 1e1e90a
)
REVISION_8_PLAN_SHA256 = (
    "37487f3b59cd69ceed8344aeb605d3625322fdaaafbce850702e4f9bd96af058"  # commit 9778ce8
)
REVISION_7_PLAN_SHA256 = (
    "87e3839513df645930d026a0eef78360058881563b1cb85a3f5d1726aed4bb80"  # commit 936337d
)
REVISION_6_PLAN_SHA256 = (
    "c1c274b99557d752a612770f4a20d707247ee474bf953adff2a44e87249eb225"  # commit 536b3ec
)
REVISION_5_PLAN_SHA256 = "7b7f93dd20506d617ddc5245166c55cf44e605dbc23789a6644e2a2e16ec3185"
REVISION_4_PLAN_SHA256 = "b638aa1a6e0c65368c110817ccdbacc7ab4e317ef0e9d5013cdcb2e1b0e38bce"
REVISION_3_PLAN_SHA256 = "dd2f800050a18b4da52369e4f62c9ef15fb8043bd2efc5f947b529e7b1e81535"
PREVIOUS_PLAN_SHA256 = "45d9088cd21248d5828552bdaec0215c54c4a0334086dfbd7a4ea1003c5dec11"
REVISION_1_PLAN_SHA256 = "42a578f5c3e9d28d1fad69800416faa2330510c37007a7c56c7bc940d42d358a"
ORIGINAL_PLAN_SHA256 = "6bf4238a37d722e177f7fb0c1182afb9862f316bc22d1ac265efb26d2981254a"
CRITERION = str(holdout.CRITERION_PATH)
MD5_B2B = "d7bd6d48bc020a138f4f129bc2ba7312"
MD5_2KM = "d9e3c533394c53c3575491558ffc35b1"
MD5_10KM = "3d8774b068deaf50f37892b38953dfd6"

# Written out on purpose (see module docstring).
MEASURED_ASSET_FIELDS = (
    "sample_rate_hz", "baud_bd", "modulation_order", "wavelength_nm", "fibre_type",
    "fibre_length_km", "transmitter_type", "detector", "reference_sequence", "raw_format",
    "calibration",
)  # fmt: skip
MEASURED_SOURCE_ONLY_FIELDS = ("dispersion_ps_per_nm_km", "fec_threshold", "wavelength_band")
FREE_SOURCE_FIELDS = (
    "equalizer", "rate_definition", "ber_definition", "chirp_model_status", "constraint",
    "distribution_family", "noise_definition",
)  # fmt: skip
GOOD_VALUES = {
    "sample_rate_hz": (256e9, "Hz"),
    "baud_bd": (50e9, "Bd"),
    "modulation_order": (4, None),
    "wavelength_nm": (1271, "nm"),
    "fibre_type": ("G652.D", None),
    "fibre_length_km": (2, "km"),
    "transmitter_type": ("COTS laser", None),
    "detector": ("InP PD", None),
    "reference_sequence": ("PRBS", None),
    "raw_format": ("float32", None),
    "calibration": ("volts", None),
    "dispersion_ps_per_nm_km": (-3.99, "ps/(nm km)"),
    "fec_threshold": ("3.8e-3", None),
    "wavelength_band": ("O-band", None),
}


def raw(path: Path = TERIPHIC) -> dict:
    return yaml.safe_load(path.read_text())


def write(tmp_path: Path, document: dict, name: str = "c.yaml") -> Path:
    path = tmp_path / name
    path.write_text(yaml.safe_dump(document, sort_keys=False))
    return path


def known(value, how=Provenance.PUBLISHED_MEASUREMENT, unit=None):
    return ParameterValue(value, how, unit=unit, source_ref="test")


def good(field, how=Provenance.PUBLISHED_MEASUREMENT):
    value, unit = GOOD_VALUES[field]
    return known(value, how, unit)


def asset_parameters() -> dict:
    return {name: ParameterValue.unknown() for name in ASSET_FIELDS}


def make_asset(group="g/B2B", split=Split.CHARACTERISATION, name="a.bin", md5=None, **extra):
    checksum = extra.pop("checksum", Checksum(md5_supplied=md5))
    return AssetRecord(
        source_id="s",
        doi="10.1234/x",
        url="https://example.invalid/r",
        asset_version="v1",
        filename=name,
        checksum=checksum,
        size_bytes=extra.pop("size_bytes", 10),
        split=split,
        group=group,
        parameters=asset_parameters() | extra,
    )


def make_licence(**overrides):
    fields = {
        "scope": "data",
        "status": LicenseStatus.RECORD_LEVEL,
        "license_id": "CC-BY-4.0",
        "private_research_use": Permission.ALLOWED,
        "public_redistribution": Permission.ALLOWED_WITH_CONDITIONS,
        "derivatives": Permission.ALLOWED_WITH_CONDITIONS,
        "commercial_use": Permission.ALLOWED_WITH_CONDITIONS,
    }
    return LicenseRecord(**(fields | overrides))


def make_source(licence=None, **overrides):
    fields = {
        "source_id": "s",
        "kind": "dataset",
        "title": "t",
        "doi": "10.1234/x",
        "url": "https://example.invalid/r",
        "version": None,
        "retrieved": "2026-10-31",
        "licenses": (licence or make_licence(),),
    }
    return SourceRecord(**(fields | overrides))


def with_local_hash(asset: AssetRecord, path: Path) -> AssetRecord:
    return dataclasses.replace(
        asset, checksum=verify_local_asset(path, asset.checksum.md5_supplied)
    )


# ------------------------------------------------------------------ plan pin and revision
def test_plan_hash_is_pinned_in_test_and_config():
    digest = hashlib.sha256(PLAN.read_bytes()).hexdigest()
    assert digest == PLAN_SHA256, (
        "FIT_HOLDOUT_PLAN.md changed: amend with a dated section and a new pin"
    )
    assert load_source_config(TERIPHIC).plan_sha256 == PLAN_SHA256
    hashes = {
        PLAN_SHA256,
        REVISION_5_PLAN_SHA256,
        REVISION_4_PLAN_SHA256,
        REVISION_3_PLAN_SHA256,
        PREVIOUS_PLAN_SHA256,
        REVISION_1_PLAN_SHA256,
        ORIGINAL_PLAN_SHA256,
    }
    assert len(hashes) == 7


def test_plan_records_every_earlier_pin_and_headings():
    text = " ".join(PLAN.read_text().split())
    for earlier in (
        REVISION_12_PLAN_SHA256,
        REVISION_11_PLAN_SHA256,
        REVISION_10_PLAN_SHA256,
        REVISION_9_PLAN_SHA256,
        REVISION_8_PLAN_SHA256,
        REVISION_7_PLAN_SHA256,
        REVISION_6_PLAN_SHA256,
        REVISION_5_PLAN_SHA256,
        REVISION_4_PLAN_SHA256,
        REVISION_3_PLAN_SHA256,  # dd2f8000...: no commit message holds it (qa5, finding 4)
        PREVIOUS_PLAN_SHA256,
        REVISION_1_PLAN_SHA256,
        ORIGINAL_PLAN_SHA256,
    ):
        assert earlier in text, earlier[:8]
    assert "dd2f8000" in text
    assert "## Revision 4 (2026-10-31)" in text
    assert "## Revision 5 (2026-11-01)" in text
    assert "## Revision 6 (2026-11-01)" in text
    assert "## Revision 7 (2026-11-01)" in text
    assert "## Revision 8 (2026-11-01)" in text
    assert "## Revision 9 (2026-11-02)" in text
    assert "## Revision 10 (2026-11-02)" in text
    assert "## Revision 11 (2026-11-02)" in text
    assert "## Revision 12 (2026-11-02)" in text
    assert "## Revision 13 (2026-11-11)" in text
    revision_13 = text[text.index("## Revision 13 (2026-11-11)") :]
    for needle in (
        REVISION_12_PLAN_SHA256,
        "0 lines are removed or edited from earlier text",
        "Revision 12 was reviewed, failed and **never scored**",
        "no 2 km or 10 km sample, header or hash was read or produced",
        "the 10 km run is made if and only if the committed 2 km record's outcome is not FAIL",
        "between about 20 and 60 percent",
        "small-signal only",
        "A 10 km FAIL does not separate a grid miss from large-signal operation, chirp or a filter",
        "M1 0.02659 to 0.01814, M2 0.03456 to 0.06000, M3 0.08985 to 0.13066, M4 1.2292 to 1.2179",
        "R13 limits equal R12 to 1e-9",
        "`NO_GRID_SCENARIO_FITS` to `NO_SCENARIO_FITS`",
        "`two_km_result_sha256`",
        "`carry_forward` equals `scenario_ids` in order",
        "**The 2 km run can be executed twice**",
        "No release is made",
        'it proves neither authorship nor "no earlier than"',
        "2f10d05305182d0cd80161d20fe3cfb1f18f8f1522707efc8e9b91f1104b4ae6",
        "the **scientific content** of the three documents must not change",
        PROMISE,
        "Nothing was scored on a holdout",
    ):
        assert needle in revision_13, needle
    revision_12 = text[text.index("## Revision 12 (2026-11-02)") :]
    for needle in (
        REVISION_11_PLAN_SHA256,
        "0 lines are removed or edited from earlier text",
        "Revision 11 was reviewed, failed and **never scored**",
        "no 2 km or 10 km sample, header or hash was read or produced",
        "`expected_freeze_commit` is a required argument of `score_holdout` and the script",
        "A pin held on the same machine as the repository checks against ordinary",
        "it is not date proof",
        "The promise of R3.1 is unchanged and not widened",
        "fixed by name in code (`ROLE_BY_NAME`)",
        "**Gain-invariant map instead of one normalisation.**",
        "reported, not tested",
        "a single scenario is carried alone only if it is the only survivor or wins by a psi margin of 0.25",
        "**all survivors** are carried",
        "**INCONCLUSIVE with the claim",
        "`NO_GRID_SCENARIO_FITS`, never FAILED",
        "`VALIDATED` is never returned, at either length, whatever is declared",
        "R12.4 Power study (pre-registered",
        "D = 9 FAILs 5/5",
        "FAIL caveats, one per nuisance",
        "PASS caveats: a PASS never validates dispersion",
        "import closure of the scoring entry point, 12 files",
        "Nothing was scored on a holdout",
    ):
        assert needle in revision_12, needle
    revision_11 = text[text.index("## Revision 11 (2026-11-02)") :]
    for needle in (
        REVISION_10_PLAN_SHA256,
        "0 lines are removed or edited from earlier text",
        "was not bound to its inputs",
        "`e2_score.bind_to_freeze` reads each of these files at `frozen.commit`",
        "exactly one commit in the full history",
        "never changed, deleted or re-added",
        "The first freeze is superseded",
        "`holdout.CRITERION_PATH` is therefore changed to",
        "TERIPHIC_CRITERION_R11.yaml",
        "does not widen it",
        "must not be used",
        "No 2 km or 10 km sample, header or hash was read or produced at any point",
    ):
        assert needle in revision_11, needle
    revision_10 = text[text.index("## Revision 10 (2026-11-02)") :]
    for needle in (
        REVISION_9_PLAN_SHA256,
        "0 lines are removed or edited from earlier text",
        "R9.1 now has a caller",
        "the only code in `src` that reads a sample of a holdout",
        "`require_frozen_criterion`, with the inputs of `holdout.REQUIRED_INPUTS`",
        "the holdout's MD5 (against the register) and SHA-256",
        "The promise of R3.1 is unchanged and is not widened",
        "`ASSUMED_G652D`, never ground truth",
        "`MODEL GAP: CHIRP`",
        "Declared UNKNOWN, never tuned on a holdout",
        "BER and SER stay `REFERENCE_SEQUENCE_MISSING`",
        "is not a BER",
        "Comparator, the B2B copy",
        "`PASS, NOT DISCRIMINATING`",
        "`PASS, DISCRIMINATING`",
        "R10.4 Code identity (narrow",
        "not the Python interpreter, NumPy",
        "its `results` key is null and no result column exists",
        "E2a does not run the scorer on a holdout",
        "No sample, header, size-based decode or statistic of the 2 km or 10 km file was read",
    ):
        assert needle in revision_10, needle
    revision_9 = text[text.index("## Revision 9 (2026-11-02)") :]
    for needle in (
        REVISION_8_PLAN_SHA256,
        "0 lines are removed or edited from earlier text",
        "is an E2 obligation, not a present guard",
        "has no caller in `src` or `scripts`",
        "must call `require_frozen_criterion` before it computes any holdout statistic",
        "until E2 nothing enforces that",
        "ends the process with a bus error (SIGBUS) and no message",
        "it is not reported",
        "a link to a file inside a typed folder is gated",
        "a link to a folder inside a typed folder escapes",
        "record of one block",
    ):
        assert needle in revision_9, needle
    revision_8 = text[text.index("## Revision 8 (2026-11-01)") :]
    for needle in (
        REVISION_7_PLAN_SHA256,
        "0 lines are removed or edited from earlier text",
        "only paths typed as CLI options are gated",
        "the owner chose this narrower claim".replace("the owner", "The owner"),
        "no gate is added for them",
        "require_frozen_criterion",
        "What the block pass misses",
        "a flat run of 20,000 samples inside one block",
        "leaves 3, `non_degenerate` 4 and `finite`",
        "`UPSAMPLE_PERIOD_MIN` (1.02) and `UPSAMPLE_CONTROL_MULTIPLE` (3.0)",
        "after B2B bytes had been seen",
        "checks again after the loop",
    ):
        assert needle in revision_8, needle
    revision_7 = text[text.index("## Revision 7 (2026-11-01)") :]
    for needle in (
        REVISION_6_PLAN_SHA256,
        "0 lines are removed or edited from earlier text",
        "64-bit integer",
        "84 hypotheses",
        "changes the acceptance rule",
        "**not** outcome-neutral",
        "offsets 164 to 167",
        "`plausible_scale`",
        "every CLI route that takes a path is gated; library code is not",
        "Whole-record block pass",
        "makes no four-level claim",
        "blocks checked",
        "| largest deviation over record scale (maximum) | 2.50 | 8 |",
    ):
        assert needle in revision_7, needle
    revision_6 = text[text.index("## Revision 6 (2026-11-01)") :]
    for needle in (
        REVISION_5_PLAN_SHA256,
        "40.96 samples per symbol of the stored stream",
        "A `continuous` check was added",
        "applied to the survivor, not to every hypothesis",
        "R2.2 metric M4 needs the sample rate, and it is stated now",
        "2.048 THz for B2B",
        "Holdout route rule",
        "gate_sample_read",
    ):
        assert needle in revision_6, needle
    revision_5 = text[text.index("## Revision 5 (2026-11-01)") : text.index("## Revision 6")]
    for needle in (
        REVISION_4_PLAN_SHA256,
        "was **true**",  # R.1: the message of 8f57af9 holds the full value
        "45d9088c",  # Revision 2: the message of 0424e9c holds the prefix only
        "No commit message holds `dd2f8000...`",
        "only** of `50G_PAM4_PD1_B2B_Subassembly1.bin`",
        "Acceptance rule",
    ):
        assert needle in revision_5, needle


def test_plan_roles_match_config_splits():
    source = load_source_config(TERIPHIC)
    roles = {a.filename: a.split for a in source.assets}
    assert roles == {
        "50G_PAM4_PD1_B2B_Subassembly1.bin": Split.CHARACTERISATION,
        "50G_PAM4_PD1_2km_Subassembly1.bin": Split.VALIDATION,
        "50G_PAM4_PD1_10km_Subassembly1.bin": Split.LOCKED_TEST,
    }
    assert_no_split_overlap(source.assets)
    text = PLAN.read_text()
    for needle in (
        "2 km (first declared validation)",
        "10 km (locked test)",
        "Identifiability caveat",
    ):
        assert needle in text


def test_plan_revisions_are_visible_and_truthful():
    text = " ".join(PLAN.read_text().split())
    for heading in ("Revision 1", "Revision 2", "Revision 3"):
        assert f"## {heading} (2026-10-31)" in text
    for previous in (PREVIOUS_PLAN_SHA256, REVISION_1_PLAN_SHA256, ORIGINAL_PLAN_SHA256):
        assert previous in text  # earlier versions recorded
    assert "no sample of any TERIPHIC capture has been read, decoded, plotted or summarised" in text
    assert "the files have only been hashed" in text
    assert text.count("Revision 2") >= 10
    # the superseded clauses stay visible, struck through, and each strike carries a note
    assert "~~If they were re-tuned between lengths" in text
    assert "~~Numeric pass/fail tolerances" in text
    spans = list(re.finditer(r"~~(.+?)~~\s*(\[[^\]]*\])?", text))
    assert len(spans) >= 9
    for match in spans:
        assert match.group(2) and "Revision" in match.group(2), match.group(0)[:80]
    for struck in (
        "Every clause it supersedes is struck through in place",  # the false claim of Revision 1
        "Checksums, format and content are therefore all still unknown",
        "against the later addendum criterion",
        "by anyone",
        "M1 level spacing: the three gaps",
        "the commit date is the freeze date",
        "It returns the commit that froze it",
    ):
        assert f"~~{struck}" in text or f"~~ {struck}" in text, struck
    # the false claim is not left standing outside a strike
    unstruck = re.sub(r"~~.+?~~", "", text)
    assert "Every clause it supersedes" not in unstruck
    assert "by anyone" not in unstruck and "later addendum" not in unstruck
    assert "the commit date is the freeze date" not in unstruck
    # what really happened to section 2 is disclosed with a diff reference
    for needle in (
        "git diff 8900748 8f57af9 -- docs/benchmarks/FIT_HOLDOUT_PLAN.md",
        "rewrote** two sentences of section 2",
        "Not opened for amplitude statistics",
        "Its amplitude statistics are not computed",
    ):
        assert needle in text, needle
    # shared-sequence and lock wording (R.2, R.3), validation limit (R.5), named metrics (R.4)
    for needle in (
        "one repeating sequence may be used for all three",
        "inferred candidate",
        "pattern correlation, timing or clock recovery, sequence extraction",
        "covers **every** statistic",
        "2 km cannot by itself be VALIDATED",
        "Only the single 10 km evaluation",
        "M2 amplitude histogram distance",
        "M3 quantile error",
        "M4 spectrum shape",
        "require_frozen_criterion",
        "committed before any 2 km statistic is computed",
    ):
        assert needle in text, needle


def test_plan_revision_2_defines_the_metrics_the_schema_and_the_residual_limits():
    text = " ".join(PLAN.read_text().split())
    for needle in (
        # M1 fully defined: norm, form, pass rule
        "M1 = max over i of |g(m)_i - g(p)_i|, the L-infinity norm",
        "all four** metrics are less than or equal to their frozen limits",
        # estimators frozen
        "Hann window (periodic), segments of 4096 samples, 50 % overlap",
        "Hyndman-Fan type 7",
        "one-dimensional k-means with k = 4",
        "N = 65536",
        # schema field for the stated multiplier
        "`plan_sha256`, `limits`, `b2b_basis` and `multipliers`",
        "the limit must equal their product",
        # predictions driven by a B2B-inferred sequence, shared-sequence check
        "must not be driven by a sequence recovered from B2B",
        "shared-sequence check",
        "Only `NOT_SHARED` allows `VALIDATED`",
        # the residual, plainly
        "Git history can be rewritten locally",
        "consistency with the history present in this local repository",
        "An amended or rewritten first commit leaves no trace in the repository and is "
        "**undetectable**",
        "a backdated freeze commit passes",
        "Only a timestamp the author does not control proves when the criterion existed",
        "Pushing is an owner action",
        "according to the orchestrator's record and the Dev logs",
    ):
        assert needle in text, needle
    schema = holdout.CRITERION_KEYS - {"criterion_version"}
    assert schema == {"plan_sha256", "limits", "b2b_basis", "multipliers", "estimators"}


def test_plan_revision_3_narrows_the_promise_and_says_why():
    text = " ".join(PLAN.read_text().split())
    revision = text[text.index("## Revision 3 (2026-10-31)") :]
    assert PREVIOUS_PLAN_SHA256 in revision and PROMISE in revision
    assert PROMISE in " ".join(holdout.__doc__.split())  # the same words in both places
    for needle in (
        "three independent reviews in a row",
        "decided to narrow what the guard promises",
        "no numeric limit is set and no criterion file exists",
        "one fixed path",
        "A file at any other path is ignored",
        "That order is **not checked**",
        "caller's declarations",
        "Routes that remain, under the promise",
    ):
        assert needle in revision, needle
    # wording that claimed more is struck through with a Revision 3 note, not left standing
    unstruck = re.sub(r"~~.+?~~", "", text)
    for claim in (
        "A change needs a new revision that is committed before the criterion file is",
        "a re-commit with other limits is refused",
        "a new criterion file name",
        "require_frozen_criterion(asset, criterion_path)",
    ):
        assert claim not in unstruck, claim
    assert "[Revision 3:" in text


# ------------------------------------------------------------------ configs
@pytest.mark.parametrize("path", [TERIPHIC, RAN, WIEGART])
def test_committed_configs_load_with_licence_state(path):
    source = load_source_config(path)
    assert source.licenses and source.retrieved == "2026-10-31"


def test_teriphic_unknowns_stay_none_with_unknown_provenance():
    source = load_source_config(TERIPHIC)
    for asset in source.assets:
        for field in (
            "wavelength_nm",
            "fibre_type",
            "reference_sequence",
            "raw_format",
            "calibration",
        ):
            parameter = asset.parameters[field]
            assert parameter.value is None and parameter.provenance is Provenance.UNKNOWN
        assert asset.missing_fields == (
            "wavelength_nm", "fibre_type", "reference_sequence", "raw_format", "calibration",
        )  # fmt: skip
        assert asset.checksum.md5_state is Md5State.SUPPLIED
        assert asset.checksum.sha256_local is None and asset.checksum.md5_local is None
        assert asset.parameters["sample_rate_hz"].provenance is Provenance.INFERRED
        assert asset.sample_rate_wording == "256 Gbaud sample rate"
    lengths = {a.group.split("/")[-1]: a.parameters["fibre_length_km"].value for a in source.assets}
    assert lengths == {"B2B": 0, "2km": 2, "10km": 10}
    supplied = {a.group.split("/")[-1]: a.checksum.md5_supplied for a in source.assets}
    assert supplied == {"B2B": MD5_B2B, "2km": MD5_2KM, "10km": MD5_10KM}


def test_teriphic_transmitter_wording_follows_the_record():
    # The record says "commercially available off-the-shelf (COTS) laser source"; it does not say CW.
    for asset in load_source_config(TERIPHIC).assets:
        transmitter = asset.parameters["transmitter_type"].value
        assert "COTS" in transmitter and "laser source" in transmitter
        assert "CW" not in transmitter and "continuous" not in transmitter.lower()
    assert "CW" not in TERIPHIC.read_text().replace("CC-BY", "")


def test_teriphic_licence_is_record_level_and_grants_what_the_record_says():
    source = load_source_config(TERIPHIC)
    data = source.license_for("data")
    assert data.status is LicenseStatus.RECORD_LEVEL and data.license_id == "CC-BY-4.0"
    assert data.read_how == "verified"
    source.require_public_redistribution("data")
    source.require_derivatives("data")


def test_article_and_data_licences_are_separate():
    ran = load_source_config(RAN)
    article, data = ran.license_for("article"), ran.license_for("data")
    assert article.status is LicenseStatus.RECORD_LEVEL
    assert article.license_id == "CC-BY-NC-ND-4.0"
    assert data.status is LicenseStatus.UNVERIFIED and data.license_id is None
    assert data.status.label == "LICENSE/REUSE TERMS UNVERIFIED"
    with pytest.raises(BenchmarkError) as error:
        ran.require_public_redistribution("data")
    assert error.value.code is ErrorCode.LICENSE_UNVERIFIED
    wiegart = load_source_config(WIEGART)
    with pytest.raises(BenchmarkError, match="LICENSE_UNVERIFIED"):
        wiegart.require_public_redistribution("article")
    with pytest.raises(BenchmarkError, match="no data licence"):
        wiegart.license_for("data")


def test_ran_uses_1271_not_the_1550_default():
    ran = load_source_config(RAN).parameters
    assert ran["wavelength_nm"].value == 1271 and ran["dispersion_ps_per_nm_km"].value < 0
    assert ran["rate_definition"].value is None and ran["ber_definition"].value is None
    assert ran["chirp_model_status"].value == "MODEL_GAP"
    assert ran["fibre_type"].value == "G652.D"  # as printed in the paper


def test_licence_status_names_say_what_was_read():
    assert {m.value for m in LicenseStatus} == {"RECORD_LEVEL", "UNVERIFIED", "RESTRICTED"}
    assert not hasattr(LicenseStatus, "VERIFIED")
    for status in ("status: VERIFIED",):
        assert all(status not in p.read_text() for p in (TERIPHIC, RAN, WIEGART))
    assert {m.value for m in provenance.ReadHow} == {
        "verified", "summary", "user-supplied", "unconfirmed",
    }  # fmt: skip


def test_benchmark_configs_cannot_change_an_experiment_id():
    # A benchmark config is not a transmit config: the loader that defines experiment_ids refuses it.
    for path in (TERIPHIC, RAN, WIEGART):
        with pytest.raises(ConfigError):
            load_mpam_config(path)
    outside = [
        p
        for p in Path("src/opticps").rglob("*.py")
        if "benchmarks" not in p.parts and "configs/benchmarks" in p.read_text()
    ]
    assert outside == []  # no existing module reads the benchmark configs


def test_error_codes_are_the_eight_standard_ones():
    assert {c.value for c in ErrorCode} == {
        "SOURCE_MISSING", "LICENSE_UNVERIFIED", "FORMAT_UNKNOWN", "REFERENCE_SEQUENCE_MISSING",
        "MODEL_GAP", "NOT_COMPARABLE", "LEAKAGE_DETECTED", "UNIDENTIFIABLE_PARAMETER",
    }  # fmt: skip


def test_no_network_code_in_the_package():
    forbidden = ("socket", "urllib", "http.client", "requests", "httpx", "ftplib", "aiohttp")
    for path in Path("src/opticps/benchmarks").glob("*.py"):
        text = path.read_text()
        for name in forbidden:
            assert f"import {name}" not in text and f"from {name}" not in text, (path, name)


# ------------------------------------------------------------------ register wording
def test_register_quotes_the_record_and_states_the_corrections():
    text = " ".join(REGISTER.read_text().split())
    for needle in (
        'commercially available off-the-shelf (COTS) laser source',
        'more than 70 GHz 3-dB bandwidth',
        'a digitally applied low-pass filter of 50 GHz 3-dB cut-off',
        'actually the samples extracted from the oscilloscope',
        "0 NRZ",
        "first hashed by the orchestrator (2026-10-31)",
        "re-verified by E1a with `verify_local_asset`, 2026-11-01",
        MD5_B2B, MD5_2KM, MD5_10KM,
        "b9c5968ae4cac4ea53b6bbda62c7255b3ecfa2ff530985c1e4ae0f4e55b9e0b2",
        "22fc7bb592681ed6135b5be28a28b1f124344924316b4333508823f7674266d3",
        "053bf8c9ba8df00063f5d686508833dc18685ec320d7e373b1877947e15b118b",
        "Licence conflict",
        "CC BY-NC-ND",
        "**MD5 state `verified`**",
    ):  # fmt: skip
        assert needle in text, needle
    assert "`transmitter_type` omits CW" not in text
    assert "Revision 2; HTML page says v1" not in text  # discrepancy 1 was an artefact


LOCAL_SHA256 = {
    "50G_PAM4_PD1_B2B_Subassembly1.bin": "b9c5968ae4cac4ea53b6bbda62c7255b3ecfa2ff530985c1e4ae0f4e55b9e0b2",
    "50G_PAM4_PD1_2km_Subassembly1.bin": "22fc7bb592681ed6135b5be28a28b1f124344924316b4333508823f7674266d3",
    "50G_PAM4_PD1_10km_Subassembly1.bin": "053bf8c9ba8df00063f5d686508833dc18685ec320d7e373b1877947e15b118b",
}  # fmt: skip
LOCAL_ROOT = Path("data/external/teriphic")


@pytest.mark.skipif(
    not all((LOCAL_ROOT / n).is_file() for n in LOCAL_SHA256), reason="local TERIPHIC files absent"
)
def test_local_hashes_match_the_register():
    """Hash-only: `verify_local_asset` streams digests and returns no sample value."""
    for asset in load_source_config(TERIPHIC).assets:
        assert asset.checksum.md5_state is Md5State.SUPPLIED
        checked = verify_local_asset(LOCAL_ROOT / asset.filename, asset.checksum.md5_supplied)
        assert checked.md5_state is Md5State.VERIFIED, asset.filename
        assert checked.sha256_local == LOCAL_SHA256[asset.filename], asset.filename
        assert checked.size_local == 163_840_136


# ------------------------------------------------------------------ article text stays out
# SHA-256 (first 12 hex digits) of every window of 7 consecutive words of the sentences of the
# CC BY-NC-ND article that an earlier version of the register and the Ran config quoted. Only
# hashes are kept here, so this file does not carry the sentences either. Words are lower-cased
# runs of letters and digits.
REMOVED_ARTICLE_WINDOWS = frozenset("""
    020940db6355 022f7b4cb4c0 0547d2162f77 06f139fd5b79 0b41849dfda8 15ed1ecba5a6 1ccb0230c0a4
    1dcf5d2bd87c 284194c41a80 28924389f13e 29f4ceb46517 2a2ca551e020 2b00fd814e32 2fdf08eec4a3
    30f573f8571e 3279ef036fd3 33d951821067 3476635e3cbd 34bc24438e01 3d6afbe2fe61 3dc65ddecdfd
    42bbc2f0566d 43786314ad2f 4489ecf0fdb0 45806aa1d6f9 4699e741022d 480a91aeb12d 48e2b31ac6cf
    4b34cab3a7e4 4d8fa8e1da25 511063be6b01 521673a244b2 5299c3bf220f 54f5c9cb676f 57b78dc0b09c
    583e450a94df 58a8a10d17a2 5e618d1d93e0 5f9a9ff85c39 60970ce0c0d4 67082c82bbfe 734370e02b25
    73a60a4199ee 78f6a933d9d9 79219ed2b62f 79d7f5496818 7baa326a8b50 7c225cf3ffa2 81aba89deebd
    82b6ad0ad674 8360225d54bb 83da8aaa9aa7 8b3213a45e16 8b40ee96cb9c 8c6c9bf26212 8f6da28c4219
    8f9f5d9964f1 9154928248ba 941a46757171 94e7c70771ca 964cc9a749ee 968b9bc93eab 97ff2ba58463
    9ba3f15a3b27 9c703ac8ff36 a0adbe41e189 a10897e121c4 a151cbd11399 a25bfdfc10b4 a36591dcaa46
    a87f411444c2 a89faec604e9 af2f47c4bcfe b13ab07d4c1b b1a9793274f2 b1fa23a3a807 b385bbdce4f2
    b49aaa337053 b94f9f6c9843 bf7cc1c355aa c4726720d252 c57d529de8b0 c7d0a150c149 c89a93e4b982
    cb358f533de5 cc080d79bd0e cc182a3f973c d114272dc2ae d2013ed898a6 d7d78b0544a3 d85cc97a4d9d
    d90692a5ba9a decc87d2bb38 df50c3f10002 e19d42e4e6ec e3cb1176bb13 e5399b87fa88 e7eda9b7a056
    e8bb8c930545 e8ed240585f4 ea2b039ae990 eb833ac943e4 ecf831067ebe f325ef0a0e2e f48e0c1f2a34
    f698c96d1888 f7fda8e2b1c8 fd362d12cbdd fd8bbb9f1ee3 ffa3c60b51e7
""".split())  # fmt: skip
WORD_WINDOW = 7


def word_windows(text: str):
    words = re.findall(r"[a-z0-9]+", text.lower())
    for i in range(len(words) - WORD_WINDOW + 1):
        yield hashlib.sha256(" ".join(words[i : i + WORD_WINDOW]).encode()).hexdigest()[:12]


def committed_text_files():
    if not git_available():
        pytest.skip("git is not installed")
    listing = subprocess.run(
        ["git", "ls-files", "-z"], capture_output=True, check=True, text=True
    ).stdout
    suffixes = {".md", ".yaml", ".yml", ".py", ".txt", ".toml", ".json", ".rst", ".cff"}
    return [Path(n) for n in listing.split("\0") if n and Path(n).suffix in suffixes]


def removed_windows_in(text: str, removed: frozenset[str]) -> list[str]:
    return [h for h in word_windows(text) if h in removed]


def test_the_removal_detector_detects_a_quoted_sentence():
    # A synthetic sentence: the real removed text is not written here, this file is scanned too.
    synthetic = "the quick brown fox jumps over the lazy dog while seven owls watch quietly"
    detector = frozenset(word_windows(synthetic))
    assert len(detector) == len(synthetic.split()) - WORD_WINDOW + 1
    assert removed_windows_in(f"Quoted: {synthetic.upper()}, and more.", detector)
    assert not removed_windows_in("dispersion -3.99 ps/(nm km) at 1271 nm", detector)
    assert not removed_windows_in("the quick brown fox jumps over", detector)  # under 7 words
    assert len(REMOVED_ARTICLE_WINDOWS) >= 100


def test_no_removed_article_sentence_remains_in_committed_text():
    for path in committed_text_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        hits = removed_windows_in(text, REMOVED_ARTICLE_WINDOWS)
        assert not hits, f"{path} still carries {len(hits)} windows of a removed article sentence"
    # the carve-out of the register is true: it names what is kept
    register = " ".join(REGISTER.read_text().split())
    assert "limited to bibliographic strings" in register


# ------------------------------------------------------------------ parameter provenance
def test_value_without_provenance_raises():
    for bad in (None, "PUBLISHED_MEASUREMENT", 3):
        with pytest.raises(BenchmarkError, match="provenance"):
            ParameterValue(50e9, bad, source_ref="x")  # type: ignore[arg-type]


def test_unknown_cannot_become_a_value_or_the_reverse():
    with pytest.raises(BenchmarkError, match="UNKNOWN"):
        ParameterValue(1271, Provenance.UNKNOWN, source_ref="x")
    with pytest.raises(BenchmarkError, match="missing value"):
        ParameterValue(None, Provenance.PUBLISHED_MEASUREMENT)
    with pytest.raises(BenchmarkError, match="missing value"):
        ParameterValue(None, Provenance.SIMULATED)
    with pytest.raises(BenchmarkError, match="source_ref"):
        ParameterValue(1271, Provenance.PUBLISHED_MEASUREMENT)
    assert ParameterValue.unknown().value is None


@pytest.mark.parametrize("field", MEASURED_ASSET_FIELDS)
def test_simulated_value_is_refused_in_every_measured_asset_field(field):
    with pytest.raises(BenchmarkError) as error:
        make_asset(**{field: good(field, Provenance.SIMULATED)})
    assert error.value.code is ErrorCode.NOT_COMPARABLE


@pytest.mark.parametrize("field", MEASURED_ASSET_FIELDS[:0] + MEASURED_SOURCE_ONLY_FIELDS)
def test_simulated_value_is_refused_in_every_measured_source_field(field):
    with pytest.raises(BenchmarkError) as error:
        make_source(parameters={field: good(field, Provenance.SIMULATED)})
    assert error.value.code is ErrorCode.NOT_COMPARABLE


@pytest.mark.parametrize("field", FREE_SOURCE_FIELDS)
def test_simulated_value_may_describe_a_model_choice(field):
    source = make_source(parameters={field: known("a model choice", Provenance.SIMULATED)})
    assert source.parameters[field].provenance is Provenance.SIMULATED


def test_known_field_names_are_exactly_the_documented_ones():
    assert set(ASSET_FIELDS) == set(MEASURED_ASSET_FIELDS)
    assert set(SOURCE_FIELDS) == (
        set(MEASURED_ASSET_FIELDS) | set(MEASURED_SOURCE_ONLY_FIELDS) | set(FREE_SOURCE_FIELDS)
    )
    assert set(provenance.MEASURED_FIELDS) == (
        set(MEASURED_ASSET_FIELDS) | set(MEASURED_SOURCE_ONLY_FIELDS)
    )
    assert set(GOOD_VALUES) == set(provenance.MEASURED_FIELDS)


def test_an_inferred_value_stays_allowed_but_labelled():
    asset = make_asset(wavelength_nm=good("wavelength_nm", Provenance.INFERRED))
    assert asset.parameters["wavelength_nm"].provenance is Provenance.INFERRED


def test_asset_must_state_every_field_and_no_others():
    parameters = asset_parameters()
    del parameters["wavelength_nm"]
    with pytest.raises(BenchmarkError, match="wavelength_nm"):
        AssetRecord(
            "s", "10.1234/x", "https://e.invalid/x", "v", "a.bin", Checksum(), 1, Split.RESERVED,
            "g", parameters,
        )  # fmt: skip
    with pytest.raises(BenchmarkError, match="unknown parameter"):
        make_asset(laser_power_dbm=ParameterValue.unknown())
    with pytest.raises(BenchmarkError, match="no provenance record"):
        make_asset(wavelength_nm=1271)


# ------------------------------------------------------------------ per-field validation
BAD_VALUES = [
    ("baud_bd", float("nan"), "Bd", "finite"),
    ("baud_bd", float("inf"), "Bd", "finite"),
    ("baud_bd", -5, "Bd", "positive"),
    ("baud_bd", 0, "Bd", "positive"),
    ("baud_bd", "fast", "Bd", "number"),
    ("baud_bd", "", "Bd", "non-empty"),
    ("baud_bd", "  ", "Bd", "non-empty"),
    ("modulation_order", 3.7, None, "integer"),
    ("modulation_order", 4.0, None, "integer"),
    ("modulation_order", 3, None, "integer"),
    ("modulation_order", 32, None, "integer"),
    ("modulation_order", "4", None, "integer"),
    ("fibre_length_km", -2, "km", "negative"),
    ("fibre_length_km", float("-inf"), "km", "finite"),
    ("wavelength_nm", "null", "nm", "not a known value"),
    ("wavelength_nm", 0, "nm", "positive"),
    ("wavelength_nm", -1271, "nm", "positive"),
    ("sample_rate_hz", 256, "GHz", "inconsistent"),
    ("sample_rate_hz", 256e9, "GHz", "inconsistent"),
    ("sample_rate_hz", 256e9, "Hz and more", "inconsistent"),
    ("sample_rate_hz", 256e9, None, "inconsistent"),
    ("sample_rate_hz", 0, "Hz", "positive"),
    ("baud_bd", 50e9, "GBd", "inconsistent"),
    ("wavelength_nm", 1271, "um", "inconsistent"),
    ("fibre_length_km", 2, "m", "inconsistent"),
    ("dispersion_ps_per_nm_km", float("nan"), "ps/(nm km)", "finite"),
    ("dispersion_ps_per_nm_km", -3.99, "ps/nm", "inconsistent"),
    ("dispersion_ps_per_nm_km", "-3.99", "ps/(nm km)", "number"),
    ("fibre_type", 652, None, "text"),
    ("fibre_type", "none", None, "not a known value"),
    ("fibre_type", "Unknown", None, "not a known value"),
    ("detector", "n/a", None, "not a known value"),
    ("calibration", "volts", "V", "no unit"),
    ("calibration", "volts\x7f", None, "control character"),
    ("modulation_order", 4, "PAM", "no unit"),
    ("raw_format", "bin\x00", None, "control character"),
]


@pytest.mark.parametrize("field, value, unit, message", BAD_VALUES)
def test_known_values_are_typed_per_field_in_the_constructor(field, value, unit, message):
    with pytest.raises(BenchmarkError, match=message):
        parameter = known(value, unit=unit)  # some are already refused by ParameterValue itself
        if field in ASSET_FIELDS:
            make_asset(**{field: parameter})
        else:
            make_source(parameters={field: parameter})


@pytest.mark.parametrize("value", [True, False, [1], {"a": 1}, (1,), b"x", object()])
def test_a_value_is_a_number_or_a_string_never_a_bool_list_or_mapping(value):
    with pytest.raises(BenchmarkError, match="number, a string or null"):
        ParameterValue(value, Provenance.PUBLISHED_MEASUREMENT, source_ref="x")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_values_are_never_known(value):
    with pytest.raises(BenchmarkError, match="finite"):
        ParameterValue(value, Provenance.PUBLISHED_MEASUREMENT, source_ref="x")


@pytest.mark.parametrize("field", list(GOOD_VALUES))
def test_a_well_formed_value_is_accepted_in_each_field(field):
    parameter = good(field)
    if field in ASSET_FIELDS:
        asset = make_asset(**{field: parameter})
        assert field not in asset.missing_fields
    else:
        assert make_source(parameters={field: parameter}).parameters[field] is parameter


def test_zero_length_is_allowed_for_b2b_and_modulation_orders_are_the_listed_ones():
    assert make_asset(fibre_length_km=known(0, unit="km")).parameters["fibre_length_km"].known
    for order in (2, 4, 8, 16):
        make_asset(modulation_order=known(order))


def test_missing_fields_stays_truthful_about_unknowns():
    asset = make_asset(baud_bd=good("baud_bd"), detector=good("detector"))
    assert asset.missing_fields == (
        "sample_rate_hz", "modulation_order", "wavelength_nm", "fibre_type", "fibre_length_km",
        "transmitter_type", "reference_sequence", "raw_format", "calibration",
    )  # fmt: skip


def test_bad_values_in_a_yaml_file_are_refused_too(tmp_path):
    def edit(field, **change):
        document = raw()
        document["source"]["assets"][0]["parameters"][field].update(change)
        return write(tmp_path, document)

    for field, change, message in [
        ("baud_bd", {"value": float("nan")}, "finite"),
        ("baud_bd", {"value": float("inf")}, "finite"),
        ("baud_bd", {"value": -5}, "positive"),
        ("baud_bd", {"value": "fast"}, "number"),
        ("baud_bd", {"value": ""}, "non-empty"),
        ("modulation_order", {"value": 3.7}, "integer"),
        ("fibre_length_km", {"value": -2}, "negative"),
        ("sample_rate_hz", {"value": 256, "unit": "GHz"}, "inconsistent"),
        ("detector", {"value": "null"}, "not a known value"),
    ]:
        with pytest.raises(BenchmarkError, match=message):
            load_source_config(edit(field, **change))
    document = raw()
    document["source"]["assets"][0]["parameters"]["wavelength_nm"].update(
        value="null", provenance="PUBLISHED_MEASUREMENT", source_ref="x"
    )
    with pytest.raises(BenchmarkError, match="not a known value"):
        load_source_config(write(tmp_path, document))


def test_unit_and_text_arguments_are_checked_for_type_and_blankness():
    for name in ("unit", "as_stated", "source_ref"):
        with pytest.raises(BenchmarkError, match="non-empty string"):
            ParameterValue(None, Provenance.UNKNOWN, **{name: " "})
        with pytest.raises(BenchmarkError, match="non-empty string"):
            ParameterValue(None, Provenance.UNKNOWN, **{name: 5})
    with pytest.raises(BenchmarkError, match="ReadHow"):
        ParameterValue(None, Provenance.UNKNOWN, read_how="probably")


# ------------------------------------------------------------------ licence rules
def test_source_without_licence_state_is_refused():
    with pytest.raises(BenchmarkError) as error:
        make_source(licenses=())
    assert error.value.code is ErrorCode.LICENSE_UNVERIFIED
    document = raw()
    del document["source"]["licenses"]
    with pytest.raises(BenchmarkError, match="LICENSE_UNVERIFIED"):
        parse_source(document["source"])


def test_licence_rules():
    with pytest.raises(BenchmarkError, match="identifier"):
        make_licence(license_id=None)
    with pytest.raises(BenchmarkError, match="scope"):
        make_licence(scope="code")
    with pytest.raises(BenchmarkError, match="LicenseStatus"):
        make_licence(status="RECORD_LEVEL")
    with pytest.raises(BenchmarkError, match="Permission"):
        make_licence(derivatives="ALLOWED")
    with pytest.raises(BenchmarkError, match="non-empty"):
        make_licence(license_id="  ")
    with pytest.raises(BenchmarkError, match="ReadHow"):
        make_licence(read_how="guess")
    with pytest.raises(BenchmarkError, match="note"):
        make_licence(note=5)


@pytest.mark.parametrize(
    "field", ["private_research_use", "public_redistribution", "derivatives", "commercial_use"]
)
@pytest.mark.parametrize("grant", [Permission.ALLOWED, Permission.ALLOWED_WITH_CONDITIONS])
def test_unverified_and_restricted_terms_cannot_grant_anything(field, grant):
    unverified = {
        "private_research_use": Permission.UNVERIFIED,
        "public_redistribution": Permission.UNVERIFIED,
        "derivatives": Permission.UNVERIFIED,
        "commercial_use": Permission.UNVERIFIED,
    }
    with pytest.raises(BenchmarkError, match="unverified terms"):
        make_licence(
            status=LicenseStatus.UNVERIFIED, license_id=None, **(unverified | {field: grant})
        )
    restricted = {
        "private_research_use": Permission.NOT_ALLOWED,
        "public_redistribution": Permission.NOT_ALLOWED,
        "derivatives": Permission.NOT_ALLOWED,
        "commercial_use": Permission.NOT_ALLOWED,
    }
    if field == "private_research_use" and grant is Permission.ALLOWED_WITH_CONDITIONS:
        make_licence(
            status=LicenseStatus.RESTRICTED, license_id=None, **(restricted | {field: grant})
        )
    else:
        with pytest.raises(BenchmarkError, match="RESTRICTED"):
            make_licence(
                status=LicenseStatus.RESTRICTED, license_id=None, **(restricted | {field: grant})
            )


def test_nc_licence_is_incompatible_with_the_mit_repository():
    ran = load_source_config(RAN)
    article = ran.license_for("article")
    assert article.commercial_use is Permission.NOT_ALLOWED
    assert article.derivatives is Permission.NOT_ALLOWED
    assert article.public_redistribution is Permission.ALLOWED_WITH_CONDITIONS
    with pytest.raises(BenchmarkError) as error:
        ran.require_public_redistribution("article")
    assert error.value.code is ErrorCode.LICENSE_UNVERIFIED
    assert "commercial use" in str(error.value)
    with pytest.raises(BenchmarkError, match="commercial use"):
        ran.require_derivatives("article")


def test_redistribution_gate_checks_status_permission_commercial_and_derivatives():
    source = make_source()
    source.require_public_redistribution("data")
    source.require_derivatives("data")
    no_public = make_source(make_licence(public_redistribution=Permission.NOT_ALLOWED))
    with pytest.raises(BenchmarkError, match="public redistribution"):
        no_public.require_public_redistribution("data")
    nc = make_source(make_licence(commercial_use=Permission.NOT_ALLOWED))
    with pytest.raises(BenchmarkError, match="commercial use"):
        nc.require_public_redistribution("data")
    no_derivatives = make_source(make_licence(derivatives=Permission.NOT_ALLOWED))
    no_derivatives.require_public_redistribution("data")  # verbatim publication is fine
    with pytest.raises(BenchmarkError, match="adapted material"):
        no_derivatives.require_derivatives("data")
    # defence in depth: a record forced past its constructor with a status that grants nothing
    forced = make_source()
    object.__setattr__(forced.licenses[0], "status", LicenseStatus.UNVERIFIED)
    with pytest.raises(BenchmarkError, match="UNVERIFIED"):
        forced.require_public_redistribution("data")
    object.__setattr__(forced.licenses[0], "status", LicenseStatus.RESTRICTED)
    with pytest.raises(BenchmarkError, match="RESTRICTED"):
        forced.require_public_redistribution("data")


def test_register_states_the_nc_mit_conflict():
    text = " ".join(REGISTER.read_text().split())
    for needle in (
        "NC restricts commercial use, MIT grants it",
        "incompatible",
        "Ran article material, figures even verbatim, and any adapted content stay out of the repository",
        "independently computed results from cleared numeric data",
        "the licence text in the Europe PMC XML denies permission to share adapted material",
        "It carries no sentence of the article",
    ):  # fmt: skip
        assert needle in text, needle


# ------------------------------------------------------------------ checksums
def test_md5_supplied_is_never_verified():
    checksum = Checksum(md5_supplied=MD5_B2B)
    assert checksum.md5_state is Md5State.SUPPLIED
    assert Checksum().md5_state is Md5State.ABSENT
    with pytest.raises(BenchmarkError, match="hexadecimal"):
        Checksum(md5_supplied="XYZ")


def test_md5_verified_cannot_be_typed():
    forged = {"md5_local": MD5_B2B, "sha256_local": "0" * 64}
    for name, value in forged.items():
        with pytest.raises(TypeError):
            Checksum(md5_supplied=MD5_B2B, **{name: value})  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        Checksum(MD5_B2B, MD5_B2B, "0" * 64)  # type: ignore[call-arg]
    checksum = Checksum(md5_supplied=MD5_B2B)
    with pytest.raises(dataclasses.FrozenInstanceError):
        checksum.md5_local = MD5_B2B  # type: ignore[misc]
    with pytest.raises(ValueError):
        dataclasses.replace(checksum, md5_local=MD5_B2B)
    # a YAML file cannot supply a local hash either
    for key in ("md5_local", "sha256_local"):
        document = raw()
        document["source"]["assets"][0][key] = None
        with pytest.raises(BenchmarkError, match="unknown keys"):
            parse_source(document["source"])


def test_md5_verified_only_after_local_bytes_match(tmp_path):
    payload = b"synthetic fixture, not a capture"
    path = tmp_path / "f.bin"
    path.write_bytes(payload)
    supplied = hashlib.md5(payload).hexdigest()
    verified = verify_local_asset(path, supplied)
    assert verified.md5_state is Md5State.VERIFIED
    assert verified.md5_local == supplied
    assert verified.sha256_local == hashlib.sha256(payload).hexdigest()
    wrong = verify_local_asset(path, MD5_B2B)
    assert wrong.md5_state is Md5State.MISMATCH
    assert wrong.md5_local == supplied
    assert verify_local_asset(path).md5_state is Md5State.ABSENT
    assert path.read_bytes() == payload  # untouched
    # copying a verified checksum with another supplied MD5 cannot keep the verification
    replaced = dataclasses.replace(verified, md5_supplied=MD5_B2B)
    assert replaced.md5_state is Md5State.SUPPLIED and replaced.sha256_local is None


def test_verify_local_asset_streams_large_files(tmp_path):
    payload = bytes(range(256)) * 9000  # larger than one hashing chunk is not needed to be exact
    path = tmp_path / "big.bin"
    path.write_bytes(payload * 1)
    assert verify_local_asset(path).sha256_local == hashlib.sha256(payload).hexdigest()


def test_missing_dataset_is_source_missing(tmp_path):
    asset = load_source_config(TERIPHIC).assets[0]
    with pytest.raises(BenchmarkError) as error:
        require_local_asset(asset, tmp_path)
    assert error.value.code is ErrorCode.SOURCE_MISSING
    with pytest.raises(BenchmarkError, match="SOURCE_MISSING"):
        verify_local_asset(tmp_path / asset.filename, asset.checksum.md5_supplied)
    with pytest.raises(BenchmarkError, match="SOURCE_MISSING"):
        verify_local_asset(tmp_path)  # a directory is not a file
    with pytest.raises(BenchmarkError, match="SOURCE_MISSING"):
        load_source_config(tmp_path / "absent.yaml")
    (tmp_path / asset.filename).write_bytes(b"x")
    assert require_local_asset(asset, tmp_path).name == asset.filename


@pytest.mark.parametrize("bad", [123, b"ab", "a" * 31, "a" * 33, "A" * 32, "g" * 32, ""])
def test_checksum_text_is_typed_and_lowercase_hex(bad):
    with pytest.raises(BenchmarkError, match="hexadecimal"):
        Checksum(md5_supplied=bad)


# ------------------------------------------------------------------ leakage
def test_split_overlap_by_group_and_hash(tmp_path):
    with pytest.raises(BenchmarkError) as error:
        assert_no_split_overlap(
            [make_asset("g/B2B", Split.CHARACTERISATION), make_asset("g/B2B", Split.LOCKED_TEST)]
        )
    assert error.value.code is ErrorCode.LEAKAGE_DETECTED
    assert_no_split_overlap(
        [make_asset("g/B2B", name="a.bin"), make_asset("g/2km", Split.VALIDATION, "b.bin")]
    )


def leaking(first: AssetRecord, second: AssetRecord, message: str):
    with pytest.raises(BenchmarkError, match=message) as error:
        assert_no_split_overlap([first, second])
    assert error.value.code is ErrorCode.LEAKAGE_DETECTED


def test_same_group_in_two_roles_is_leakage_even_when_the_case_differs():
    leaking(
        make_asset("g/B2B", name="a.bin"), make_asset("G/b2b", Split.LOCKED_TEST, "b.bin"), "both"
    )


def test_same_filename_in_two_roles_or_two_groups_is_leakage():
    leaking(
        make_asset("g/B2B", name="x.bin"),
        make_asset("g/10km", Split.LOCKED_TEST, "x.bin"),
        "file name",
    )
    leaking(make_asset("g/B2B", name="x.bin"), make_asset("g/other", name="x.bin"), "file name")
    leaking(
        make_asset("g/B2B", name="X.bin"),
        make_asset("g/10km", Split.LOCKED_TEST, "x.BIN"),
        "file name",
    )


def test_same_supplied_md5_in_two_roles_or_groups_is_leakage():
    leaking(
        make_asset("g/B2B", name="a.bin", md5=MD5_B2B),
        make_asset("g/10km", Split.LOCKED_TEST, "b.bin", md5=MD5_B2B),
        "supplied MD5",
    )
    leaking(
        make_asset("g/B2B", name="a.bin", md5=MD5_B2B),
        make_asset("g/other", name="b.bin", md5=MD5_B2B),
        "supplied MD5",
    )


def test_identical_local_bytes_in_two_roles_are_leakage(tmp_path):
    first, second = tmp_path / "a.bin", tmp_path / "b.bin"
    first.write_bytes(b"same bytes")
    second.write_bytes(b"same bytes")
    a = with_local_hash(make_asset("g/B2B", name="a.bin"), first)
    b = with_local_hash(make_asset("g/10km", Split.LOCKED_TEST, "b.bin"), second)
    leaking(a, b, "local MD5|local SHA-256")
    assert a.checksum.sha256_local == b.checksum.sha256_local
    # different bytes pass
    second.write_bytes(b"other bytes")
    c = with_local_hash(make_asset("g/10km", Split.LOCKED_TEST, "b.bin"), second)
    assert_no_split_overlap([a, c])


def forced_checksum(**local) -> Checksum:
    checksum = Checksum()
    for name, value in local.items():
        object.__setattr__(checksum, name, value)
    return checksum


def test_each_local_hash_branch_alone_detects_leakage():
    for name, length in (("md5_local", 32), ("sha256_local", 64)):
        one = make_asset("g/B2B", name="a.bin", checksum=forced_checksum(**{name: "a" * length}))
        two = make_asset(
            "g/10km", Split.LOCKED_TEST, "b.bin", checksum=forced_checksum(**{name: "a" * length})
        )
        leaking(one, two, "local MD5" if name == "md5_local" else "local SHA-256")
        other = make_asset(
            "g/10km", Split.LOCKED_TEST, "b.bin", checksum=forced_checksum(**{name: "b" * length})
        )
        assert_no_split_overlap([one, other])
    # the same bytes under the same group and role is one acquisition, not leakage
    twin = make_asset("g/B2B", name="b.bin", checksum=forced_checksum(sha256_local="a" * 64))
    assert_no_split_overlap(
        [make_asset("g/B2B", name="a.bin", checksum=forced_checksum(sha256_local="a" * 64)), twin]
    )


def test_loader_applies_the_leakage_check(tmp_path):
    def move_10km_into_b2b_group(d):
        d["source"]["assets"][2]["group"] = d["source"]["assets"][0]["group"]

    with pytest.raises(BenchmarkError, match="LEAKAGE_DETECTED"):
        load_source_config(mutate(tmp_path, move_10km_into_b2b_group))

    def reuse_md5(d):
        d["source"]["assets"][2]["md5_supplied"] = d["source"]["assets"][0]["md5_supplied"]

    with pytest.raises(BenchmarkError, match="LEAKAGE_DETECTED"):
        load_source_config(mutate(tmp_path, reuse_md5))

    def swap_case(d):
        d["source"]["assets"][2]["group"] = d["source"]["assets"][0]["group"].lower()
        d["source"]["assets"][0]["group"] = d["source"]["assets"][0]["group"].upper()

    with pytest.raises(BenchmarkError, match="LEAKAGE_DETECTED"):
        load_source_config(mutate(tmp_path, swap_case))


# ------------------------------------------------------------------ schema holes
@pytest.mark.parametrize(
    "bad", ["../../etc/passwd", "a/b", "a\x00b", "..", "a b", "", " ", "-x", "a\\b"]
)
def test_source_id_allow_list(bad):
    with pytest.raises(BenchmarkError):
        make_source(source_id=bad)


@pytest.mark.parametrize(
    "bad",
    [
        "..",
        "../x.bin",
        "a/b.bin",
        "a\\b.bin",
        "a\x00.bin",
        ".hidden",
        "a..b.bin",
        "",
        "a b.bin",
        "x" * 300,
    ],
)
def test_filename_allow_list(bad):
    with pytest.raises(BenchmarkError):
        make_asset(name=bad)


@pytest.mark.parametrize("bad", ["", "..", "a//b", "a/../b", "/abs", "a\\b", "a\x00", "a/ b"])
def test_group_allow_list(bad):
    with pytest.raises(BenchmarkError):
        make_asset(group=bad)


@pytest.mark.parametrize("field, bad", [
    ("doi", "not-a-doi"), ("doi", "10.1234/a b"), ("url", "file:///etc/passwd"), ("url", "ftp://x/y"),
    ("retrieved", "31/10/2026"), ("retrieved", "2026-13-01"), ("kind", "notebook"),
    ("title", "  "), ("version", " "), ("plan_sha256", "A" * 64), ("plan_sha256", "a" * 63),
    ("plan_sha256", "g" * 64), ("plan_sha256", 5),
])  # fmt: skip
def test_source_text_fields_are_validated_in_the_constructor(field, bad):
    with pytest.raises(BenchmarkError):
        make_source(**{field: bad})


def test_plan_sha256_accepts_only_64_lowercase_hex():
    assert make_source(plan_sha256="a" * 64).plan_sha256 == "a" * 64


def test_version_must_be_the_integer_one(tmp_path):
    for version in (1.0, "1", True, 2, None):
        with pytest.raises(BenchmarkError, match="benchmark_config_version"):
            load_source_config(
                mutate(tmp_path, lambda d, v=version: d.update(benchmark_config_version=v))
            )


def test_asset_identifiers_are_validated_without_a_source():
    for bad in ("../x", "a/b", "a\x00b", ""):
        with pytest.raises(BenchmarkError):
            dataclasses.replace(make_asset(), source_id=bad)
    for field, bad in (("doi", "x"), ("url", "file:///x")):
        with pytest.raises(BenchmarkError):
            dataclasses.replace(make_asset(), **{field: bad})


def test_asset_size_and_wording_are_validated_in_the_constructor():
    for bad in (0, -1, True, 1.5, "10"):
        with pytest.raises(BenchmarkError, match="positive integer"):
            make_asset(size_bytes=bad)
    assert make_asset(size_bytes=None).size_bytes is None
    with pytest.raises(BenchmarkError, match="non-empty"):
        dataclasses.replace(make_asset(), asset_version=" ")
    with pytest.raises(BenchmarkError, match="non-empty"):
        dataclasses.replace(make_asset(), sample_rate_wording=" ")
    with pytest.raises(BenchmarkError, match="Checksum"):
        dataclasses.replace(make_asset(), checksum=MD5_B2B)
    with pytest.raises(BenchmarkError, match="Split"):
        dataclasses.replace(make_asset(), split="TEST")


def test_source_id_of_an_asset_must_match_its_source():
    asset = make_asset()
    other = dataclasses.replace(asset, source_id="other")
    assert make_source(assets=(asset,)).assets == (asset,)
    with pytest.raises(BenchmarkError, match="source_id differs"):
        make_source(assets=(other,))


def test_a_filename_cannot_be_listed_twice_in_a_source():
    a = make_asset("g/a", name="x.bin")
    b = make_asset("g/a", name="X.bin")
    with pytest.raises(BenchmarkError, match="twice|file name"):
        make_source(assets=(a, b))


def test_a_licence_scope_cannot_be_listed_twice_and_licences_must_be_records():
    with pytest.raises(BenchmarkError, match="twice"):
        make_source(licenses=(make_licence(), make_licence()))
    with pytest.raises(BenchmarkError, match="LicenseRecord"):
        make_source(licenses=("CC-BY",))
    with pytest.raises(BenchmarkError, match="AssetRecord"):
        make_source(assets=("a.bin",))


def test_records_do_not_alias_the_callers_containers():
    parameters = asset_parameters()
    asset = make_asset()
    asset = AssetRecord(
        "s", "10.1234/x", "https://e.invalid/x", "v", "a.bin", Checksum(), 1, Split.RESERVED, "g",
        parameters,
    )  # fmt: skip
    parameters["baud_bd"] = good("baud_bd")  # caller edits its dict afterwards
    assert not asset.parameters["baud_bd"].known
    with pytest.raises(TypeError):
        asset.parameters["baud_bd"] = good("baud_bd")  # type: ignore[index]
    with pytest.raises(TypeError):
        del asset.parameters["baud_bd"]  # type: ignore[attr-defined]
    with pytest.raises(dataclasses.FrozenInstanceError):
        asset.split = Split.LOCKED_TEST  # type: ignore[misc]

    licences = [make_licence()]
    assets = [make_asset()]
    source_parameters = {"wavelength_band": good("wavelength_band")}
    source = make_source(licenses=licences, assets=assets, parameters=source_parameters)  # type: ignore[arg-type]
    licences.append(make_licence(scope="article"))
    assets.append(make_asset("g/other", name="b.bin"))
    source_parameters["equalizer"] = known("FFE")
    assert isinstance(source.licenses, tuple) and len(source.licenses) == 1
    assert isinstance(source.assets, tuple) and len(source.assets) == 1
    assert set(source.parameters) == {"wavelength_band"}
    with pytest.raises(TypeError):
        source.parameters["equalizer"] = known("FFE")  # type: ignore[index]


# ------------------------------------------------------------------ holdout guards
EVERYTHING = {
    "VALIDATED", "FAILED", "INCONCLUSIVE", "UNIDENTIFIABLE_PARAMETER", "BLOCKED", "EXPLORATORY",
}  # fmt: skip
OPEN = {"FAILED", "INCONCLUSIVE", "UNIDENTIFIABLE_PARAMETER", "BLOCKED"}


def verdicts(split, **state):
    return {v.value for v in allowed_verdicts(split, **state)}


def test_verdict_names_are_the_documented_ones():
    assert {v.value for v in Verdict} == EVERYTHING
    assert {s.value for s in ValidationStage} == {"NOT_DONE", "FAILED", "NOT_FAILED"}
    assert {s.value for s in SequenceCheck} == {"NOT_RUN", "SHARED", "NOT_SHARED"}
    assert {s.value for s in HoldoutState} == {"INTACT", "BURNED"}


def test_only_the_locked_test_can_be_validated_and_only_with_every_state_established():
    good = {
        "validation_stage": ValidationStage.NOT_FAILED,
        "sequence_check": SequenceCheck.NOT_SHARED,
        "state": HoldoutState.INTACT,
    }
    assert verdicts(Split.LOCKED_TEST, **good) == OPEN | {"VALIDATED"}
    # no permissive default: nothing given, nothing granted
    assert verdicts(Split.LOCKED_TEST) == OPEN
    # each missing or bad state alone removes VALIDATED
    for name, bad in (
        ("validation_stage", None),
        ("validation_stage", ValidationStage.NOT_DONE),
        ("validation_stage", ValidationStage.FAILED),
        ("sequence_check", None),
        ("sequence_check", SequenceCheck.NOT_RUN),
        ("sequence_check", SequenceCheck.SHARED),
        ("state", None),
    ):
        assert "VALIDATED" not in verdicts(Split.LOCKED_TEST, **(good | {name: bad})), (name, bad)
    # a shared sequence is labelled EXPLORATORY (or BLOCKED) only (plan Revision 13, R2.4)
    shared = verdicts(Split.LOCKED_TEST, **(good | {"sequence_check": SequenceCheck.SHARED}))
    assert shared == {"EXPLORATORY", "BLOCKED"}
    # a burned file can only be EXPLORATORY or BLOCKED, whatever else is true
    burned = verdicts(Split.LOCKED_TEST, **(good | {"state": HoldoutState.BURNED}))
    assert burned == {"EXPLORATORY", "BLOCKED"}
    for wrong in ("NOT_FAILED", 1, True):
        with pytest.raises(BenchmarkError, match="must be a ValidationStage"):
            allowed_verdicts(Split.LOCKED_TEST, validation_stage=wrong)  # type: ignore[arg-type]
    with pytest.raises(BenchmarkError, match="must be a SequenceCheck"):
        allowed_verdicts(Split.LOCKED_TEST, sequence_check="NOT_SHARED")  # type: ignore[arg-type]
    with pytest.raises(BenchmarkError, match="must be a HoldoutState"):
        allowed_verdicts(Split.LOCKED_TEST, state="INTACT")  # type: ignore[arg-type]


def test_other_roles_never_validate_whatever_state_is_given():
    good = {
        "validation_stage": ValidationStage.NOT_FAILED,
        "sequence_check": SequenceCheck.NOT_SHARED,
        "state": HoldoutState.INTACT,
    }
    assert verdicts(Split.VALIDATION, **good) == OPEN
    assert verdicts(Split.VALIDATION) == OPEN
    # R.2: a shared sequence marks "the affected holdout" EXPLORATORY, 2 km included (R13)
    shared = verdicts(Split.VALIDATION, **good | {"sequence_check": SequenceCheck.SHARED})
    assert shared == {"EXPLORATORY", "BLOCKED"}
    assert verdicts(Split.CHARACTERISATION, **good) == {"INCONCLUSIVE", "BLOCKED"}
    assert verdicts(Split.RESERVED, **good) == {"BLOCKED"}
    assert verdicts(Split.UNASSIGNED, **good) == {"BLOCKED"}


def test_ber_needs_a_reference_stated_by_a_source():
    for asset in load_source_config(TERIPHIC).assets:
        with pytest.raises(BenchmarkError, match="no transmitted sequence is documented") as error:
            require_reference_for_ber(asset)
        assert error.value.code is ErrorCode.REFERENCE_SEQUENCE_MISSING
    for how in (Provenance.INFERRED, Provenance.DIGITIZED_FIGURE, Provenance.RAW_CAPTURE):
        recovered = make_asset(reference_sequence=known("recovered from B2B", how))
        with pytest.raises(BenchmarkError, match="inferred candidate") as error:
            require_reference_for_ber(recovered)
        assert error.value.code is ErrorCode.REFERENCE_SEQUENCE_MISSING
    stated = make_asset(reference_sequence=known("PRBS13Q"))
    assert require_reference_for_ber(stated) == "PRBS13Q"


METRIC_NAMES = (
    "M1_level_spacing", "M2_wasserstein1_amplitude", "M3_quantile_error", "M4_log_spectral_distance",
)  # fmt: skip
INPUT_FILES = {
    Split.VALIDATION: ("b2b_model", "scenario_list"),
    Split.LOCKED_TEST: (
        "frozen_parameters",
        "selected_scenario",
        "two_km_result",
        "evaluation_script",
    ),
}


def git_available() -> bool:
    return shutil.which("git") is not None


def git(root: Path, *args: str, env: dict | None = None) -> str:
    done = subprocess.run(
        ["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
         "-c", "commit.gpgsign=false", *args],
        check=True, capture_output=True, text=True, env=None if env is None else os.environ | env,
    )  # fmt: skip
    return done.stdout.strip()


def criterion_document(plan: Path, **limits) -> dict:
    values = dict.fromkeys(METRIC_NAMES, 0.1) | limits
    basis = dict.fromkeys(METRIC_NAMES, 0.05)
    multipliers = {
        m: (v / basis[m] if isinstance(v, float) and math.isfinite(v) and v > 0 else 2.0)
        for m, v in values.items()
    }
    return {
        "criterion_version": 3,
        "plan_sha256": hashlib.sha256(plan.read_bytes()).hexdigest(),
        "limits": values,
        "b2b_basis": basis,
        "multipliers": multipliers,
        "estimators": dict(holdout.ESTIMATORS),
    }


@pytest.fixture
def repo(tmp_path):
    if not git_available():
        pytest.skip("git is not installed")
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q")
    (root / "plan.md").write_text("plan text")
    for names in INPUT_FILES.values():
        for name in names:
            (root / f"{name}.txt").write_text(f"content of {name}")
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "plan")
    return root


def freeze(root: Path, document: dict, commit: bool = True, env: dict | None = None) -> Path:
    path = root / CRITERION
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(document))
    if commit:
        git(root, "add", CRITERION)
        git(root, "commit", "-q", "-m", "freeze", env=env)
    return path


def holdout_assets():
    return {a.split: a for a in load_source_config(TERIPHIC).assets}


def call(repo, split=Split.VALIDATION, **extra):
    arguments = {
        "plan_path": repo / "plan.md",
        "repo_root": repo,
        "inputs": {name: repo / f"{name}.txt" for name in INPUT_FILES[split]},
    }
    if split is Split.LOCKED_TEST:
        arguments["validation_stage"] = ValidationStage.NOT_FAILED
    return require_frozen_criterion(holdout_assets()[split], **(arguments | extra))


def refuse(repo, message, split=Split.VALIDATION, **extra):
    with pytest.raises(BenchmarkError, match=message):
        call(repo, split, **extra)


def head(repo) -> str:
    return git(repo, "rev-parse", "HEAD")


def test_holdout_without_a_frozen_criterion_is_refused(tmp_path):
    assets = holdout_assets()
    for split in (Split.VALIDATION, Split.LOCKED_TEST):
        inputs = {name: tmp_path / name for name in INPUT_FILES[split]}
        with pytest.raises(BenchmarkError, match="no frozen criterion"):
            require_frozen_criterion(
                assets[split],
                repo_root=tmp_path,
                inputs=inputs,
                validation_stage=ValidationStage.NOT_FAILED,
            )
    # the characterisation file needs none
    assert require_frozen_criterion(assets[Split.CHARACTERISATION], repo_root=tmp_path) is None
    assert holdout.HOLDOUT_SPLITS == {Split.VALIDATION, Split.LOCKED_TEST}
    assert holdout.METRICS == METRIC_NAMES
    assert holdout.CRITERION_VERSION == 3
    assert holdout.REQUIRED_INPUTS[Split.VALIDATION] == INPUT_FILES[Split.VALIDATION]
    assert holdout.REQUIRED_INPUTS[Split.LOCKED_TEST] == INPUT_FILES[Split.LOCKED_TEST]


def test_reserved_and_unassigned_roles_are_refused_not_allowed(repo):
    freeze(repo, criterion_document(repo / "plan.md"))
    for role in (Split.RESERVED, Split.UNASSIGNED):
        asset = dataclasses.replace(holdout_assets()[Split.VALIDATION], split=role)
        with pytest.raises(BenchmarkError, match="is not open"):
            require_frozen_criterion(asset, plan_path=repo / "plan.md", repo_root=repo, inputs={})


def test_a_committed_complete_criterion_is_returned_with_its_commit(repo):
    freeze(repo, criterion_document(repo / "plan.md", M1_level_spacing=0.25))
    for split in (Split.VALIDATION, Split.LOCKED_TEST):
        frozen = call(repo, split)
        assert frozen is not None
        assert frozen.commit == head(repo) == frozen.head_commit
        assert len(frozen.committed_at) >= 20 and len(frozen.authored_at) >= 20
        committed = subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:{CRITERION}"],
            capture_output=True, check=True,
        ).stdout  # fmt: skip
        assert frozen.file_sha256 == hashlib.sha256(committed).hexdigest()
        assert frozen.limits["M1_level_spacing"] == 0.25
        assert set(frozen.limits) == set(METRIC_NAMES)
        assert set(frozen.inputs) == set(INPUT_FILES[split])
        assert (
            frozen.inputs[INPUT_FILES[split][0]]
            == hashlib.sha256(f"content of {INPUT_FILES[split][0]}".encode()).hexdigest()
        )
        with pytest.raises(TypeError):
            frozen.limits["M1_level_spacing"] = 9.0
        with pytest.raises(TypeError):
            frozen.inputs["x"] = "y"
        with pytest.raises(dataclasses.FrozenInstanceError):
            frozen.commit = "0" * 40  # type: ignore[misc]


def test_a_frozen_criterion_cannot_be_constructed_replaced_copied_or_pickled(repo):
    freeze(repo, criterion_document(repo / "plan.md"))
    frozen = call(repo)
    assert frozen is not None
    fields = {f.name: getattr(frozen, f.name) for f in dataclasses.fields(frozen)}
    with pytest.raises(TypeError, match="issued by require_frozen_criterion"):
        holdout.FrozenCriterion(**fields)
    with pytest.raises(TypeError):
        holdout.FrozenCriterion("x", "y", "z", {})  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        dataclasses.replace(frozen, limits={"M1_level_spacing": 99.0})
    for forge in (copy.copy, copy.deepcopy, pickle.dumps):
        with pytest.raises(TypeError, match="cannot be copied or pickled"):
            forge(frozen)
    with pytest.raises(TypeError, match="issued by require_frozen_criterion"):
        holdout.FrozenCriterion._issue(object(), **fields)
    # the limit of what Python allows, stated: deliberate in-process code can still build one
    forged = object.__new__(holdout.FrozenCriterion)
    assert isinstance(forged, holdout.FrozenCriterion)
    assert "Python cannot make a class unforgeable" in " ".join(
        holdout.FrozenCriterion.__doc__.split()
    )


def test_an_uncommitted_or_modified_criterion_is_refused(repo):
    path = freeze(repo, criterion_document(repo / "plan.md"), commit=False)
    refuse(repo, "not committed")
    git(repo, "add", CRITERION)
    refuse(repo, "not committed")  # staged, not committed
    git(repo, "commit", "-q", "-m", "freeze")
    assert call(repo) is not None
    path.write_text(path.read_text().replace("0.1", "0.9"))
    refuse(repo, "not committed or modified")


def test_a_later_commit_that_changes_the_limits_is_refused(repo):
    # Repro 1a of the second review: edit after the freeze and plain `git commit -am`.
    freeze(repo, criterion_document(repo / "plan.md"))
    first = head(repo)
    assert call(repo).commit == first
    freeze(repo, criterion_document(repo / "plan.md", M1_level_spacing=2.0))
    assert head(repo) != first
    refuse(repo, "changed after the first commit")
    for split in (Split.VALIDATION, Split.LOCKED_TEST):
        refuse(repo, first[:12], split)  # names the freeze commit


def test_a_comment_only_later_commit_keeps_the_first_commit_as_the_freeze(repo):
    # The freeze commit is the first, not the last, and non-limit changes are not a change.
    path = freeze(repo, criterion_document(repo / "plan.md"))
    first = head(repo)
    path.write_text("# a comment\n" + path.read_text())
    git(repo, "commit", "-q", "-am", "comment")
    git(repo, "commit", "-q", "--allow-empty", "-m", "empty")
    assert head(repo) != first
    frozen = call(repo)
    assert frozen.commit == first and frozen.head_commit == head(repo)


def test_the_freeze_commit_is_the_first_that_holds_non_null_limits(repo):
    document = criterion_document(repo / "plan.md")
    freeze(repo, dict(document, limits=None))
    refuse(repo, "limits must be exactly")  # null limits are not a criterion
    placeholder = head(repo)
    freeze(repo, document)
    frozen = call(repo)
    assert frozen.commit == head(repo) != placeholder


def test_limits_removed_and_restored_are_a_change(repo):
    document = criterion_document(repo / "plan.md")
    freeze(repo, document)
    freeze(repo, dict(document, limits=None))
    freeze(repo, document)
    refuse(repo, "changed after the first commit")


def other_criterion(repo, name, document, text=None):
    path = repo / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text if text is not None else yaml.safe_dump(document))
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", f"criterion {name}")
    return path


def test_a_criterion_at_any_other_path_is_ignored_and_cannot_satisfy_the_guard(repo):
    # Finding 1 of the third review, variants 1 to 3: a re-tuned limit under a new path.
    retuned = criterion_document(repo / "plan.md", M1_level_spacing=2.0)
    flow = "{" + ", ".join(f"{k}: {v!r}" for k, v in retuned.items()) + "}"
    path = freeze(repo, criterion_document(repo / "plan.md"))
    # 1. renamed away and rewritten as one-line flow style: nothing at the fixed path
    git(repo, "mv", CRITERION, "docs/c3.yaml")
    other_criterion(repo, "docs/c3.yaml", retuned, flow)
    refuse(repo, "no frozen criterion")
    # 2. a JSON-style new file elsewhere
    other_criterion(repo, "c4.json", retuned, json.dumps(retuned))
    refuse(repo, "no frozen criterion")
    assert path.parent.exists() and not path.exists()


def test_a_re_tuned_copy_next_to_an_untouched_frozen_file_does_not_replace_it(repo):
    freeze(repo, criterion_document(repo / "plan.md"))
    first = head(repo)
    other_criterion(
        repo, "docs/benchmarks/TERIPHIC_CRITERION_v2.yaml",
        criterion_document(repo / "plan.md", M1_level_spacing=2.0),
    )  # fmt: skip
    frozen = call(repo)
    assert frozen.commit == first and frozen.limits["M1_level_spacing"] == 0.1


@pytest.mark.parametrize("old", ["draft.yaml", 'we"ird.yaml'])
def test_a_file_renamed_into_the_fixed_path_is_refused(repo, old):
    # Variant 4 and the quoted-path variant: a draft with other limits moved to the fixed path.
    draft = criterion_document(repo / "plan.md")
    other_criterion(repo, old, draft)
    (repo / CRITERION).parent.mkdir(parents=True, exist_ok=True)
    git(repo, "mv", old, CRITERION)
    (repo / CRITERION).write_text(
        yaml.safe_dump(criterion_document(repo / "plan.md", M1_level_spacing=2.0))
    )
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "move the draft")
    refuse(repo, "renamed in")


@pytest.mark.parametrize("kept", [10, 20])
def test_a_rename_in_below_the_default_similarity_is_still_refused(repo, kept):
    # The threshold is 20 %: a draft rewritten far beyond git's default 50 % is still a rename.
    filler = lambda tag, n: "".join(f"# {tag} filler line number {i}\n" for i in range(n))  # noqa: E731
    document = yaml.safe_dump(criterion_document(repo / "plan.md"))
    other_criterion(repo, "draft.yaml", None, document + filler("old", 40 - kept))
    (repo / CRITERION).parent.mkdir(parents=True, exist_ok=True)
    git(repo, "mv", "draft.yaml", CRITERION)
    retuned = yaml.safe_dump(criterion_document(repo / "plan.md", M1_level_spacing=2.0))
    (repo / CRITERION).write_text(retuned + filler("new", 40 - kept))
    commit_all(repo, "move the rewritten draft")
    shown = git(repo, "log", "-1", "--find-renames=60%", "--name-status", "--format=")
    assert not shown.startswith("R")  # below 60 %: only the 20 % threshold sees the rename
    assert git(repo, "log", "-1", "--find-renames=20%", "--name-status", "--format=").startswith(
        "R"
    )
    refuse(repo, "renamed in")


def test_the_git_wrapper_lists_a_root_commit_even_with_log_showroot_false(repo):
    git(repo, "config", "log.showRoot", "false")
    assert git(repo, "log", "-1", "--name-status", "--format=").strip() == ""  # config is live
    shown = holdout._git_ok(repo, "log", "-1", "--name-status", "--format=", head(repo))
    assert shown.startswith(b"A\t")


def test_a_signature_tells_the_string_one_from_the_number_one(repo):
    document = criterion_document(repo / "plan.md")
    freeze(repo, dict(document, limits=dict(document["limits"], M1_level_spacing="0.1")))
    freeze(repo, document)  # the same text of the number, another type
    refuse(repo, "changed after the first commit")


def test_a_criterion_first_written_at_the_fixed_path_is_the_freeze_whatever_a_draft_said(repo):
    # Named under the promise: a draft elsewhere is not a criterion, the freeze is this commit.
    other_criterion(repo, "draft.yaml", criterion_document(repo / "plan.md"))
    freeze(
        repo,
        criterion_document(repo / "plan.md", M1_level_spacing=2.0, M2_wasserstein1_amplitude=9.0),
    )
    frozen = call(repo)
    assert frozen.commit == head(repo)


def test_a_later_plan_change_is_refused_while_a_frozen_criterion_exists(repo):
    # Finding 2 of the third review: plan rewritten, plan_sha256 re-tied, limits the same.
    path = freeze(repo, criterion_document(repo / "plan.md"))
    first = head(repo)
    assert call(repo).commit == first
    (repo / "plan.md").write_text("Pass rule: three of four metrics. M1 = mean.")
    freeze(repo, criterion_document(repo / "plan.md"), commit=False)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "plan and criterion")
    refuse(repo, "changed after the first commit")
    assert path.exists()


@pytest.mark.parametrize("part", ["b2b_basis", "multipliers"])
def test_a_later_change_of_basis_or_multiplier_with_the_same_product_is_refused(repo, part):
    document = criterion_document(repo / "plan.md")
    freeze(repo, document)
    assert call(repo) is not None
    other = "multipliers" if part == "b2b_basis" else "b2b_basis"
    halved = {m: v / 2 for m, v in document[part].items()}
    doubled = {m: v * 2 for m, v in document[other].items()}
    freeze(repo, dict(document, **{part: halved, other: doubled}))
    refuse(repo, "changed after the first commit")


def test_the_signature_keeps_the_number_type_and_the_estimator_ids():
    one = holdout._signature(b"limits: {a: 1}\nplan_sha256: x\n")
    one_float = holdout._signature(b"limits: {a: 1.0}\nplan_sha256: x\n")
    assert one is not None and one != one_float  # 1 and 1.0 are a change
    assert holdout._signature(b"limits: {a: 1}\nplan_sha256: y\n") != one
    assert holdout._signature(b"limits: {a: 1}\nplan_sha256: x\nestimators: {a: e}\n") != one
    assert holdout._signature(b"limits: {a: [1]}\n") is not None  # non-mapping limits still count
    assert holdout._signature(b"limits: null\n") is None
    assert holdout._signature(b"- a\n- list\n") is None
    assert holdout._signature(b"\xff\xfe") is None


def test_a_later_commit_that_only_retypes_a_limit_is_refused(repo):
    document = criterion_document(repo / "plan.md")
    document["limits"]["M1_level_spacing"] = 1
    document["b2b_basis"]["M1_level_spacing"] = 0.5
    document["multipliers"]["M1_level_spacing"] = 2.0
    freeze(repo, document)
    assert call(repo) is not None
    document["limits"]["M1_level_spacing"] = 1.0
    freeze(repo, document)
    refuse(repo, "changed after the first commit")


def test_a_later_commit_with_non_mapping_limits_is_a_change(repo):
    document = criterion_document(repo / "plan.md")
    freeze(repo, document)
    freeze(repo, dict(document, limits=[1]))
    freeze(repo, document)  # restored: the broken version in between is still a change
    refuse(repo, "changed after the first commit")


def test_a_deleted_then_restored_criterion_is_a_change_even_with_the_same_bytes(repo):
    path = freeze(repo, criterion_document(repo / "plan.md"))
    saved = path.read_bytes()
    git(repo, "rm", "-q", CRITERION)
    git(repo, "commit", "-q", "-m", "delete")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(saved)
    git(repo, "add", CRITERION)
    git(repo, "commit", "-q", "-m", "restore")
    refuse(repo, "changed after the first commit")


def test_an_amended_first_commit_is_the_undetectable_case_and_says_so(repo):
    # Repro 1a, amend: the tool cannot see it. The test pins the behaviour so that the
    # disclosure in the plan and the docstring stays true; it is not a claim of protection.
    path = freeze(repo, criterion_document(repo / "plan.md"))
    original = head(repo)
    path.write_text(yaml.safe_dump(criterion_document(repo / "plan.md", M1_level_spacing=3.0)))
    git(repo, "commit", "-q", "--amend", "-a", "--no-edit")
    assert head(repo) != original
    frozen = call(repo)
    assert frozen.limits["M1_level_spacing"] == 3.0 and frozen.commit == head(repo)
    assert PROMISE in " ".join(holdout.__doc__.split())
    assert "rewriting history (amend, rebase, filter, a new clone)" in " ".join(
        holdout.__doc__.split()
    )
    assert PROMISE in " ".join(PLAN.read_text().split())


def test_a_backdated_commit_passes_and_its_date_is_reported_as_stated_and_forgeable(repo):
    forged = {
        "GIT_COMMITTER_DATE": "2020-01-01T00:00:00+00:00",
        "GIT_AUTHOR_DATE": "2019-06-01T12:00:00+00:00",
    }
    freeze(repo, criterion_document(repo / "plan.md"), env=forged)
    frozen = call(repo)
    assert frozen.committed_at.startswith("2020-01-01T00:00:00")  # committer date, not author
    assert frozen.authored_at.startswith("2019-06-01T12:00:00")
    assert "forged" in " ".join(holdout.__doc__.split()) or "typed" in holdout.__doc__
    assert "backdat" in holdout.FrozenCriterion.__doc__
    plan = " ".join(PLAN.read_text().split())
    assert "a backdated freeze commit passes" in plan and "not evidence" in plan


@pytest.mark.parametrize("flag", ["--assume-unchanged", "--skip-worktree"])
def test_a_hidden_working_change_is_seen_through_the_index_flags(repo, flag):
    # Repro 1b of the second review: the index flags hide the edit from `git status`.
    path = freeze(repo, criterion_document(repo / "plan.md"))
    git(repo, "update-index", flag, CRITERION)
    path.write_text(yaml.safe_dump(criterion_document(repo / "plan.md", M1_level_spacing=9.0)))
    assert git(repo, "status", "--porcelain", "--", CRITERION) == ""  # hidden from status
    refuse(repo, "modified since HEAD")
    # the returned limits are the committed ones once the working file is back to HEAD
    path.write_text(
        subprocess.run(
            ["git", "-C", str(repo), "show", f"HEAD:{CRITERION}"],
            capture_output=True,
            check=True,
            text=True,
        ).stdout  # fmt: skip
    )
    frozen = call(repo)
    assert frozen.limits["M1_level_spacing"] == 0.1


def test_an_uncommitted_plan_is_refused_even_when_the_criterion_is_retied(repo):
    freeze(repo, criterion_document(repo / "plan.md"))
    assert call(repo) is not None
    (repo / "plan.md").write_text("plan text, edited after the freeze")
    refuse(repo, "plan.md: not committed or modified since HEAD")
    # a new criterion tied to the edited plan, committed, still sees the uncommitted plan
    freeze(repo, criterion_document(repo / "plan.md"))
    refuse(repo, "changed after the first commit|plan.md")
    git(repo, "add", "plan.md")  # staged is not committed either
    refuse(repo, "plan.md: not committed or modified since HEAD")
    # plan outside the repository
    with pytest.raises(BenchmarkError, match="outside the repository"):
        call(repo, plan_path=repo.parent / "plan.md")


def test_the_inputs_the_plan_names_must_be_exact_committed_and_unchanged(repo):
    freeze(repo, criterion_document(repo / "plan.md"))
    inputs = {name: repo / f"{name}.txt" for name in INPUT_FILES[Split.VALIDATION]}
    for bad in ({}, {"b2b_model": inputs["b2b_model"]}, inputs | {"extra": repo / "plan.md"}):
        refuse(repo, "the inputs must be exactly", inputs=bad)
    with pytest.raises(BenchmarkError, match="the inputs must be exactly"):
        require_frozen_criterion(
            holdout_assets()[Split.VALIDATION],
            plan_path=repo / "plan.md",
            repo_root=repo,
        )  # inputs omitted
    inputs["b2b_model"].write_text("changed after the commit")
    refuse(repo, "b2b_model.*modified since HEAD|b2b_model.txt: not committed or modified")
    inputs["b2b_model"].write_text("content of b2b_model")
    (repo / "late.txt").write_text("never committed")
    refuse(repo, "not committed", inputs=inputs | {"scenario_list": repo / "late.txt"})
    (repo / "scenarios_gone.txt").write_text("x")
    git(repo, "add", "scenarios_gone.txt")
    refuse(repo, "not committed", inputs=inputs | {"scenario_list": repo / "scenarios_gone.txt"})
    refuse(repo, "outside the repository", inputs=inputs | {"scenario_list": repo.parent})


def test_the_ten_km_file_needs_the_two_km_stage_done(repo):
    freeze(repo, criterion_document(repo / "plan.md"))
    for stage in (None, ValidationStage.NOT_DONE):
        refuse(repo, "before the 2 km stage is done", Split.LOCKED_TEST, validation_stage=stage)
    # plan Revision 13: after a 2 km FAIL nothing is carried and the 10 km file stays unspent
    refuse(
        repo, "the 2 km stage FAILED: nothing is carried", Split.LOCKED_TEST,
        validation_stage=ValidationStage.FAILED,
    )  # fmt: skip
    with pytest.raises(holdout.StageRefused):
        call(repo, Split.LOCKED_TEST, validation_stage=ValidationStage.FAILED)
    assert call(repo, Split.LOCKED_TEST, validation_stage=ValidationStage.NOT_FAILED) is not None
    refuse(repo, "before the 2 km stage", Split.LOCKED_TEST, validation_stage="NOT_FAILED")
    # 2 km does not need a stage
    assert call(repo, Split.VALIDATION) is not None


def test_a_criterion_for_another_plan_or_with_bad_limits_is_refused(repo):
    other = criterion_document(repo / "plan.md") | {"plan_sha256": "0" * 64}
    freeze(repo, other)
    refuse(repo, "another version of the plan")


@pytest.mark.parametrize(
    "bad",
    [0, -1.0, float("nan"), float("inf"), True, "0.1", 10**400, None, [1]],
)
def test_bad_limits_are_refused_with_a_typed_error(repo, bad):
    document = criterion_document(repo / "plan.md", M1_level_spacing=bad)
    freeze(repo, document)
    refuse(repo, "finite and positive")


def test_the_limit_must_equal_the_b2b_basis_times_the_stated_multiplier(repo):
    document = criterion_document(repo / "plan.md")
    broken = dict(document, multipliers=document["multipliers"] | {"M3_quantile_error": 3.0})
    freeze(repo, broken)
    refuse(repo, "is not b2b_basis x multiplier")
    for key in ("multipliers", "b2b_basis"):
        freeze(repo, {k: v for k, v in document.items() if k != key})
        refuse(repo, "must have exactly")
    for name in ("b2b_basis", "multipliers"):
        for bad in (0, -1.0, float("nan"), True, "2"):
            wrong = dict(document, **{name: document[name] | {"M2_wasserstein1_amplitude": bad}})
            freeze(repo, wrong)
            refuse(repo, "finite and positive")
    assert holdout.CRITERION_KEYS == {
        "criterion_version", "plan_sha256", "limits", "b2b_basis", "multipliers", "estimators",
    }  # fmt: skip


def test_a_criterion_with_missing_extra_or_malformed_keys_is_refused(repo):
    base = criterion_document(repo / "plan.md")
    missing = dict(
        base, limits={k: v for k, v in base["limits"].items() if k != "M3_quantile_error"}
    )
    freeze(repo, missing)
    refuse(repo, "limits must be exactly")
    freeze(repo, dict(base, limits=base["limits"] | {"M5": 1.0}))
    refuse(repo, "limits must be exactly")
    freeze(repo, dict(base, estimators=dict(base["estimators"], M1_level_spacing="mean")))
    refuse(repo, "estimators must be exactly")
    freeze(repo, dict(base, extra=1))
    refuse(repo, "must have exactly")
    freeze(repo, dict(base, criterion_version=2))
    refuse(repo, "criterion_version")
    freeze(repo, dict(base, criterion_version=3.0))
    refuse(repo, "criterion_version")
    freeze(repo, dict(base, limits=[1]))
    refuse(repo, "limits must be exactly")
    path = repo / CRITERION
    path.write_text("- not\n- a mapping\n")
    git(repo, "add", CRITERION)
    git(repo, "commit", "-q", "-m", "bad")
    refuse(repo, "must have exactly")
    path.write_text("criterion_version: 3\ncriterion_version: 3\n")
    git(repo, "commit", "-q", "-am", "dup")
    refuse(repo, "not valid YAML")
    path.write_bytes(b"\xff\xfe\x00 not utf-8")
    git(repo, "commit", "-q", "-am", "binary")
    refuse(repo, "not valid UTF-8")


def test_a_git_ignored_criterion_is_refused(repo):
    (repo / ".gitignore").write_text("TERIPHIC_CRITERION.yaml\n")
    freeze(repo, criterion_document(repo / "plan.md"), commit=False)
    refuse(repo, "no commit contains")


def test_a_criterion_symlinked_to_a_file_outside_the_repository_is_refused(repo, tmp_path):
    outside = tmp_path / "elsewhere.yaml"
    outside.write_text(yaml.safe_dump(criterion_document(repo / "plan.md")))
    (repo / CRITERION).parent.mkdir(parents=True, exist_ok=True)
    (repo / CRITERION).symlink_to(outside)
    refuse(repo, "symbolic link")


def commit_all(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def merge_setup(repo):
    """Branch `side` forked before the freeze; main freezes 1.0; side commits 2.0 (qa4, 1)."""
    main = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    git(repo, "checkout", "-q", "-b", "side")
    freeze(repo, criterion_document(repo / "plan.md", M1_level_spacing=2.0))
    git(repo, "checkout", "-q", main)
    freeze(repo, criterion_document(repo / "plan.md"))
    return main


def test_a_merge_cannot_launder_a_second_signature_by_add_add_and_theirs(repo):
    merge_setup(repo)
    done = subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
         "merge", "-q", "side"], capture_output=True, text=True,
    )  # fmt: skip
    assert done.returncode != 0  # add/add conflict
    git(repo, "checkout", "--theirs", CRITERION)
    commit_all(repo, "merge side")
    refuse(repo, "changed after the first commit")


def test_a_merge_cannot_launder_a_second_signature_by_x_ours_and_fast_forward(repo):
    main = merge_setup(repo)
    git(repo, "checkout", "-q", "side")
    git(repo, "merge", "-q", "-X", "ours", main, "-m", "merge main", "--no-edit")
    git(repo, "checkout", "-q", main)
    git(repo, "merge", "-q", "--ff-only", "side")
    refuse(repo, "changed after the first commit")


def test_a_merge_cannot_launder_a_second_signature_by_s_ours_and_re_adding(repo):
    main = merge_setup(repo)
    git(repo, "checkout", "-q", "side")
    git(repo, "merge", "-q", "-s", "ours", main, "-m", "merge main", "--no-edit")
    git(repo, "rm", "-q", CRITERION)
    git(repo, "commit", "-q", "-m", "drop")
    freeze(repo, criterion_document(repo / "plan.md", M1_level_spacing=2.0))
    refuse(repo, "changed after the first commit")


def test_history_lists_both_sides_of_a_merge(repo):
    merge_setup(repo)
    subprocess.run(["git", "-C", str(repo), "merge", "-q", "side"], capture_output=True)
    git(repo, "checkout", "--theirs", CRITERION)
    commit_all(repo, "merge side")
    assert len(holdout._history(repo, CRITERION)) == 3  # side, freeze and the merge


def symlink_in_git(repo, name):
    """Replace `name` by a link to a copy of itself, committed (git mode 120000)."""
    target = repo / (name + ".real")
    (repo / name).rename(target)
    (repo / name).symlink_to(target.name)
    commit_all(repo, f"link {name}")
    assert git(repo, "ls-tree", "HEAD", "--", name).startswith("120000")


def test_a_symlink_at_the_criterion_path_is_refused_in_worktree_and_in_git(repo):
    # qa4, 2: a link at the fixed path moves the history read to another path.
    freeze(repo, criterion_document(repo / "plan.md"))
    assert call(repo) is not None
    git(repo, "mv", CRITERION, CRITERION + ".moved")
    (repo / CRITERION).symlink_to(Path(CRITERION).name + ".moved")
    refuse(repo, "symbolic link")  # worktree link, not yet committed
    commit_all(repo, "link")
    refuse(repo, "symbolic link")  # committed, mode 120000
    assert git(repo, "ls-tree", "HEAD", "--", CRITERION).startswith("120000")


def test_a_symlink_at_the_plan_or_a_named_input_is_refused(repo):
    freeze(repo, criterion_document(repo / "plan.md"))
    assert call(repo) is not None
    for name in ("plan.md", "b2b_model.txt"):
        git(repo, "reset", "-q", "--hard")
        symlink_in_git(repo, name)
        refuse(repo, "symbolic link")
        git(repo, "reset", "-q", "--hard", "HEAD~1")
        assert call(repo) is not None


def test_a_symlink_in_git_is_refused_even_when_the_worktree_holds_a_regular_file(repo):
    freeze(repo, criterion_document(repo / "plan.md"))
    symlink_in_git(repo, "b2b_model.txt")
    (repo / "b2b_model.txt").unlink()
    (repo / "b2b_model.txt").write_text("b2b_model.txt.real")  # the link text as a regular file
    refuse(repo, "symbolic link in Git")


def test_git_problems_are_typed_errors(repo, tmp_path, monkeypatch):
    freeze(repo, criterion_document(repo / "plan.md"))
    # no plan file at all
    with pytest.raises(BenchmarkError, match="plan"):
        call(repo, plan_path=repo / "no_such_plan.md")
    # a directory that is not a repository
    plain = tmp_path / "plain"
    plain.mkdir()
    (plain / "plan.md").write_text("p")
    (plain / CRITERION).parent.mkdir(parents=True)
    (plain / CRITERION).write_text("x")
    with pytest.raises(BenchmarkError, match="not committed|cannot establish"):
        call(plain, plan_path=plain / "plan.md")
    # git not installed
    monkeypatch.setenv("PATH", str(tmp_path / "empty"))
    with pytest.raises(BenchmarkError, match="git failed"):
        call(repo)


def test_the_environment_cannot_point_git_at_another_repository(repo, tmp_path, monkeypatch):
    freeze(repo, criterion_document(repo / "plan.md"))
    decoy = tmp_path / "decoy"
    decoy.mkdir()
    git(decoy, "init", "-q")
    monkeypatch.setenv("GIT_DIR", str(decoy / ".git"))
    assert call(repo) is not None
    monkeypatch.delenv("GIT_DIR")
    # a replace ref substitutes a commit locally; the guard reads the real objects
    first = head(repo)
    freeze(repo, criterion_document(repo / "plan.md", M1_level_spacing=2.0))
    git(repo, "replace", head(repo), first)
    refuse(repo, "changed after the first commit")


def test_a_shallow_clone_is_refused(repo, tmp_path):
    path = freeze(repo, criterion_document(repo / "plan.md"))
    freeze(repo, criterion_document(repo / "plan.md"), commit=False)
    (repo / "note.txt").write_text("n")
    git(repo, "add", "note.txt")
    git(repo, "commit", "-q", "-m", "later")
    clone = tmp_path / "shallow"
    subprocess.run(
        ["git", "clone", "-q", "--depth", "1", f"file://{repo}", str(clone)],
        check=True, capture_output=True,
    )  # fmt: skip
    assert path.exists()
    refuse(clone, "shallow clone")


def test_git_runs_without_signature_checks_replace_objects_or_a_hidden_root_commit(repo):
    # Finding 3 of the third review: hostile repository-local settings change what git reports.
    marker = repo.parent / "gpg_ran"
    program = repo.parent / "fake_gpg.sh"
    program.write_text(f"#!/bin/sh\ntouch {marker}\nexit 1\n")
    program.chmod(0o755)
    git(repo, "config", "log.showSignature", "true")
    git(repo, "config", "gpg.program", str(program))
    git(repo, "config", "log.showRoot", "false")
    freeze(repo, criterion_document(repo / "plan.md"))
    # give the freeze commit a signature header (not a real one); git verifies it only on request
    body = git(repo, "cat-file", "commit", "HEAD").replace(
        "\n\n",
        "\ngpgsig -----BEGIN PGP SIGNATURE-----\n \n AAAA\n -----END PGP SIGNATURE-----\n\n",
        1,
    )
    signed = subprocess.run(
        ["git", "-C", str(repo), "hash-object", "-t", "commit", "-w", "--stdin"],
        input=body + "\n", capture_output=True, check=True, text=True,
    ).stdout.strip()  # fmt: skip
    git(repo, "reset", "-q", "--soft", signed)
    git(repo, "log", "-1", "--show-signature", "--format=%H")  # the setting is live in this repo
    assert marker.exists()
    marker.unlink()
    assert call(repo) is not None
    assert not marker.exists()  # log.showSignature is switched off for every git call
    # a freeze that sits in a root commit stays visible with log.showRoot=false in .git/config
    root = repo.parent / "rooted"
    root.mkdir()
    git(root, "init", "-q")
    shutil.copy(repo / "plan.md", root / "plan.md")
    for names in INPUT_FILES.values():
        for name in names:
            shutil.copy(repo / f"{name}.txt", root / f"{name}.txt")
    git(root, "config", "log.showRoot", "false")
    (root / holdout.CRITERION_PATH).parent.mkdir(parents=True)
    (root / holdout.CRITERION_PATH).write_text(
        yaml.safe_dump(criterion_document(root / "plan.md", M1_level_spacing=2.0))
    )
    git(root, "add", ".")
    git(root, "commit", "-q", "-m", "everything at once")
    assert call(root).commit == head(root)


def test_a_grafts_file_or_a_partial_clone_is_refused(repo):
    freeze(repo, criterion_document(repo / "plan.md"))
    assert call(repo) is not None
    grafts = repo / ".git" / "info" / "grafts"
    grafts.parent.mkdir(exist_ok=True)
    grafts.write_text(f"{head(repo)}\n")
    refuse(repo, "grafts")
    grafts.unlink()
    assert call(repo) is not None
    git(repo, "config", "extensions.partialClone", "origin")
    refuse(repo, "partial clone")


def test_an_empty_input_file_is_refused_but_a_declared_stage_is_only_a_declaration(repo):
    freeze(repo, criterion_document(repo / "plan.md"))
    (repo / "b2b_model.txt").write_text("")
    git(repo, "commit", "-q", "-am", "empty input")
    refuse(repo, "b2b_model.*is empty")
    # the stage is what the caller says: a wrong declaration is not detected, and the docs say so
    git(repo, "checkout", "HEAD~1", "--", "b2b_model.txt")
    git(repo, "commit", "-q", "-am", "restore input")
    assert call(repo, Split.LOCKED_TEST, validation_stage=ValidationStage.NOT_FAILED) is not None
    text = " ".join(holdout.__doc__.split())
    assert "Stage gating is declared, not established" in text
    assert (
        "`validation_stage`, `sequence_check`, `state` and the existence of the input files" in text
    )


def test_a_limit_must_equal_the_basis_times_the_multiplier_within_a_tiny_tolerance(repo):
    document = criterion_document(repo / "plan.md")
    document["limits"]["M2_wasserstein1_amplitude"] *= 1 + 1e-6  # 1 ppm: far above 1e-9
    freeze(repo, document)
    refuse(repo, "is not b2b_basis x multiplier")
    document["limits"]["M2_wasserstein1_amplitude"] = 0.1 * (1 + 1e-12)  # rounding noise
    freeze(repo, document)
    # history already holds the 1 ppm version, so the later fix is itself a change
    refuse(repo, "changed after the first commit")
    assert holdout._LIMIT_RELATIVE_TOLERANCE == 1e-9


def test_git_failing_in_a_checked_call_is_a_typed_error(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    git(empty, "init", "-q")
    with pytest.raises(BenchmarkError, match="rev-parse failed"):
        holdout._git_ok(empty, "rev-parse", "HEAD")  # no commit yet: a non-zero exit
    assert holdout._git_ok(empty, "rev-parse", "--git-dir")


# ------------------------------------------------------------------ second-review additions
KNOWN_NC_ND = {"CC-BY-NC-ND-4.0", "CC-BY-NC-ND-3.0", "CC-BY-NC-ND-3.0-DE", "cc-by-nc-nd-4.0",
               "CC BY-NC-ND 4.0", "CC_BY_NC_ND_4.0", "CC-BYNCND-4.0"}  # fmt: skip


@pytest.mark.parametrize(
    "license_id",
    [
        "CC-BY-NC-ND-4.0",
        "CC-BY-NC-ND-3.0",
        "CC-BY-NC-ND-3.0-DE",
        "cc-by-nc-nd-4.0",
        "CC BY-NC-ND 4.0",
        "CC_BY_NC_ND_4.0",
        "Attribution-NonCommercial-NoDerivatives 4.0 International",
        "CC-BYNCND-4.0",
        "CCBYNCND",
        "CC\u2011BY\u2011NC\u2011ND\u20114.0",
    ],
)
def test_an_nc_nd_identifier_cannot_be_typed_as_granting_commercial_use_or_derivatives(license_id):
    nc_nd = {
        "private_research_use": Permission.ALLOWED_WITH_CONDITIONS,
        "public_redistribution": Permission.ALLOWED_WITH_CONDITIONS,
        "derivatives": Permission.NOT_ALLOWED,
        "commercial_use": Permission.NOT_ALLOWED,
    }
    if license_id in KNOWN_NC_ND:  # the honest record; a spelling the list lacks cannot grant
        record = make_licence(scope="article", license_id=license_id, **nc_nd)
        assert record.commercial_use is Permission.NOT_ALLOWED
    for grant in (Permission.ALLOWED, Permission.ALLOWED_WITH_CONDITIONS):
        with pytest.raises(BenchmarkError, match="NonCommercial.*commercial use"):
            make_licence(
                scope="article", license_id=license_id, **(nc_nd | {"commercial_use": grant})
            )
        with pytest.raises(BenchmarkError, match="NoDerivatives.*adapted material"):
            make_licence(scope="article", license_id=license_id, **(nc_nd | {"derivatives": grant}))


@pytest.mark.parametrize(
    "license_id", ["Creative Commons NonCommercial", "CC BY-NC 4.0", "NC-SA 4.0", "cc by nd 4.0"]
)
def test_other_spellings_of_nc_or_nd_are_still_caught(license_id):
    with pytest.raises(BenchmarkError, match="NonCommercial|NoDerivatives"):
        make_licence(license_id=license_id)  # the default record grants both


def test_an_unknown_identifier_cannot_grant_anything_unless_it_is_on_the_known_list():
    for license_id in ("Acme Open Data Terms 1", "CC-BY-9.9-ish", "free", "CC BY"):
        with pytest.raises(BenchmarkError, match="not a known identifier"):
            make_licence(license_id=license_id)
        for grant in ("private_research_use", "public_redistribution", "derivatives",
                      "commercial_use"):  # fmt: skip
            denied = dict.fromkeys(
                ("private_research_use", "public_redistribution", "derivatives", "commercial_use"),
                Permission.NOT_ALLOWED,
            )
            with pytest.raises(BenchmarkError, match="not a known identifier"):
                make_licence(license_id=license_id, **(denied | {grant: Permission.ALLOWED}))
        denied_all = dict.fromkeys(
            ("private_research_use", "public_redistribution", "derivatives", "commercial_use"),
            Permission.NOT_ALLOWED,
        )
        assert make_licence(license_id=license_id, **denied_all).license_id == license_id
    for known_id in ("CC-BY-4.0", "CC BY 4.0", "CC0-1.0", "MIT", "Apache-2.0", "BSD-3-Clause",
                     "NCSA", "CC-BY-SA-4.0", "CC-BY-NC-ND-3.0-DE"):  # fmt: skip
        assert make_licence(license_id=known_id, commercial_use=Permission.NOT_ALLOWED
                            if "NC" in known_id else Permission.ALLOWED,
                            derivatives=Permission.NOT_ALLOWED if "ND" in known_id
                            else Permission.ALLOWED)  # fmt: skip


def test_the_ran_config_loads_with_its_real_id_and_not_with_the_full_name(tmp_path):
    document = raw(RAN)
    parse_source(document["source"])
    document["source"]["licenses"][0]["license_id"] = (
        "Attribution-NonCommercial-NoDerivatives 4.0 International"
    )
    with pytest.raises(BenchmarkError, match="not a known identifier"):
        parse_source(document["source"])


def test_licence_identifier_terms_are_matched_as_tokens_not_substrings():
    for license_id, field in (
        ("CC-BY-NC-4.0", "commercial_use"),
        ("CC-BY-NC-SA-4.0", "commercial_use"),
        ("CC-BY-ND-4.0", "derivatives"),
    ):
        with pytest.raises(BenchmarkError):
            make_licence(license_id=license_id, **{field: Permission.ALLOWED})
    # CC-BY, MIT and an id that merely contains the letters grant what they say
    for license_id in ("CC-BY-4.0", "CC-BY-SA-4.0", "MIT", "NCSA", "Apache-2.0", "CC0-1.0"):
        record = make_licence(
            license_id=license_id,
            commercial_use=Permission.ALLOWED,
            derivatives=Permission.ALLOWED,
        )
        assert record.commercial_use is Permission.ALLOWED


def test_a_ran_config_edited_to_grant_what_nc_nd_excludes_does_not_load(tmp_path):
    for field in ("derivatives", "commercial_use"):
        document = raw(RAN)
        document["source"]["licenses"][0][field] = "ALLOWED"
        with pytest.raises(BenchmarkError, match="NonCommercial|NoDerivatives"):
            parse_source(document["source"])
        path = write(tmp_path, document, f"ran_{field}.yaml")
        with pytest.raises(BenchmarkError):
            load_source_config(path)


@pytest.mark.parametrize(
    "field, permission",
    [
        ("public_redistribution", Permission.UNVERIFIED),
        ("commercial_use", Permission.UNVERIFIED),
        ("derivatives", Permission.UNVERIFIED),
    ],
)
def test_a_record_level_licence_with_an_unverified_permission_does_not_pass_the_gates(
    field, permission
):
    source = make_source(make_licence(**{field: permission}))
    messages = {
        "public_redistribution": "public redistribution",
        "commercial_use": "commercial use",
        "derivatives": "adapted material",
    }
    with pytest.raises(BenchmarkError, match=messages[field]) as error:
        source.require_derivatives("data")
    assert error.value.code is ErrorCode.LICENSE_UNVERIFIED
    if field != "derivatives":
        with pytest.raises(BenchmarkError, match=messages[field]):
            source.require_public_redistribution("data")
    else:
        source.require_public_redistribution("data")  # verbatim publication is not adapted


def test_the_supplied_md5_of_one_asset_equals_the_local_md5_of_another(tmp_path):
    # Review finding 4: keys were per kind, so a supplied and a local MD5 never met.
    payload = b"one acquisition under two names"
    path = tmp_path / "x.bin"
    path.write_bytes(payload)
    digest = hashlib.md5(payload).hexdigest()
    supplied = make_asset(group="g/A", split=Split.CHARACTERISATION, name="a.bin", md5=digest)
    local = with_local_hash(make_asset(group="g/B", split=Split.VALIDATION, name="b.bin"), path)
    assert supplied.checksum.md5_local is None and local.checksum.md5_supplied is None
    for pair in ((supplied, local), (local, supplied)):
        with pytest.raises(BenchmarkError, match="MD5") as error:
            assert_no_split_overlap(pair)
        assert error.value.code is ErrorCode.LEAKAGE_DETECTED
    # the same file in the same group and role is not leakage
    same = with_local_hash(make_asset(group="g/A", name="c.bin", md5=digest), path)
    assert_no_split_overlap((supplied, same))
    # different digests never meet
    other = make_asset(group="g/C", split=Split.LOCKED_TEST, name="c2.bin", md5="0" * 32)
    assert_no_split_overlap((other, supplied))


@pytest.mark.parametrize(
    "text",
    ["TBD", "tbd", "TBA", "?", "??", "???", "n / a", "N/A", "  to do ", "todo", "unspecified",
     "- - -", "~", "...", "?-", "nil", "Pending", "tbd.", "TBC", "n/a."],
)  # fmt: skip
def test_placeholder_words_are_not_known_text(text):
    with pytest.raises(BenchmarkError, match="not a known value"):
        ParameterValue(text, Provenance.PUBLISHED_MEASUREMENT, source_ref="r")


def test_none_is_an_answer_for_the_equalizer_and_a_placeholder_elsewhere():
    # A source that says it used no equaliser is a known value; an unknown one stays null.
    document = raw(RAN)
    parameters = document["source"]["parameters"]
    parameters["equalizer"] = {
        "value": "none", "provenance": "PUBLISHED_MEASUREMENT", "source_ref": "article",
    }  # fmt: skip
    assert parse_source(document["source"]).parameters["equalizer"].value == "none"
    for field in ("fibre_type", "detector", "calibration", "raw_format"):
        parameters = document["source"]["parameters"]
        parameters[field] = {
            "value": "none", "provenance": "PUBLISHED_MEASUREMENT", "source_ref": "article",
        }  # fmt: skip
        with pytest.raises(BenchmarkError, match="not a known value"):
            parse_source(document["source"])
        del parameters[field]
    with pytest.raises(BenchmarkError, match="not a known value"):
        ParameterValue("nil", Provenance.PUBLISHED_MEASUREMENT, source_ref="r")


def test_real_text_that_resembles_a_placeholder_is_accepted():
    for text in ("TBD-1 board", "what?", "a-b", "N/A type 2", "3.5"):
        assert ParameterValue(text, Provenance.PUBLISHED_MEASUREMENT, source_ref="r").known


def check_parameter(field, parameter):
    provenance._check_parameters({field: parameter}, provenance.SOURCE_FIELDS, "t")


@pytest.mark.parametrize(
    "field, value",
    [
        ("sample_rate_hz", 256),  # 256 Hz instead of 256 GSa/s
        ("sample_rate_hz", 5e5),
        ("sample_rate_hz", 1e14),
        ("sample_rate_hz", 10**400),
        ("baud_bd", 50),
        ("baud_bd", 10**400),
        ("baud_bd", 1e13),
        ("wavelength_nm", 1.55),  # micrometres typed as nanometres
        ("wavelength_nm", 1e6),
        ("fibre_length_km", 1e6),
        ("dispersion_ps_per_nm_km", 1e300),
        ("dispersion_ps_per_nm_km", -(10**400)),
    ],
)
def test_implausible_numbers_are_refused_by_a_declared_range(field, value):
    unit = provenance._NUMERIC_FIELDS[field][0]
    parameter = ParameterValue(value, Provenance.PUBLISHED_MEASUREMENT, unit=unit, source_ref="r")
    with pytest.raises(BenchmarkError, match="plausible range"):
        check_parameter(field, parameter)


def test_plausible_ranges_are_declared_and_accept_the_documented_values():
    assert provenance.PLAUSIBLE_RANGES == {
        "sample_rate_hz": (1e6, 1e13),
        "baud_bd": (1e6, 1e12),
        "wavelength_nm": (200.0, 20000.0),
        "fibre_length_km": (0.0, 1e5),
        "dispersion_ps_per_nm_km": (-1e4, 1e4),
    }
    for field in provenance.PLAUSIBLE_RANGES:
        low, high = provenance.PLAUSIBLE_RANGES[field]
        unit = provenance._NUMERIC_FIELDS[field][0]
        for value in (low, high):
            parameter = ParameterValue(
                value, Provenance.PUBLISHED_MEASUREMENT, unit=unit, source_ref="r"
            )
            check_parameter(field, parameter)
    # the documented values stay accepted
    for field, value in (
        ("baud_bd", 50e9), ("sample_rate_hz", 256e9), ("dispersion_ps_per_nm_km", -3.99),
        ("wavelength_nm", 1271), ("fibre_length_km", 0),
    ):  # fmt: skip
        unit = provenance._NUMERIC_FIELDS[field][0]
        check_parameter(
            field,
            ParameterValue(value, Provenance.PUBLISHED_MEASUREMENT, unit=unit, source_ref="r"),
        )
    make_asset(sample_rate_hz=good("sample_rate_hz"), baud_bd=good("baud_bd"))


def test_a_verified_state_cannot_travel_by_pickle_copy_or_dict_write(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"abc")
    verified = verify_local_asset(path, hashlib.md5(b"abc").hexdigest())
    assert verified.md5_state is Md5State.VERIFIED
    for forge in (pickle.dumps, copy.copy, copy.deepcopy):
        with pytest.raises(TypeError, match="not pickled or copied"):
            forge(verified)
    for blank in (Checksum(), Checksum(md5_supplied=MD5_B2B)):
        with pytest.raises(TypeError):
            pickle.dumps(blank)
    assert not hasattr(verified, "__dict__")
    with pytest.raises((AttributeError, TypeError)):
        verified.__dict__ = {"md5_local": MD5_B2B}  # type: ignore[misc]
    with pytest.raises(AttributeError):
        verified.__dict__["md5_local"] = MD5_B2B  # type: ignore[attr-defined]


def test_the_verified_result_carries_size_and_mtime_and_goes_stale_when_the_file_changes(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"abcdef")
    checksum = verify_local_asset(path)
    assert checksum.size_local == 6
    assert checksum.mtime_ns_local == path.stat().st_mtime_ns
    assert checksum.still_current(path)
    path.write_bytes(b"abcdefg")  # size changes
    assert not checksum.still_current(path)
    fresh = verify_local_asset(path)
    assert fresh.still_current(path)
    os.utime(path, ns=(1, fresh.mtime_ns_local + 10_000_000_000))  # same size, newer mtime
    assert not fresh.still_current(path)
    assert not Checksum().still_current(path)  # never hashed
    assert not fresh.still_current(tmp_path / "gone.bin")
    # dataclasses.replace drops the local facts together with the hashes
    assert dataclasses.replace(fresh, md5_supplied=MD5_B2B).size_local is None


def test_still_current_checks_the_size_and_the_time_each_on_its_own(tmp_path):
    path = tmp_path / "f.bin"
    path.write_bytes(b"abcdef")
    fresh = verify_local_asset(path)
    stamp = path.stat().st_mtime_ns
    path.write_bytes(b"abcdefgh")  # another size, the old time put back
    os.utime(path, ns=(stamp, stamp))
    assert path.stat().st_mtime_ns == fresh.mtime_ns_local and not fresh.still_current(path)
    path.write_bytes(b"abcdef")  # the old size, another time
    os.utime(path, ns=(stamp + 5_000_000_000, stamp + 5_000_000_000))
    assert not fresh.still_current(path)
    os.utime(path, ns=(stamp, stamp))
    assert fresh.still_current(path)
    # a checksum with only one of the two local facts is never current
    for missing in ("size_local", "mtime_ns_local"):
        partial = verify_local_asset(path)
        object.__setattr__(partial, missing, None)
        assert partial.still_current(path) is False


def test_verify_local_asset_reads_in_chunks_and_opens_read_only(tmp_path, monkeypatch):
    payload = bytes(range(256)) * 40  # 10 240 bytes
    path = tmp_path / "chunks.bin"
    path.write_bytes(payload)
    path.chmod(0o444)
    monkeypatch.setattr(provenance, "_CHUNK", 1000)
    reads: list[int] = []
    modes: list[str] = []
    real_open = Path.open

    def spy_open(self, mode="r", *args, **kwargs):
        modes.append(mode)
        handle = real_open(self, mode, *args, **kwargs)
        real_read = handle.read

        def read(size=-1):
            reads.append(size)
            return real_read(size)

        return _ReadSpy(handle, read)

    monkeypatch.setattr(Path, "open", spy_open)
    checksum = verify_local_asset(path)
    assert modes == ["rb"]
    assert reads and set(reads) == {1000}  # never a whole-file read
    assert len(reads) == 12  # eleven chunks and the empty read that ends the loop
    assert checksum.sha256_local == hashlib.sha256(payload).hexdigest()
    assert path.read_bytes() == payload and (path.stat().st_mode & 0o777) == 0o444


class _ReadSpy:
    def __init__(self, handle, read):
        self._handle, self.read = handle, read

    def __enter__(self):
        self._handle.__enter__()
        return self

    def __exit__(self, *exc):
        return self._handle.__exit__(*exc)

    def fileno(self):
        return self._handle.fileno()


def test_a_file_that_cannot_be_read_is_a_typed_error(tmp_path):
    path = tmp_path / "locked.bin"
    path.write_bytes(b"x")
    path.chmod(0o000)
    try:
        if os.access(path, os.R_OK):
            pytest.skip("permissions are not enforced for this user")
        with pytest.raises(BenchmarkError, match="cannot be read"):
            verify_local_asset(path)
    finally:
        path.chmod(0o644)


def test_a_config_that_is_not_utf8_text_is_a_typed_error(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_bytes(b"\xff\xfe not utf-8")
    with pytest.raises(BenchmarkError, match="cannot be read as UTF-8"):
        load_source_config(path)


# ------------------------------------------------------------------ strict loader
def mutate(tmp_path, edit):
    document = raw()
    edit(document)
    return write(tmp_path, document)


def with_text(tmp_path, edit) -> Path:
    path = tmp_path / "dup.yaml"
    path.write_text(edit(TERIPHIC.read_text()))
    return path


def test_duplicate_yaml_keys_are_refused_at_every_level(tmp_path):
    # Repro 1 of the review: a second `split` under the 10 km asset used to win silently.
    def second_split(text):
        needle = "        split: LOCKED_TEST\n"
        assert text.count(needle) == 1
        return text.replace(needle, needle + "        split: CHARACTERISATION\n")

    with pytest.raises(BenchmarkError, match="duplicate key 'split'"):
        load_source_config(with_text(tmp_path, second_split))

    # Repro 2: a second wavelength_nm turned an unknown into a measured value.
    def second_wavelength(text):
        marker = "          wavelength_nm: {value: null, provenance: UNKNOWN"
        last = text.rindex(marker)
        end = text.index("\n", last) + 1
        extra = (
            "          wavelength_nm: {value: 1310, provenance: PUBLISHED_MEASUREMENT,"
            " unit: nm, source_ref: x}\n"
        )
        return text[:end] + extra + text[end:]

    with pytest.raises(BenchmarkError, match="duplicate key 'wavelength_nm'"):
        load_source_config(with_text(tmp_path, second_wavelength))

    def second_md5(text):
        needle = '        md5_supplied: "3d8774b068deaf50f37892b38953dfd6"\n'
        return text.replace(needle, needle + needle.replace("3d8774", "d7bd6d"))

    with pytest.raises(BenchmarkError, match="duplicate key 'md5_supplied'"):
        load_source_config(with_text(tmp_path, second_md5))

    for key, text in {
        "source_id": lambda t: t.replace("  source_id: teriphic_pd_array\n", "  source_id: teriphic_pd_array\n  source_id: other\n"),
        "benchmark_config_version": lambda t: t.replace("benchmark_config_version: 1\n", "benchmark_config_version: 1\nbenchmark_config_version: 1\n"),
        "value": lambda t: t.replace("{value: 0, provenance", "{value: 0, value: 9, provenance", 1),
    }.items():  # fmt: skip
        with pytest.raises(BenchmarkError, match=f"duplicate key '{key}'"):
            load_source_config(with_text(tmp_path, text))
    # merge keys count as keys: an override through `<<` is refused too
    merged = TERIPHIC.read_text().replace(
        '  retrieved: "2026-10-31"\n',
        '  retrieved: "2026-10-31"\n  <<: {retrieved: "2000-01-01"}\n',
    )
    path = tmp_path / "merge.yaml"
    path.write_text(merged)
    with pytest.raises(BenchmarkError, match="duplicate key 'retrieved'"):
        load_source_config(path)
    complex_key = TERIPHIC.read_text().replace("source:\n", "source:\n  ? [1, 2]\n  : x\n", 1)
    path.write_text(complex_key)
    with pytest.raises(BenchmarkError, match="unhashable"):
        load_source_config(path)


def test_the_committed_configs_have_no_duplicate_keys():
    for path in (TERIPHIC, RAN, WIEGART):
        assert catalog.load_strict_yaml(path.read_text()) == yaml.safe_load(path.read_text())


@pytest.mark.parametrize(
    "edit, message",
    [
        (lambda d: d.update(extra=1), "unknown keys"),
        (lambda d: d.update(benchmark_config_version=2), "benchmark_config_version"),
        (lambda d: d.update(benchmark_config_version=True), "benchmark_config_version"),
        (lambda d: d["source"].update(extra=1), "unknown keys"),
        (lambda d: d["source"].pop("doi"), "missing keys"),
        (lambda d: d["source"].update(kind="notebook"), "dataset or publication"),
        (lambda d: d["source"].update(title="   "), "non-empty string"),
        (lambda d: d["source"]["licenses"][0].update(extra=1), "unknown keys"),
        (lambda d: d["source"]["licenses"][0].update(status="open"), "not one of"),
        (lambda d: d["source"]["licenses"][0].update(status="VERIFIED"), "not one of"),
        (lambda d: d["source"]["licenses"][0].update(scope="code"), "scope"),
        (lambda d: d["source"]["licenses"][0].pop("derivatives"), "missing keys"),
        (lambda d: d["source"]["licenses"][0].pop("commercial_use"), "missing keys"),
        (lambda d: d["source"]["licenses"][0].update(commercial_use="YES"), "not one of"),
        (lambda d: d["source"]["licenses"][0].update(read_how="guess"), "ReadHow"),
        (lambda d: d["source"]["licenses"].append(dict(d["source"]["licenses"][0])), "twice"),
        (lambda d: d["source"]["licenses"].clear(), "licence state is required"),
        (lambda d: d["source"].update(licenses="CC-BY"), "licence state is required"),
        (lambda d: d["source"].update(assets="none"), "must be a list"),
        (lambda d: d["source"]["assets"][0].update(extra=1), "unknown keys"),
        (lambda d: d["source"]["assets"][0].update(split="TEST"), "not one of"),
        (lambda d: d["source"]["assets"][0].update(size_bytes=-5), "positive integer"),
        (lambda d: d["source"]["assets"][0].update(size_bytes=True), "positive integer"),
        (lambda d: d["source"]["assets"][0].update(md5_supplied="nothex"), "hexadecimal"),
        (lambda d: d["source"]["assets"][0].update(md5_supplied="  "), "non-empty"),
        (lambda d: d["source"]["assets"][0].update(md5_local="0" * 32), "unknown keys"),
        (lambda d: d["source"]["assets"][0].update(filename="../x.bin"), "not allowed"),
        (lambda d: d["source"]["assets"].append(dict(d["source"]["assets"][0])), "twice"),
        (lambda d: d["source"]["assets"][0]["parameters"].pop("raw_format"), "raw_format"),
        (lambda d: d["source"]["assets"][0]["parameters"].update(laser={"value": None, "provenance": "UNKNOWN"}), "unknown parameter"),
        (lambda d: d["source"]["assets"][0]["parameters"].update(baud_bd="fast"), "mapping"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].pop("provenance"), "missing keys"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(provenance="MEASURED"), "not one of"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(source_ref=None), "source_ref"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(value=True), "number, a string or null"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(value=[1]), "number, a string or null"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(value={"a": 1}), "number, a string or null"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(extra=1), "unknown keys"),
        (lambda d: d["source"]["assets"][0]["parameters"]["baud_bd"].update(read_how="guess"), "ReadHow"),
        (lambda d: d["source"]["assets"][0]["parameters"]["wavelength_nm"].update(value=1310), "UNKNOWN"),
        (lambda d: d["source"]["assets"][0]["parameters"]["wavelength_nm"].update(provenance="SIMULATED"), "missing value"),
        (lambda d: d["source"]["assets"][0]["parameters"]["fibre_type"].update(
            value="G.652.D", provenance="SIMULATED", source_ref="default"), "SIMULATED"),
        (lambda d: d["source"].update(plan_sha256="abc"), "plan_sha256"),
    ],
)  # fmt: skip
def test_malformed_config_is_refused_at_every_level(tmp_path, edit, message):
    with pytest.raises(BenchmarkError, match=message):
        load_source_config(mutate(tmp_path, edit))


def test_loader_rejects_non_mapping_and_bad_yaml(tmp_path):
    for body in ("- a\n- b\n", "source: [", ""):
        path = tmp_path / "bad.yaml"
        path.write_text(body)
        with pytest.raises(BenchmarkError):
            load_source_config(path)
    for place in ("asset", "source"):
        document = raw()
        target = document["source"]["assets"][0] if place == "asset" else document["source"]
        target["parameters"] = ["baud_bd"]
        with pytest.raises(BenchmarkError, match="mapping of parameter name"):
            load_source_config(write(tmp_path, document))


def test_catalog_module_exports_no_loader_for_urls():
    assert not hasattr(catalog, "urlopen") and not hasattr(catalog, "download")


# ------------------------------------------------------------------ importer audit
def fake_teriphic_bins(tmp_path: Path) -> dict[str, Path]:
    """Independently made files that only carry a TERIPHIC name; none is a capture."""
    rng = np.random.default_rng(7)
    floats = rng.normal(size=4096).astype("<f4").tobytes()
    cases = {
        "float32_noise": floats,
        "int16_noise": rng.integers(-2000, 2000, 4096).astype("<i2").tobytes(),
        "zeros": bytes(4096),
        "cookie_only": b"AG10" + bytes(8),
        "cookie_wrong_size": b"AG10" + (9999).to_bytes(4, "little") + (1).to_bytes(4, "little") + floats,
        "wrong_cookie_right_size": b"XX10" + (4096 + 12).to_bytes(4, "little") + (1).to_bytes(4, "little") + bytes(4096),
        "header_only": b"AG10" + (12).to_bytes(4, "little") + (1).to_bytes(4, "little"),
    }  # fmt: skip
    out = {}
    for tag, blob in cases.items():
        path = tmp_path / f"50G_PAM4_PD1_B2B_Subassembly1_{tag}.bin"
        path.write_bytes(blob)
        out[tag] = path
    return out


def test_teriphic_named_fake_bin_is_rejected_by_the_keysight_parser(tmp_path):
    for tag, path in fake_teriphic_bins(tmp_path).items():
        with pytest.raises(UxrImportError):
            read_bin(path)
        with pytest.raises(UxrImportError):
            read_scope_file(path)
        assert path.exists(), tag  # the importer never modifies its input
