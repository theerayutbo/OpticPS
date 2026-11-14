"""Mutation check of the NANF fibre-profile guards (Gate N2a).

Each mutant is one text replacement in `optical_channel/fiber.py` or `link.py`, applied to a scratch
copy of the files the NANF tests need. The NANF test files run against that copy; a mutant is
"killed" when a test fails (pytest exit code 1). A survivor means a guard has no test that notices
its removal. A mutant that breaks collection (exit code 2 or more) is reported BROKEN, never
killed, and the unmutated copy must pass first. The exit code is 0 only when every listed mutant is
killed. A mutant run that does not end in 30 minutes is reported killed (a hang), and each
outcome is printed as it completes.

    python scripts/mutate_nanf.py [-j JOBS] [-k LABEL_SUBSTRING]

The list is a hand-written sample of the guards (the 14 gaps of the third N1 review, the N2a
guards, the N2 fix-round guards, the N3 part a guards, the 14 survivors of the first N3 part a
review and the guards added in the N3 part a fix round, then the N3 part b guards: the fit driver,
the freeze script and the holdout runner). It proves nothing about mutants that are
not in it.
The label says what the mutant does.
"""

# SPDX-License-Identifier: MIT
# ruff: noqa: E501  (mutant texts are source lines and may be long)
from __future__ import annotations

import argparse
import os
import shutil
import signal
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
M = "src/opticps/measurement/nanf_import.py"
B = "src/opticps/measurement/nanf_benchmark.py"
F = "src/opticps/optical_channel/fiber.py"
L = "src/opticps/optical_channel/link.py"
D = "src/opticps/receiver/dfe.py"
CH = "src/opticps/measurement/nanf_chain.py"
SC = "src/opticps/measurement/nanf_scoring.py"
FZ = "src/opticps/measurement/nanf_freeze.py"
NF = "src/opticps/measurement/nanf_fit.py"
NH = "src/opticps/measurement/nanf_holdout.py"
SF = "scripts/nanf_fit.py"
TESTS = (
    "tests/nanf_fit_stub.py",
    "tests/nanf_fit_study.py",
    "tests/test_nanf_n3b_fix.py",
    "tests/test_nanf_n3b_study.py",
    "tests/nanf_holdout_stub.py",
    "tests/test_nanf_n3b_fit.py",
    "tests/test_nanf_n3b_holdout.py",
    "tests/nanf_freeze_support.py",
    "tests/test_nanf_profiles.py",
    "tests/test_nanf_propagation.py",
    "tests/test_nanf_n2a.py",
    "tests/test_nanf_import.py",
    "tests/nanf_workbook_fixture.py",
    "tests/test_nanf_benchmark.py",
    "tests/test_nanf_n3_step1.py",
    "tests/test_nanf_n3a_dfe.py",
    "tests/test_nanf_n3a_chain.py",
    "tests/test_nanf_n3a_fix.py",
    "tests/test_nanf_n3a_lost_lock.py",
    "tests/test_nanf_n3a_review2.py",
    "tests/test_nanf_n3a_scoring.py",
    "tests/test_nanf_n3a_freeze.py",
)
# Reviewed as equivalent and left out: dropping `link` or `nanf_import` from ENTRY_MODULES (both stay
# reachable by imports from nanf_chain and nanf_benchmark); reading infinity as censored in
# `is_censored` (the range check still refuses it); allowing NaN fields in `Crossing` (the per-kind
# finiteness checks still refuse them).
# Equivalent, left out (Amendment 12): an explicit finite check of a replayed residual vector; a NaN
# residual gives a recomputed cost that differs from any recorded one, and infinity is refused by the
# lost-point check, so removing the explicit check changes no outcome.
# Equivalent, left out (N3 part b): dropping `np.clip(u, 0.0, 1.0)` in `run_optimiser.call`; every point
# that reaches it is inside the box already (the design, the clipped trials, the Jacobian steps).
# Equivalent, left out: removing `require_scorable([result])` from `run_point` (the same refusal
# is made by `PointOutcome.__post_init__`, which is itself mutated and killed).
# Fast files first, so that most mutants are killed early; the slow chain tests run last.
RUN_ORDER = (
    "tests/test_nanf_n3a_scoring.py",
    "tests/test_nanf_n3a_lost_lock.py",
    "tests/test_nanf_n3a_review2.py",
    "tests/test_nanf_n3a_freeze.py",
    "tests/test_nanf_n3_step1.py",
    "tests/test_nanf_n3a_dfe.py",
    "tests/test_nanf_import.py",
    "tests/test_nanf_n2a.py",
    "tests/test_nanf_profiles.py",
    "tests/test_nanf_propagation.py",
    "tests/test_nanf_benchmark.py",
    "tests/test_nanf_n3a_chain.py",
    "tests/test_nanf_n3a_fix.py",
)
# The N3 part b mutants are killed by the new tests; those run first for them, so that the older
# mutants do not wait for the (slower) new files.
MUTANT_TIMEOUT_S = 1800  # a mutant run that does not end in this time is reported killed (a hang)
NEW_PREFIXES = (
    "fit:",
    "holdout:",
    "chain: the declared",
    "freeze: the holdout runner",
    "freeze: the artefact checks",
    "freeze: a malformed log hash",
)
NEW_ORDER = (
    "tests/test_nanf_n3b_fit.py",
    "tests/test_nanf_n3b_fix.py",
    "tests/test_nanf_n3b_holdout.py",
    "tests/test_nanf_n3b_study.py",
    *RUN_ORDER,
)
# (label, file, old text, new text); `old` must occur exactly once.
MUTANTS: list[tuple[str, str, str, str]] = [
    # the 14 gaps of the third N1 review (finding 6)
    ("rel tol 1e-2", F, "_AGREEMENT_REL_TOL = 1e-6", "_AGREEMENT_REL_TOL = 1e-2"),
    ("rel tol 1e-5", F, "_AGREEMENT_REL_TOL = 1e-6", "_AGREEMENT_REL_TOL = 1e-5"),
    ("rel tol 1e-7", F, "_AGREEMENT_REL_TOL = 1e-6", "_AGREEMENT_REL_TOL = 1e-7"),
    ("slope abs tol 1e-2", F, "_SLOPE_TOLERANCE_ABS = 1e-3", "_SLOPE_TOLERANCE_ABS = 1e-2"),
    ("slope abs tol 0", F, "_SLOPE_TOLERANCE_ABS = 1e-3", "_SLOPE_TOLERANCE_ABS = 0.0"),
    ("slope rel tol 0.5", F, "_SLOPE_TOLERANCE_REL = 0.1", "_SLOPE_TOLERANCE_REL = 0.5"),
    ("slope rel tol 0", F, "_SLOPE_TOLERANCE_REL = 0.1", "_SLOPE_TOLERANCE_REL = 0.0"),
    (
        "scenario S uses a precedence",
        F,
        "decl = None if slope_from_scenario else profile.precedence.get(name)",
        "decl = profile.precedence.get(name)",
    ),
    ("slope_at left side", F, 'wavelength_nm, side="right"', 'wavelength_nm, side="left"'),
    (
        "slope_at no left clip",
        F,
        'wavelength_nm, side="right"), 1, len(wl) - 1',
        'wavelength_nm, side="right"), 0, len(wl) - 1',
    ),
    (
        "outside-span conflict branch removed",
        F,
        "            if scalar_extrapolated:\n                # the scalar does not hold here",
        "            if False:\n                # the scalar does not hold here",
    ),
    (
        "raw scalar compared before placing D",
        F,
        "if not math.isclose(value, tab, rel_tol=_AGREEMENT_REL_TOL, abs_tol=1e-12):",
        "if not math.isclose(pv.value, tab, rel_tol=_AGREEMENT_REL_TOL, abs_tol=1e-12):",
    ),
    (
        "sentinel: slope None skip removed",
        F,
        "if table is None or slope is None or scalar_d_declared_over_table:",
        "if table is None or scalar_d_declared_over_table:",
    ),
    (
        "laser cap applied to fixed launch",
        L,
        "    result = transmit(normalized, sample_rate, config, rng)\n"
        "    record = resolved.to_record()",
        "    if config.laser_power_w > MAX_MATCHED_LASER_POWER_W:\n"
        '        raise ValueError("cap")\n'
        "    result = transmit(normalized, sample_rate, config, rng)\n"
        "    record = resolved.to_record()",
    ),
    (
        "citation distinct 3",
        F,
        "len(set(compact.casefold())) < 4",
        "len(set(compact.casefold())) < 3",
    ),
    ("citation floor 5", F, "if len(compact) < 6 or", "if len(compact) < 5 or"),
    ("citation floor 7", F, "if len(compact) < 6 or", "if len(compact) < 7 or"),
    (
        "precedence needs no real citation",
        F,
        "        if not is_real_citation(self.provenance.citation):\n"
        '            raise FiberProfileError("a precedence declaration needs a real citation")',
        "        if False:\n"
        '            raise FiberProfileError("a precedence declaration needs a real citation")',
    ),
    (
        "precedence of unknown provenance",
        F,
        "        if self.provenance.category is ProvenanceCategory.UNKNOWN:\n"
        '            raise FiberProfileError("a precedence declaration needs a stated provenance")',
        "        if False:\n"
        '            raise FiberProfileError("a precedence declaration needs a stated provenance")',
    ),
    # N2 importer guards
    ("importer: hash not checked", M, "if digest != expected_sha256:", "if False:"),
    (
        "importer: hidden sheet accepted",
        M,
        'if any(s[2] != "visible" for s in sheets):',
        "if False:",
    ),
    ("importer: DOCTYPE accepted", M, 'b"<!doctype" in lowered or ', "False or "),
    ("importer: zero BER not censored", M, "if value == 0.0:", "if False:"),
    ("importer: censor floor 0", M, "elif value < BER_CENSOR_FLOOR:", "elif value < 0.0:"),
    ("importer: BER above 1 accepted", M, "if not 0.0 <= value <= 1.0:", "if False:"),
    (
        "importer: unordered axis accepted",
        M,
        "if any(b <= a for a, b in zip(axis, axis[1:], strict=False)):",
        "if False:",
    ),
    ("importer: any formula accepted", M, 'cell.formula != "-Inf"', "False"),
    ("importer: Fig.6 B2B read as calibration", M, "b2b_role if link", "_CAL if link"),
    (
        "importer: holdout returned by default",
        M,
        "include_holdout or s.role is not DataRole.HOLDOUT",
        "True",
    ),
    (
        "importer: repr shows values",
        M,
        'f"{self.provenance.value}, {shown})"',
        'f"{self.provenance.value}, {shown}, {self.y})"',
    ),
    ("importer: missing cells accepted", M, "        if missing:", "        if False:"),
    (
        "importer: negative loss accepted",
        M,
        'elif s.quantity in ("link_loss", "capacity", "latency") and value < 0.0:',
        "elif False:",
    ),
    (
        "importer: dimension not checked",
        M,
        'if dim is None or dim.get("ref") != layout.dimension:',
        "if False:",
    ),
    (
        "importer: merged ranges not checked",
        M,
        "if sorted(merges) != sorted(layout.merges):",
        "if False:",
    ),
    (
        "importer: sheet list not checked",
        M,
        "if [s[0] for s in sheets] != list(EXPECTED_SHEETS):",
        "if False:",
    ),
    ("importer: non-finite number accepted", M, "if not math.isfinite(value):", "if False:"),
    # N2a guards
    (
        "declared-over-table flag never set",
        F,
        "                    d_declared_over_table = True\n",
        "                    pass\n",
    ),
    (
        "scenario S placing a scalar D may override a table",
        F,
        '                if name == "dispersion_ps_per_nm_km" and slope_from_scenario:\n'
        "                    raise FiberProfileError(",
        '                if False and name == "dispersion_ps_per_nm_km":\n'
        "                    raise FiberProfileError(",
    ),
    (
        "scenario D with S and no wavelength accepted",
        F,
        "                    if anchor_nm is None:\n"
        "                        raise OutOfValidityRangeError(\n"
        '                            "the scenario D states',
        "                    if False:\n"
        "                        raise OutOfValidityRangeError(\n"
        '                            "the scenario D states',
    ),
    (
        "scenario D not moved by S",
        F,
        "out[name] = values[name] + slope_value * (wavelength_nm - anchor_nm)",
        "out[name] = values[name]",
    ),
    (
        "scenario wavelength without a D accepted",
        F,
        '            if "dispersion_ps_per_nm_km" not in self.values:',
        "            if False:",
    ),
    (
        "measurement wavelength outside own range accepted",
        F,
        "if wl is not None and not low - tol <= wl <= high + tol:",
        "if False:",
    ),
    (
        "measurement wavelength range edge refused",
        F,
        "if wl is not None and not low - tol <= wl <= high + tol:",
        "if wl is not None and not low < wl < high:",
    ),
    (
        "base label dropped from the link record",
        L,
        '        record["sensitivity_scenario"] = config.sensitivity_scenario\n'
        '        record["not_a_benchmark_result"] = True\n',
        "        pass\n",
    ),
    (
        "ZeroDivisionError at extreme loss",
        L,
        "laser_w = target_w / transmission if transmission > 0 else math.inf",
        "laser_w = target_w / transmission",
    ),
    # N2 fix round: the 9 survivors of the independent N2 review, then the new guards
    (
        "importer: plain-number message echoes the cell",
        M,
        'is not a plain number as the layout requires")',
        'is not a plain number as the layout requires {cell.text}")',
    ),
    (
        "importer: BER message echoes the value",
        M,
        'raise _fail(f"{sheet}: BER cell {ref} lies outside [0, 1]")',
        'raise _fail(f"{sheet}: BER cell {ref} lies outside [0, 1] {value}")',
    ),
    ("importer: NUL filter removed", M, 'if b"\\x00" in data or ', "if False or "),
    (
        "importer: member-count cap removed",
        M,
        "if len(infos) > MAX_MEMBERS or any(",
        "if any(",
    ),
    ("importer: rich-text runs ignored", M, 'elif child.tag == f"{_NS}r":', "elif False:"),
    (
        "importer: shared formula without a master accepted",
        M,
        "formula = masters.get(si)",
        'formula = masters.get(si) or "-Inf"',
    ),
    (
        "benchmark: Fig.1 role check removed",
        B,
        "if s.role is not DataRole.CROSS_CHECK:",
        "if False:",
    ),
    (
        "benchmark: Fig.5 role check removed",
        B,
        "if s.role is not DataRole.CALIBRATION_INPUT:",
        "if False:",
    ),
    ("benchmark: null tolerance 3.0", B, "NULL_TOLERANCE_GHZ = 0.3", "NULL_TOLERANCE_GHZ = 3.0"),
    (
        "importer: inline string outside the layout counts as empty",
        M,
        'if element.find(f"{_NS}is") is not None:',
        "if False:",
    ),
    (
        "importer: corrupt deflate raises the raw zlib error",
        M,
        "                zlib.error,\n",
        "",
    ),
    (
        "importer: bad CRC raises the raw BadZipFile",
        M,
        "                zipfile.BadZipFile,\n                EOFError,",
        "                EOFError,",
    ),
    (
        "importer: cap point at -5 dBm excluded",
        M,
        "x > ROP_SCORING_CAP_DBM",
        "x >= ROP_SCORING_CAP_DBM",
    ),
    (
        "importer: measured results tagged by block only",
        M,
        "if quantity in _MEASURED_QUANTITIES:",
        "if False:",
    ),
    # Gate N3 step 1: the 7 survivors of the second N2 review and the new length and index guards
    (
        "importer: negative shared-string index accepted",
        M,
        "if not 0 <= index < len(shared):",
        "if not index < len(shared):",
    ),
    (
        "importer: non-ASCII digit index accepted",
        M,
        "text.isascii() and text.isdigit()",
        "text.isdigit()",
    ),
    ("importer: shared index length unbounded", M, " and len(text) <= 9", ""),
    (
        "benchmark: loss bound ignores the length argument",
        B,
        "    return link_loss_at(wb, wavelength_nm) / length_km",
        "    return link_loss_at(wb, wavelength_nm) / 4.76",
    ),
    (
        "benchmark: length not validated",
        B,
        "    if not valid:",
        "    if False:",
    ),
    ("importer: EOFError not typed", M, "                EOFError,\n", ""),
    ("importer: OSError not typed", M, "                OSError,\n", ""),
    (
        "importer: RuntimeError (and NotImplementedError) not typed",
        M,
        "                RuntimeError,  # and its subclass NotImplementedError (unknown method)\n",
        "",
    ),
    # Gate N3 part a: DFE, chain, scoring and the freeze guard
    ("dfe: forgetting factor not applied to P", D, "inv_lam = 1.0 / lam", "inv_lam = 1.0"),
    ("dfe: denominator without lambda", D, "den = lam + dot(u, pi)", "den = 1.0 + dot(u, pi)"),
    ("dfe: weight update sign", D, "w += (target - y) / den * pi", "w -= (target - y) / den * pi"),
    (
        "dfe: P update without the rank-one term",
        D,
        "p -= outer(pi, pi) / den",
        "p -= 0.0 * outer(pi, pi)",
    ),
    (
        "dfe: training switch off by one",
        D,
        "target = ref[n] if n < train else levels[idx]",
        "target = ref[n] if n <= train else levels[idx]",
    ),
    (
        "dfe: feedback holds decisions during training",
        D,
        "            u[nf] = target\n",
        "            u[nf] = levels[idx]\n",
    ),
    ("dfe: cursor ignored", D, "cursor = cfg.main_tap", "cursor = 0"),
    ("dfe: window clipped instead of wrapped", D, 'mode="wrap"', 'mode="clip"'),
    ("dfe: trace cap removed", D, "if trace > cfg.p_trace_cap:", "if False:"),
    (
        "dfe: denominator guard removed",
        D,
        "if not den > 0.0 or not math.isfinite(den):",
        "if False:",
    ),
    (
        "dfe: health check removed",
        D,
        "                _check_health(p, w, n)\n",
        "                pass\n",
    ),
    ("dfe: adaptation never stops", D, "if n < train or adapt:", "if True:"),
    ("dfe: forgetting 0 refused no more", D, "if not 0.0 < self.forgetting <= 1.0:", "if False:"),
    (
        "dfe: symmetrisation removed",
        D,
        "                p = 0.5 * (p + p.T)\n",
        "                pass\n",
    ),
    ("chain: grid multiple 20", CH, "GRID_MULTIPLE = 140", "GRID_MULTIPLE = 20"),
    ("chain: capture length 655360", CH, "CAPTURE_SYMBOLS = 655_200", "CAPTURE_SYMBOLS = 655_360"),
    ("chain: training length 4096", CH, "TRAINING_SYMBOLS = 8192", "TRAINING_SYMBOLS = 4096"),
    ("chain: roll-off 0.35", CH, "SRRC_ROLL_OFF = 0.1", "SRRC_ROLL_OFF = 0.35"),
    ("chain: DAC 6 bit", CH, "DAC_BITS = 8", "DAC_BITS = 6"),
    ("chain: symbol seed", CH, "SYMBOL_SEED = 20261101", "SYMBOL_SEED = 20261102"),
    (
        "chain: noise depends on the link",
        CH,
        "[SYMBOL_SEED, NOISE_SEED_TAG, int(baud_gbd), int(point_index)]",
        "[SYMBOL_SEED, NOISE_SEED_TAG, int(baud_gbd)]",
    ),
    ("chain: censor floor 1e-4", CH, "BER_CENSOR_FLOOR = 1e-5", "BER_CENSOR_FLOOR = 1e-4"),
    (
        "chain: thermal noise omitted",
        CH,
        "thermal = z_thermal * (thermal_a_per_rthz * math.sqrt(fs_hz / 2))",
        "thermal = 0.0 * z_thermal",
    ),
    (
        "chain: shot noise doubled",
        CH,
        "2 * ELEMENTARY_CHARGE * np.maximum(current, 0.0)",
        "4 * ELEMENTARY_CHARGE * np.maximum(current, 0.0)",
    ),
    ("chain: ceiling in amplitude dB", CH, "10 ** (ceiling_db / 10)", "10 ** (ceiling_db / 20)"),
    (
        "chain: laser power not matched",
        CH,
        "laser_w = dbm_to_watt(rop_dbm) / mean_unit if mean_unit > 0 else math.inf",
        "laser_w = dbm_to_watt(rop_dbm)",
    ),
    (
        "chain: laser limit removed",
        CH,
        "if not math.isfinite(laser_w) or laser_w > MAX_MATCHED_LASER_POWER_W:",
        "if False:",
    ),
    (
        "chain: Nyquist bin not split",
        CH,
        "            out[n_in // 2] *= 0.5\n",
        "            pass\n",
    ),
    ("chain: resample length rounds", CH, "    if out.denominator != 1:", "    if False:"),
    ("chain: DAC peak scaling removed", CH, "x / peak + 1.0", "x + 1.0"),
    (
        "chain: equaliser training mismatch accepted",
        CH,
        "if eq.samples_per_symbol != 2 or eq.training_symbols != cfg.training_symbols:",
        "if False:",
    ),
    (
        "chain: SNR in amplitude dB",
        CH,
        "10.0 * math.log10(power / error)",
        "20.0 * math.log10(power / error)",
    ),
    (
        "chain: matched filter removed",
        CH,
        "response = rrc_frequency_response(ac.size, 2, roll_off)[: ac.size // 2 + 1]",
        "response = np.ones(ac.size // 2 + 1)",
    ),
    (
        "chain: first symbols scored",
        CH,
        "scored = slice(cfg.training_symbols, None)",
        "scored = slice(0, None)",
    ),
    (
        "chain: parameter range not enforced",
        CH,
        "if not math.isfinite(value) or not spec.low <= value <= spec.high:",
        "if False:",
    ),
    (
        "freeze: symlink record accepted",
        FZ,
        "if path.is_symlink() or not path.is_file():",
        "if not path.is_file():",
    ),
    ("freeze: own hash not recomputed", FZ, 'if record["freeze_hash"] != recomputed:', "if False:"),
    (
        "freeze: duplicate keys accepted",
        FZ,
        '        record = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)\n    except',
        '        record = json.loads(raw.decode("utf-8"))\n    except',
    ),
    (
        "freeze: duplicate keys accepted in the artefact",
        FZ,
        '    artefact = json.loads(raw.decode("utf-8"), object_pairs_hook=_no_duplicates)\n    if not isinstance(artefact, dict) or set(artefact) != ARTIFACT_KEYS:',
        '    artefact = json.loads(raw.decode("utf-8"))\n    if not isinstance(artefact, dict) or set(artefact) != ARTIFACT_KEYS:',
    ),
    (
        "freeze: extra fields accepted",
        FZ,
        "or set(record) != RECORD_KEYS:",
        "or not RECORD_KEYS <= set(record):",
    ),
    ("freeze: size cap removed", FZ, "if len(raw) > MAX_RECORD_BYTES:", "if False:"),
    (
        "freeze: flags not checked",
        FZ,
        "        or not set(flags) <= set(B4_NAMES)\n",
        "",
    ),
    (
        "import: holdout guard removed",
        M,
        "    if include_holdout:\n        try:\n            require_freeze(freeze_hash)",
        "    if False:\n        try:\n            require_freeze(freeze_hash)",
    ),
    ("scoring: threshold 4e-3", SC, "BER_THRESHOLD = 3.8e-3", "BER_THRESHOLD = 4e-3"),
    (
        "scoring: a point at the threshold counts below",
        SC,
        "if b[a] >= threshold and b[c] < threshold:",
        "if b[a] > threshold and b[c] < threshold:",
    ),
    (
        "scoring: first bracket not last",
        SC,
        "for a, c in zip(unc[-2::-1], unc[:0:-1], strict=False):",
        "for a, c in zip(unc[:-1], unc[1:], strict=False):",
    ),
    ("scoring: C1 tolerance 1.5", SC, "C1_TOL_DB = 1.0", "C1_TOL_DB = 1.5"),
    (
        "scoring: C2 mean 1.6",
        SC,
        "C2_MEAN_DB, C2_MAX_DB = 1.5, 3.0",
        "C2_MEAN_DB, C2_MAX_DB = 1.6, 3.0",
    ),
    (
        "scoring: C2 max 3.1",
        SC,
        "C2_MEAN_DB, C2_MAX_DB = 1.5, 3.0",
        "C2_MEAN_DB, C2_MAX_DB = 1.5, 3.1",
    ),
    ("scoring: C3 tolerance 3.1", SC, "C3_TOL_DB = 3.0", "C3_TOL_DB = 3.1"),
    ("scoring: C3 stated 14 dB is 13", SC, "112: 14.0}", "112: 13.0}"),
    (
        "scoring: C3 BER at the limit passes",
        SC,
        "ber_ok = bool(np.all(ber_scored > BER_THRESHOLD))",
        "ber_ok = bool(np.all(ber_scored >= BER_THRESHOLD))",
    ),
    (
        "scoring: C4 fraction 0.75",
        SC,
        "C4_LOG_TOL, C4_FRACTION = 0.5, 0.8",
        "C4_LOG_TOL, C4_FRACTION = 0.5, 0.75",
    ),
    (
        "scoring: C4 log tolerance 0.6",
        SC,
        "C4_LOG_TOL, C4_FRACTION = 0.5, 0.8",
        "C4_LOG_TOL, C4_FRACTION = 0.6, 0.8",
    ),
    (
        "scoring: C4 zero errors count as within",
        SC,
        "G3)\n            continue\n",
        "G3)\n            within += 1\n            continue\n",
    ),
    (
        "scoring: C5 NANF tolerance 2.1",
        SC,
        'C5_TOL_DB = {"nanf": 2.0,',
        'C5_TOL_DB = {"nanf": 2.1,',
    ),
    ("scoring: C5 SSMF tolerance 3.1", SC, '"ssmf": 3.0, "b2b": 2.0}', '"ssmf": 3.1, "b2b": 2.0}'),
    (
        "scoring: C5 keeps 1630 and 1640",
        SC,
        "keep = wl <= 1620.0 + 1e-9",
        "keep = wl <= 1640.0 + 1e-9",
    ),
    ("scoring: C6 tolerance 2.5", SC, "C6_TOL_GHZ = 2.0", "C6_TOL_GHZ = 2.5"),
    (
        "scoring: C6 window starts at 18 GHz",
        SC,
        "C6_WINDOW_GHZ = (20.0, 32.8125)",
        "C6_WINDOW_GHZ = (18.0, 32.8125)",
    ),
    (
        "scoring: C6 median of 3",
        SC,
        "np.median(s[max(0, i - 2) : min(n, i + 3)])",
        "np.median(s[max(0, i - 1) : min(n, i + 2)])",
    ),
    ("scoring: C6 coincidence 0.8 GHz", SC, "abs(freq - c) <= 0.5", "abs(freq - c) <= 0.8"),
    ("scoring: C6 edge null accepted", SC, "edge = k in (0, window.size - 1)", "edge = False"),
    (
        "scoring: C7 capacity tolerance 12",
        SC,
        "C7_CAPACITY_TOL_GBPS, C7_RATIO_TOL = 10.0, 0.10",
        "C7_CAPACITY_TOL_GBPS, C7_RATIO_TOL = 12.0, 0.10",
    ),
    (
        "scoring: C7 ratio tolerance 0.2",
        SC,
        "C7_CAPACITY_TOL_GBPS, C7_RATIO_TOL = 10.0, 0.10",
        "C7_CAPACITY_TOL_GBPS, C7_RATIO_TOL = 10.0, 0.20",
    ),
    ("scoring: capacity over 256", SC, "fft_size: int = 512", "fft_size: int = 256"),
    (
        "scoring: loading target 4e-3",
        SC,
        "_BIT_ERROR_TARGET = BER_THRESHOLD",
        "_BIT_ERROR_TARGET = 4e-3",
    ),
    (
        "scoring: C8 SSMF tolerance 3.1",
        SC,
        'C8_TOL_DB = {"nanf": 2.0, "ssmf": 3.0}',
        'C8_TOL_DB = {"nanf": 2.0, "ssmf": 3.1}',
    ),
    (
        "scoring: discriminating at equality",
        SC,
        "return d is not None and math.isfinite(d) and d > tolerance",
        "return d is not None and math.isfinite(d) and d >= tolerance",
    ),
    (
        "scoring: B2B gate mean 1.1",
        SC,
        "B2B_GATE_MEAN_DB, B2B_GATE_MAX_DB, B2B_GATE_CROSSING_DB = 1.0, 2.0, 0.5",
        "B2B_GATE_MEAN_DB, B2B_GATE_MAX_DB, B2B_GATE_CROSSING_DB = 1.1, 2.0, 0.5",
    ),
    (
        "scoring: B2B gate crossing 1.0",
        SC,
        "B2B_GATE_MEAN_DB, B2B_GATE_MAX_DB, B2B_GATE_CROSSING_DB = 1.0, 2.0, 0.5",
        "B2B_GATE_MEAN_DB, B2B_GATE_MAX_DB, B2B_GATE_CROSSING_DB = 1.0, 2.0, 1.0",
    ),
    (
        "scoring: B2B copy extrapolates",
        SC,
        "ok = (q >= r[0]) & (q <= r[-1])\n        snr_out[ok] = np.interp(q[ok], r, snr)",
        "ok = q == q\n        snr_out[ok] = np.interp(q[ok], r, snr)",
    ),
    (
        "scoring: B2B copy uses censored BER nodes",
        SC,
        "nodes = ~is_censored(ber, published=True)  # inf, negative or above 1 raises",
        "nodes = np.isfinite(ber)",
    ),
    (
        "scoring: published bound read as a point",
        SC,
        'if published.kind == "point":\n',
        "if False:\n",
    ),
    (
        "scoring: identifiability ratio 1e-2",
        SC,
        "ratio: float = 1e-3,\n) -> IdentifiabilityResult:",
        "ratio: float = 1e-2,\n) -> IdentifiabilityResult:",
    ),
    (
        "scoring: flagged parameter set to the optimum not the prior",
        SC,
        "result_vector[specs[i].name] = specs[i].prior",
        "result_vector[specs[i].name] = float(optimum[specs[i].name])",
    ),
    (
        "scoring: ties pick the highest index",
        SC,
        "flagged.append(next(i for i in free if vec[i] >= top * (1 - 1e-12)))",
        "flagged.append(max(i for i in free if vec[i] >= top * (1 - 1e-12)))",
    ),
    (
        "scoring: a verdict ignores poor B2B calibration",
        SC,
        "        if scores[rate].b2b_poor\n        or not (scores[rate].c1_discriminating",
        "        if not (scores[rate].c1_discriminating",
    ),
    # N3 part a fix round: the 14 real survivors of the first review (finding 7)
    (
        "chain: Tx filter dropped",
        CH,
        "    if tx_bandwidth_hz is not None:\n        drive = lowpass(drive, fs_hz, tx_bandwidth_hz)\n",
        "    if False:\n        drive = lowpass(drive, fs_hz, tx_bandwidth_hz)\n",
    ),
    (
        "chain: Tx bandwidth not passed to the analogue path",
        CH,
        "tx_bandwidth_hz=params.tx_bandwidth_ghz * 1e9,",
        "tx_bandwidth_hz=None,",
    ),
    (
        "chain: matched filter call removed from the receiver",
        CH,
        "matched = matched_filter_t2(ac / rms, cfg.roll_off)",
        "matched = ac / rms",
    ),
    (
        "chain: one-sample T/2 timing shift",
        CH,
        "matched = matched_filter_t2(ac / rms, cfg.roll_off)",
        "matched = np.roll(matched_filter_t2(ac / rms, cfg.roll_off), 1)",
    ),
    (
        "chain: noise not Rx filtered",
        CH,
        "        if noise is not None:\n            noise = lowpass(noise, fs_hz, bandwidth)\n",
        "        if False:\n            noise = lowpass(noise, fs_hz, bandwidth)\n",
    ),
    (
        "chain: noise draw order, thermal before shot",
        CH,
        "    z_shot = rng.standard_normal(n_a) if noise else None\n"
        "    z_thermal = rng.standard_normal(n_a) if noise else None\n",
        "    z_thermal = rng.standard_normal(n_a) if noise else None\n"
        "    z_shot = rng.standard_normal(n_a) if noise else None\n",
    ),
    (
        "chain: ceiling noise drawn before the analogue noise",
        CH,
        "    z_shot = rng.standard_normal(n_a) if noise else None\n"
        "    z_thermal = rng.standard_normal(n_a) if noise else None\n"
        '    z_ceiling = rng.standard_normal(counts["scope"]) if noise else None\n',
        '    z_ceiling = rng.standard_normal(counts["scope"]) if noise else None\n'
        "    z_shot = rng.standard_normal(n_a) if noise else None\n"
        "    z_thermal = rng.standard_normal(n_a) if noise else None\n",
    ),
    ("chain: mean not removed", CH, "ac = two_sps - two_sps.mean()", "ac = two_sps"),
    ("chain: DAC steps 2**bits", CH, "steps = 2**bits - 1", "steps = 2**bits"),
    (
        "chain: DAC resolution not passed",
        CH,
        "dac = dac_quantise(awg, cfg.dac_bits)",
        "dac = dac_quantise(awg, 6)",
    ),
    (
        "dfe: default cap 1e8 in the config",
        D,
        "    p_trace_cap: float = PINNED_P_TRACE_CAP\n",
        "    p_trace_cap: float = 1e8\n",
    ),
    ("dfe: pinned cap 1e8", D, "PINNED_P_TRACE_CAP = 1e10", "PINNED_P_TRACE_CAP = 1e8"),
    (
        "chain: BER floor boundary, 1e-5 censored",
        CH,
        "        if ber < BER_CENSOR_FLOOR:\n",
        "        if ber <= BER_CENSOR_FLOOR:\n",
    ),
    (
        "scoring: C4 ROP cap strict",
        SC,
        "    keep = r <= ROP_CAP_DBM\n    locked = ",
        "    keep = r < ROP_CAP_DBM\n    locked = ",
    ),
    (
        "scoring: C7 ratio boundary strict",
        SC,
        "and er <= C7_RATIO_TOL",
        "and er < C7_RATIO_TOL",
    ),
    (
        "scoring: C7 capacity boundary strict",
        SC,
        "ok = en <= C7_CAPACITY_TOL_GBPS and es <= C7_CAPACITY_TOL_GBPS",
        "ok = en < C7_CAPACITY_TOL_GBPS and es <= C7_CAPACITY_TOL_GBPS",
    ),
    (
        "scoring: simulated left bound read at its lower end",
        SC,
        'x = simulated.hi if simulated.kind == "left" else simulated.lo',
        "x = simulated.lo",
    ),
    (
        "freeze: record size limit, at equals refused",
        FZ,
        "    if len(raw) > MAX_RECORD_BYTES:\n",
        "    if len(raw) >= MAX_RECORD_BYTES:\n",
    ),
    (
        "freeze: record size limit raised",
        FZ,
        "MAX_RECORD_BYTES = 65_536",
        "MAX_RECORD_BYTES = 1_000_000",
    ),
    (
        "freeze: artefact size limit removed",
        FZ,
        '    if len(raw) > MAX_ARTIFACT_BYTES:\n        raise _refuse("the calibration artefact is too large")\n    if hashlib',
        "    if hashlib",
    ),
    (
        "importer: include_holdout is True",
        M,
        "    if include_holdout:\n        try:\n            require_freeze(freeze_hash)",
        "    if include_holdout is True:\n        try:\n            require_freeze(freeze_hash)",
    ),
    # N3 part a fix round: guards of decisions 1 to 6 and the minors
    (
        "chain: a cap that acts does not raise",
        CH,
        "        if not diagnostic:\n            raise TraceCapActedError(",
        "        if False:\n            raise TraceCapActedError(",
    ),
    (
        "chain: a cap that acts is not recorded as a reason",
        CH,
        "    if result.n_trace_caps > 0:\n        reasons.append(",
        "    if False:\n        reasons.append(",
    ),
    (
        "chain: an overridden equaliser is scorable",
        CH,
        "    if eq != declared_eq:\n        reasons.append(",
        "    if False:\n        reasons.append(",
    ),
    (
        "chain: an overridden configuration is scorable",
        CH,
        "    if cfg != ChainConfig():\n        reasons.append(",
        "    if False:\n        reasons.append(",
    ),
    (
        "chain: a noise-free run is scorable",
        CH,
        "    if not noise:\n        reasons.append(",
        "    if False:\n        reasons.append(",
    ),
    (
        "chain: a diagnostic run is scorable",
        CH,
        "    if diagnostic:\n        reasons.append(",
        "    if False:\n        reasons.append(",
    ),
    (
        "chain: the declared equaliser uses the config default not the pin",
        CH,
        "training_symbols=cfg.training_symbols, p_trace_cap=PINNED_P_TRACE_CAP",
        "training_symbols=cfg.training_symbols, p_trace_cap=1e4",
    ),
    (
        "chain: require_scorable accepts an unscorable point",
        CH,
        "        if not isinstance(point, PointResult) or not point.scorable:",
        "        if not isinstance(point, PointResult):",
    ),
    (
        "chain: a freeze is not looked for",
        CH,
        "    if nanf_freeze.freeze_record_present() and not diagnostic:",
        "    if False and not diagnostic:",
    ),
    (
        "chain: overrides allowed after a freeze",
        CH,
        "        if reasons:\n            raise FrozenOverrideError(",
        "        if False:\n            raise FrozenOverrideError(",
    ),
    (
        "chain: parameters other than the record allowed after a freeze",
        CH,
        "        if params is not None and params != record.parameters:",
        "        if False:",
    ),
    (
        "chain: the record vector is not used after a freeze",
        CH,
        "        params = record.parameters\n",
        "",
    ),
    (
        "chain: the record is not verified after a freeze",
        CH,
        "record: FreezeRecord = nanf_freeze.load_freeze_record()",
        "record: FreezeRecord = nanf_freeze.FreezeRecord(\n"
        '            "", "", params or TxRxParameters(), (), "", "", "", "", ""\n'
        "        )",
    ),
    (
        "chain: F2 string for BER below 1e-4 removed",
        CH,
        "        if ber < BER_REPORT_FLOOR:\n",
        "        if False:\n",
    ),
    (
        "freeze: second gate for the real workbook removed",
        M,
        "    if include_holdout and digest == NANF_WORKBOOK_SHA256:",
        "    if False:",
    ),
    (
        "freeze: the real workbook is unlocked by the patched record path",
        M,
        "require_freeze(freeze_hash, record_path=COMMITTED_RECORD_PATH)",
        "require_freeze(freeze_hash)",
    ),
    (
        "freeze: artefact not required to be tracked",
        FZ,
        "    if tracked.returncode != 0 or head_blob is None:",
        "    if head_blob is None:",
    ),
    (
        "freeze: uncommitted changes to the artefact allowed",
        FZ,
        '    if head_blob != ref["sha256"]:',
        "    if False:",
    ),
    (
        "freeze: the named commit need not hold the artefact",
        FZ,
        '    if commit_blob != ref["sha256"]:',
        "    if False:",
    ),
    (
        "freeze: the commit need not be an ancestor of HEAD",
        FZ,
        "    if ancestor.returncode != 0:",
        "    if False:",
    ),
    (
        "freeze: artefact SHA-256 not compared",
        FZ,
        '    if hashlib.sha256(raw).hexdigest() != ref["sha256"]:',
        "    if False:",
    ),
    (
        "freeze: an absent artefact is not refused",
        FZ,
        '    if file.is_symlink() or not file.is_file():\n        raise _refuse("the calibration artefact is absent")\n    raw = file.read_bytes()\n    if len(raw) > MAX_ARTIFACT_BYTES:',
        "    raw = file.read_bytes()\n    if len(raw) > MAX_ARTIFACT_BYTES:",
    ),
    (
        "freeze: default vector with no fit result accepted",
        FZ,
        "    if not isinstance(fit, dict) or not fit:",
        "    if not isinstance(fit, dict):",
    ),
    (
        "freeze: fit result contents not checked",
        FZ,
        "    if set(fit) != FIT_RESULT_KEYS:",
        "    if False:",
    ),
    (
        "freeze: fit cost may be negative",
        FZ,
        "        or cost <= 0\n",
        "",
    ),
    (
        "freeze: record vector need not be the artefact vector",
        FZ,
        '    if TxRxParameters.from_mapping(artefact["parameters"]) != parameters:',
        "    if False:",
    ),
    (
        "freeze: record flags need not be the artefact flags",
        FZ,
        '    if _check_flags(artefact["unidentifiable"]) != flags:',
        "    if False:",
    ),
    (
        "freeze: artefact partition not compared",
        FZ,
        '    if artefact["calibration_partition_sha256"] != partition:',
        "    if False:",
    ),
    (
        "freeze: flagged parameters need not be at their priors",
        FZ,
        "        if values[name] != _prior_of(name):",
        "        if False:",
    ),
    (
        "freeze: flagged priors not checked when loading",
        FZ,
        '    flags = _check_flags(record["unidentifiable"])\n    _check_priors(parameters, flags)\n',
        '    flags = _check_flags(record["unidentifiable"])\n',
    ),
    (
        "freeze: current partition not compared",
        FZ,
        '    if record["calibration_partition_sha256"] != current_partition():',
        "    if False:",
    ),
    (
        "freeze: artefact path may leave docs/benchmarks",
        FZ,
        "        or not path.startswith(CALIBRATION_ARTIFACT_DIR)\n",
        "",
    ),
    (
        "freeze: artefact path may climb with ..",
        FZ,
        '        or ".." in pure.parts\n',
        "",
    ),
    (
        "freeze: huge integers raise a raw error",
        FZ,
        "_MALFORMED = (ValueError, TypeError, OverflowError, RecursionError, KeyError, AttributeError)",
        "_MALFORMED = (ValueError, TypeError, KeyError, AttributeError)",
    ),
    (
        "freeze: deep nesting raises a raw error",
        FZ,
        "_MALFORMED = (ValueError, TypeError, OverflowError, RecursionError, KeyError, AttributeError)",
        "_MALFORMED = (ValueError, TypeError, OverflowError, KeyError, AttributeError)",
    ),
    (
        "freeze: deep nesting in the JSON parse not typed",
        FZ,
        '    except (ValueError, UnicodeDecodeError, RecursionError):\n        raise _refuse("the freeze record is not valid JSON',
        '    except (ValueError, UnicodeDecodeError):\n        raise _refuse("the freeze record is not valid JSON',
    ),
    (
        "freeze: Git failure is not a refusal",
        FZ,
        '    except (OSError, subprocess.SubprocessError):\n        raise _refuse("Git could not be run',
        '    except subprocess.SubprocessError:\n        raise _refuse("Git could not be run',
    ),
    (
        "freeze: the identity ignores function-level imports",
        FZ,
        "    for node in ast.walk(tree):",
        "    for node in tree.body:",
    ),
    (
        "freeze: the identity ignores from-import module names",
        FZ,
        '                found.update(f"{module}.{alias.name}" for alias in node.names)',
        "                pass",
    ),
    (
        "freeze: the identity omits parent packages",
        FZ,
        '        queue.extend(".".join(parts[:i]) for i in range(1, len(parts)))',
        "        pass",
    ),
    (
        "freeze: the identity omits the lock file",
        FZ,
        'CONFIG_FILES = ("pyproject.toml", "uv.lock")',
        'CONFIG_FILES = ("pyproject.toml",)',
    ),
    (
        "freeze: the identity omits the project configuration",
        FZ,
        'CONFIG_FILES = ("pyproject.toml", "uv.lock")',
        'CONFIG_FILES = ("uv.lock",)',
    ),
    (
        "freeze: the identity omits the benchmark helpers",
        FZ,
        '    "opticps.measurement.nanf_benchmark",\n',
        "",
    ),
    (
        "freeze: the identity hashes paths not contents",
        FZ,
        'name.encode() + b"\\x00" + _sha256(base / name).encode() + b"\\n"',
        'name.encode() + b"\\x00" + name.encode() + b"\\n"',
    ),
    (
        "freeze: the record vector is not part of the hash",
        FZ,
        '        "parameters": dict(parameters),\n        "unidentifiable": list(unidentifiable),\n        "calibration": dict(calibration),',
        '        "unidentifiable": list(unidentifiable),\n        "calibration": dict(calibration),',
    ),
    (
        "freeze: the calibration reference is not part of the hash",
        FZ,
        '        "calibration": dict(calibration),\n',
        "",
    ),
    (
        "freeze: the partition is not part of the hash",
        FZ,
        '        "calibration_partition_sha256": partition,\n    }\n    return hashlib',
        "    }\n    return hashlib",
    ),
    (
        "freeze: the caller's hash is not compared",
        FZ,
        "    if freeze_hash != record.freeze_hash:",
        "    if False:",
    ),
    (
        "freeze: a record is accepted without comparing its own hash",
        FZ,
        '    if record["freeze_hash"] != recomputed:',
        "    if False:",
    ),
    (
        "freeze: plan pin not compared",
        FZ,
        '    if record["plan_sha256"] != plan_sha256(plan_path):',
        "    if False:",
    ),
    (
        "freeze: code identity not compared",
        FZ,
        '    if record["code_identity"] != code_identity(base):',
        "    if False:",
    ),
    (
        "scoring: invalid simulated BER (NaN, inf) read as censored",
        SC,
        "    if (nan.any() and not published) or np.any(np.isinf(b)):\n",
        "    if np.any(np.isinf(b)):\n",
    ),
    (
        "scoring: negative or above-one BER accepted",
        SC,
        "    if np.any(finite < 0) or np.any(finite > 1):\n",
        "    if False:\n",
    ),
    (
        "scoring: an invalid curve is not an invalid crossing",
        SC,
        '        return Crossing("invalid", math.nan, math.nan)\n    unc =',
        '        return Crossing("left", -math.inf, float(r[0]))\n    unc =',
    ),
    (
        "scoring: an invalid crossing is scored",
        SC,
        '    if published.kind == "invalid" or simulated.kind == "invalid":',
        "    if False:",
    ),
    (
        "scoring: Crossing kind not validated",
        SC,
        "        if self.kind not in _KINDS:",
        "        if False:",
    ),
    (
        "scoring: Crossing point at infinity allowed",
        SC,
        "            ok = math.isfinite(lo) and lo == hi",
        "            ok = lo == hi",
    ),
    (
        "scoring: C4 simulated censored non-zero BER counted within",
        SC,
        "        if sim_censored[i]:",
        "        if s[i] == 0.0:",
    ),
    (
        "scoring: C4 NaN ROP not refused",
        SC,
        '    if not np.all(np.isfinite(r)):\n        raise ValueError("the ROP axis must be finite (a NaN',
        '    if False:\n        raise ValueError("the ROP axis must be finite (a NaN',
    ),
    (
        "scoring: C4 published BER not validated",
        SC,
        "    cens = is_censored(p, published=True)\n    within = 0",
        "    cens = np.asarray(~np.isfinite(p) | (p < BER_CENSOR_FLOOR))\n    within = 0",
    ),
    (
        "scoring: C3 BER range not checked",
        SC,
        "np.any(ber_scored < 0) or np.any(ber_scored > 1):",
        "False:",
    ),
    (
        "scoring: C3 BER at the threshold passes",
        SC,
        "ber_ok = bool(np.all(ber_scored > BER_THRESHOLD))",
        "ber_ok = bool(np.all(ber_scored >= BER_THRESHOLD))",
    ),
    (
        "scoring: C5 files any wavelength above 1620 apart",
        SC,
        "    if not np.all(np.isfinite(wl)) or any(",
        "    if False and any(",
    ),
    (
        "scoring: C7 any number of subcarriers",
        SC,
        "    if b.size != C7_SUBCARRIERS or np.any(b < 0):",
        "    if b.size == 0 or np.any(b < 0):",
    ),
    (
        "scoring: RateScores accepts truthy junk",
        SC,
        "            if not isinstance(getattr(self, name), bool | np.bool_):",
        "            if False:",
    ),
    (
        "scoring: unbracketed copy point read as a censored point",
        SC,
        "        ok = ~np.isnan(self.ber)\n        return q[ok], self.ber[ok]",
        "        return q, self.ber",
    ),
    (
        "scoring: an empty copy is not invalid",
        SC,
        '    if q.size == 0:\n        return Crossing("invalid", math.nan, math.nan)\n    return c1_crossing(q, b)',
        "    return c1_crossing(q, b)",
    ),
    (
        "scoring: B2B copy accepts an invalid BER",
        SC,
        "    nodes = ~is_censored(ber, published=True)  # inf, negative or above 1 raises",
        "    nodes = ~np.isnan(ber)",
    ),
    (
        "scoring: B2B copy accepts non-finite SNR",
        SC,
        "    if not np.all(np.isfinite(snr)) or not np.all(np.isfinite(q)):",
        "    if False:",
    ),
    # N3 part a, Amendment 7: lost-lock runs
    (
        "chain: lost outcome, a cap that acts is not caught",
        CH,
        "    except TraceCapActedError as err:\n        return PointOutcome",
        "    except ZeroDivisionError as err:\n        return PointOutcome",
    ),
    (
        "chain: lost outcome, an instability is not caught",
        CH,
        "    except RlsInstabilityError as err:\n        return PointOutcome",
        "    except ZeroDivisionError as err:\n        return PointOutcome",
    ),
    ("chain: lost outcome without a reason", CH, 'f"trace cap acted: {err}")', '"")'),
    ("chain: lost outcome instability reason dropped", CH, 'f"RlsInstabilityError: {err}")', '"")'),
    (
        "chain: lost report omits lost points",
        CH,
        "for o in outcomes if o.lost]",
        "for o in outcomes if False]",
    ),
    (
        "chain: a lost point is stored as BER zero",
        CH,
        "math.nan if o.result is None else o.result.ber",
        "0.0 if o.result is None else o.result.ber",
    ),
    (
        "chain: a lost point is stored as SNR zero",
        CH,
        "math.nan if o.result is None else o.result.snr_db",
        "0.0 if o.result is None else o.result.snr_db",
    ),
    (
        "chain: a lost point is marked valid",
        CH,
        "valid = np.array([not o.lost for o in outcomes], dtype=bool)",
        "valid = np.array([True for o in outcomes], dtype=bool)",
    ),
    (
        "scoring: a lost point above the locked run is allowed",
        SC,
        "        if not locked[-1]:\n",
        "        if False:\n",
    ),
    (
        "scoring: every point lost is not invalid",
        SC,
        "        if not locked.any():\n",
        "        if False:\n",
    ),
    (
        "scoring: the crossing uses the lowest locked run",
        SC,
        "first = int(np.flatnonzero(~locked)[-1]) + 1",
        "first = int(np.flatnonzero(~locked)[0]) + 1",
    ),
    (
        "scoring: a bound among locked points is accepted",
        SC,
        '        if inner.kind != "point":\n            why',
        '        if inner.kind == "invalid":\n            why',
    ),
    (
        "scoring: lost points not counted in the crossing",
        SC,
        'return Crossing("point", inner.lo, inner.hi, n_lost, "locked run',
        'return Crossing("point", inner.lo, inner.hi, 0, "locked run',
    ),
    (
        "scoring: validity mask not checked for dtype",
        SC,
        "    if mask.dtype != np.bool_ or mask.shape != (n,):",
        "    if mask.shape != (n,):",
    ),
    (
        "scoring: validity mask not checked for length",
        SC,
        "    if mask.dtype != np.bool_ or mask.shape != (n,):",
        "    if mask.dtype != np.bool_:",
    ),
    ("scoring: C2 ignores a lost point", SC, "    if not ok_pts.all():\n", "    if False:\n"),
    (
        "scoring: C5 ignores a lost wavelength",
        SC,
        "    if not locked[keep].all():\n",
        "    if False:\n",
    ),
    (
        "scoring: C3 ignores a lost point",
        SC,
        "    if not (s_okc.all() and n_okc[inside].all()):",
        "    if False:",
    ),
    (
        "scoring: C3 ignores a lost SSMF point",
        SC,
        "    if not (s_okc.all() and n_okc[inside].all()):",
        "    if not n_okc[inside].all():",
    ),
    (
        "scoring: C4 ignores a lost point",
        SC,
        "    p, s = p[keep], s[keep]\n    if not locked.all():",
        "    p, s = p[keep], s[keep]\n    if False:",
    ),
    (
        "scoring: the B2B gate ignores a lost point",
        SC,
        "    if not locked.all():  # a lost-lock point of the calibration grid",
        "    if False:  # a lost-lock point of the calibration grid",
    ),
    (
        "scoring: a lost evaluation does not get the worst case",
        SC,
        "value, lost = WORST_CASE_OBJECTIVE, err.lost",
        "value, lost = 1e9, err.lost",
    ),
    (
        "scoring: a lost evaluation is not counted",
        SC,
        "value, lost = WORST_CASE_OBJECTIVE, err.lost",
        "value, lost = WORST_CASE_OBJECTIVE, ()",
    ),
    (
        "scoring: a non-finite objective is accepted",
        SC,
        "    if not lost and not math.isfinite(value):",
        "    if False:",
    ),
    (
        "scoring: a lost evaluation can be selected",
        SC,
        "clean = [e for e in log.evaluations if not e.lost and math.isfinite(e.objective)]",
        "clean = [e for e in log.evaluations if math.isfinite(e.objective)]",
    ),
    (
        "scoring: an infinite evaluation can be selected",
        SC,
        "clean = [e for e in log.evaluations if not e.lost and math.isfinite(e.objective)]",
        "clean = [e for e in log.evaluations if not e.lost]",
    ),
    (
        "scoring: no clean evaluation is not an error",
        SC,
        '        raise NoValidFitError("every evaluation lost lock at a needed point")',
        "        return log.evaluations[0]",
    ),
    (
        "scoring: a chosen fit with lost points is valid",
        SC,
        "    if chosen.lost or not math.isfinite(chosen.objective):",
        "    if not math.isfinite(chosen.objective):",
    ),
    (
        "scoring: a chosen fit with an infinite objective is valid",
        SC,
        "    if chosen.lost or not math.isfinite(chosen.objective):",
        "    if chosen.lost:",
    ),
    (
        "scoring: the evaluation log omits worst-case lines",
        SC,
        "            if e.lost\n        ]",
        "            if False\n        ]",
    ),
    (
        "scoring: the worst-case count is wrong",
        SC,
        "return sum(1 for e in self.evaluations if e.lost)",
        "return 0",
    ),
    (
        "scoring: identifiability lets a worst-case evaluation through",
        SC,
        "        except EvaluationLostLockError as err:\n            raise IdentifiabilityUndefinedError(",
        "        except ZeroDivisionError as err:\n            raise IdentifiabilityUndefinedError(",
    ),
    # N3 part a, Amendment 8: second review
    (
        "chain: an outcome may hold an unscorable result",
        CH,
        "        if self.result is not None and (",
        "        if False and (",
    ),
    (
        "chain: the record hash is not stored on the result",
        CH,
        "        frozen_record_hash=frozen_hash,",
        "        frozen_record_hash=None,",
    ),
    (
        "chain: a link outside the declared table is scorable",
        CH,
        "        if spec != LinkSpec() and spec not in DECLARED_LINKS.values():",
        "        if False:",
    ),
    (
        "chain: back-to-back needs a declared link",
        CH,
        "        if spec != LinkSpec() and spec not in DECLARED_LINKS.values():",
        "        if spec not in DECLARED_LINKS.values():",
    ),
    (
        "chain: a point index outside the declared set is scorable",
        CH,
        "        if point_index not in DECLARED_POINT_INDICES:",
        "        if False:",
    ),
    (
        "chain: run_point catches every arithmetic error",
        CH,
        "    except RlsInstabilityError as err:",
        "    except ArithmeticError as err:",
    ),
    (
        "chain: one cap action is not an invalid run",
        CH,
        "    if result.n_trace_caps > 0:\n        reasons.append(",
        "    if result.n_trace_caps > 1:\n        reasons.append(",
    ),
    (
        "freeze: a fit that did not converge is accepted",
        FZ,
        '        or fit["converged"] is not True',
        '        or not isinstance(fit["converged"], bool)',
    ),
    (
        "freeze: one evaluation is a fit",
        FZ,
        "MIN_EVALUATIONS = 1 + len(B4_NAMES)",
        "MIN_EVALUATIONS = 1",
    ),
    (
        "freeze: any point count is a calibration grid",
        FZ,
        "        or not MIN_CALIBRATION_POINTS <= n_pts <= MAX_CALIBRATION_POINTS",
        "        or n_pts < 0",
    ),
    (
        "freeze: no upper bound on the calibration points",
        FZ,
        "        or not MIN_CALIBRATION_POINTS <= n_pts <= MAX_CALIBRATION_POINTS",
        "        or not MIN_CALIBRATION_POINTS <= n_pts",
    ),
    (
        "freeze: no lower bound on the calibration points",
        FZ,
        "        or not MIN_CALIBRATION_POINTS <= n_pts <= MAX_CALIBRATION_POINTS",
        "        or not n_pts <= MAX_CALIBRATION_POINTS",
    ),
    (
        "freeze: the checks record is not required",
        FZ,
        "    if not isinstance(checks, dict) or set(checks) != CHECKS_KEYS:",
        "    if not isinstance(checks, dict):",
    ),
    (
        "freeze: the checks record is not called",
        FZ,
        '    _check_checks(artefact["checks"], flags)\n',
        "    pass\n",
    ),
    (
        "freeze: check_chosen_fit not recorded as run",
        FZ,
        '    if checks["chosen_fit_checked"] is not True or isinstance(lost, bool) or lost != 0:',
        "    if lost != 0:",
    ),
    (
        "freeze: lost points in the grid not refused",
        FZ,
        '    if checks["chosen_fit_checked"] is not True or isinstance(lost, bool) or lost != 0:',
        '    if checks["chosen_fit_checked"] is not True:',
    ),
    (
        "freeze: eigenvalues need not ascend",
        FZ,
        "    ok = ok and all(a <= b for a, b in zip(eig, eig[1:], strict=False))",
        "    ok = ok",
    ),
    (
        "freeze: flags need not match the eigenvalues",
        FZ,
        "    if n_low != len(flags):",
        "    if False:",
    ),
    (
        "freeze: identifiability ratio 1e-2",
        FZ,
        "IDENTIFIABILITY_RATIO = 1e-3",
        "IDENTIFIABILITY_RATIO = 1e-2",
    ),
    (
        "freeze: grafts are accepted",
        FZ,
        "        if gitdir.returncode != 0 or grafts.exists():",
        "        if gitdir.returncode != 0:",
    ),
    (
        "freeze: replace refs are honoured",
        FZ,
        '["git", "--no-replace-objects", "-C", str(root), *args]',
        '["git", "-C", str(root), *args]',
    ),
    (
        "freeze: fibre profiles not in the identity",
        FZ,
        'CONFIG_GLOBS = ("configs/fibers/*.yaml",)',
        "CONFIG_GLOBS = ()",
    ),
    (
        "freeze: relative import level off by one",
        FZ,
        "anchor = anchor[: len(anchor) - (node.level - 1)]",
        "anchor = anchor[: len(anchor) - node.level]",
    ),
    (
        "freeze: relative import level off by one, other side",
        FZ,
        "anchor = anchor[: len(anchor) - (node.level - 1)]",
        "anchor = anchor[: len(anchor) - (node.level - 2)]",
    ),
    (
        "importer: Fig.11 not excluded from scoring",
        M,
        'SCORING_EXCLUDED_SHEETS: frozenset[str] = frozenset({"Fig.11"})',
        "SCORING_EXCLUDED_SHEETS: frozenset[str] = frozenset()",
    ),
    (
        "importer: a Fig.11 key is not refused",
        M,
        '        if key.split("/", 1)[0] in SCORING_EXCLUDED_SHEETS:',
        "        if False:",
    ),
    (
        "importer: Fig.11 returned with the holdout",
        M,
        "        and s.sheet not in SCORING_EXCLUDED_SHEETS\n",
        "\n",
    ),
    (
        "scoring: C3 counts a NANF point outside the ROP set",
        SC,
        "    if not (s_okc.all() and n_okc[inside].all()):",
        "    if not (s_okc.all() and n_okc.all()):",
    ),
    (
        "scoring: a published curve may carry a validity mask",
        SC,
        "    if published and valid is not None:",
        "    if False:",
    ),
    (
        "scoring: C4 fails on a lost point outside the scored set",
        SC,
        "    locked = _as_valid(simulated_valid, r.size)[keep]",
        "    locked = _as_valid(simulated_valid, r.size)",
    ),
    (
        "scoring: C5 fails on a lost wavelength reported apart",
        SC,
        "    if not locked[keep].all():",
        "    if not locked.all():",
    ),
    # N3 part a, Amendment 9: closing review
    (
        "chain: curve_arrays accepts an unscorable calibration result",
        CH,
        "    results = [o.result for o in outcomes if o.result is not None]\n    require_scorable(results)\n",
        "    results = [o.result for o in outcomes if o.result is not None]\n",
    ),
    (
        "chain: calibration arrays allowed while a record exists",
        CH,
        '        if nanf_freeze.freeze_record_present():\n            raise NotScorableError("calibration arrays cannot be built',
        '        if False:\n            raise NotScorableError("calibration arrays cannot be built',
    ),
    (
        "chain: calibration arrays need not be back-to-back",
        CH,
        "            if r.link != LinkSpec() or r.frozen_record_hash is not None:",
        "            if r.frozen_record_hash is not None:",
    ),
    (
        "chain: calibration arrays may carry a record hash",
        CH,
        "            if r.link != LinkSpec() or r.frozen_record_hash is not None:",
        "            if r.link != LinkSpec():",
    ),
    (
        "chain: calibration points need not be declared",
        CH,
        "            if point not in DECLARED_CALIBRATION_POINTS:",
        "            if False:",
    ),
    (
        "chain: an outcome may name another ROP than its result",
        CH,
        "        if o.result is not None and o.result.rop_dbm != o.rop_dbm:",
        "        if False:",
    ),
    (
        "chain: scoring trusts the hash on the result",
        CH,
        "            record_hash = nanf_freeze.load_freeze_record().freeze_hash",
        '            record_hash = (results[0].frozen_record_hash if results else None) or ""',
    ),
    (
        "chain: a stale or deleted record is not a refusal",
        CH,
        "        except nanf_freeze.HoldoutLockedError as err:",
        "        except ZeroDivisionError as err:",
    ),
    (
        "chain: the record hash is only checked for presence",
        CH,
        "        if frozen_hash is not None and point.frozen_record_hash != frozen_hash:",
        "        if frozen_hash is not None and point.frozen_record_hash is None:",
    ),
    (
        "chain: the result does not keep its rate",
        CH,
        "        rate_gbps=rate_gbps,",
        "        rate_gbps=0,",
    ),
    (
        "chain: the result does not keep its point index",
        CH,
        "        point_index=point_index,",
        "        point_index=0,",
    ),
    (
        "chain: the result does not keep its link",
        CH,
        "        point_index=point_index,\n        link=spec,\n",
        "        point_index=point_index,\n        link=LinkSpec(),\n",
    ),
    (
        "chain: run_point does not refuse a non-pinned run",
        CH,
        "    if refused:  # refused before any run",
        "    if False:  # refused before any run",
    ),
    (
        "chain: a non-pinned configuration is not refused",
        CH,
        "    if cfg is not None and cfg != ChainConfig():",
        "    if False:",
    ),
    (
        "chain: only the cap of the equaliser is checked",
        CH,
        "    if eq is not None and eq != declared:",
        "    if eq is not None and eq.p_trace_cap != PINNED_P_TRACE_CAP:",
    ),
    (
        "chain: a non-pinned equaliser is not refused",
        CH,
        "    if eq is not None and eq != declared:",
        "    if False:",
    ),
    (
        "chain: a noise-off run is not refused",
        CH,
        '    if kwargs.get("noise", True) is not True:',
        "    if False:",
    ),
    (
        "chain: a diagnostic run is not refused",
        CH,
        '    if kwargs.get("diagnostic", False) is not False:',
        "    if False:",
    ),
    (
        "chain: an unknown argument is not refused",
        CH,
        '    reasons = [f"unknown argument {k}" for k in kwargs if k not in known]',
        "    reasons = []",
    ),
    (
        "chain: an outcome error text drops the reasons",
        CH,
        '                ", ".join(self.result.unscorable_reasons)',
        '                "unscorable"',
    ),
    (
        "freeze: grafts are read from the worktree git dir",
        FZ,
        'gitdir = _git(root, "rev-parse", "--path-format=absolute", "--git-common-dir")',
        'gitdir = _git(root, "rev-parse", "--absolute-git-dir")',
    ),
    (
        "scoring: no round-off tolerance for the eigenvalues",
        SC,
        "    floor = -EIGENVALUE_ROUNDOFF_RELATIVE * max(largest, 0.0)",
        "    floor = 0.0",
    ),
    (
        "scoring: any negative eigenvalue is floored",
        SC,
        "    floor = -EIGENVALUE_ROUNDOFF_RELATIVE * max(largest, 0.0)",
        "    floor = -1.0 * max(largest, 0.0)",
    ),
    (
        "scoring: tiny negative eigenvalues are kept",
        SC,
        "    values = np.where(values < 0.0, 0.0, values)",
        "    values = values",
    ),
    (
        "scoring: round-off tolerance 1e-3",
        SC,
        "EIGENVALUE_ROUNDOFF_RELATIVE = 1e-10",
        "EIGENVALUE_ROUNDOFF_RELATIVE = 1e-3",
    ),
    (
        "scoring: round-off tolerance 1e-13",
        SC,
        "EIGENVALUE_ROUNDOFF_RELATIVE = 1e-10",
        "EIGENVALUE_ROUNDOFF_RELATIVE = 1e-13",
    ),
    (
        "scoring: the B2B gate drops no unscored points",
        SC,
        '    _, s, p, locked = _scored(_arr(rop, "rop"), s, p, locked)',
        "    pass",
    ),
    (
        "scoring: the B2B gate rop is optional",
        SC,
        "    rop: Sequence[float] | FloatArray,\n    simulated_valid: Sequence[bool] | NDArray[np.bool_] | None = None,\n) -> B2bGate:",
        "    rop: Sequence[float] | FloatArray | None = None,\n    simulated_valid: Sequence[bool] | NDArray[np.bool_] | None = None,\n) -> B2bGate:",
    ),
    (
        "chain: calibration B2B check ignores the wavelength",
        CH,
        "            if r.link != LinkSpec() or r.frozen_record_hash is not None:",
        "            if r.link.profile is not None or r.frozen_record_hash is not None:",
    ),
    (
        "freeze: a dangling symlink record is not present",
        FZ,
        "    return FREEZE_RECORD_PATH.exists() or FREEZE_RECORD_PATH.is_symlink()",
        "    return FREEZE_RECORD_PATH.is_file()",
    ),
    (
        "fit: the budget is 150",
        NF,
        "BUDGET = 140",
        "BUDGET = 150",
    ),
    (
        "fit: the budget check lets one more evaluation start",
        NF,
        "        if count >= budget:\n            raise _BudgetExhaustedError",
        "        if count > budget:\n            raise _BudgetExhaustedError",
    ),
    (
        "fit: another design seed",
        NF,
        "FIT_SEED = (20261101, 4101)",
        "FIT_SEED = (20261101, 4102)",
    ),
    (
        "fit: the design draws the coordinates before the permutation",
        NF,
        "        perm = rng.permutation(n)\n        rnd = rng.random(n)",
        "        rnd = rng.random(n)\n        perm = rng.permutation(n)",
    ),
    (
        "fit: a zero-error point enters as 1e-30 and not 1/N_b",
        NF,
        "max(p.ber, 1.0 / p.n_bits)",
        "max(p.ber, 1e-30)",
    ),
    (
        "fit: the BER residual is divided by 1.0 and not 0.5",
        NF,
        "BER_RESIDUAL_SCALE = 0.5",
        "BER_RESIDUAL_SCALE = 1.0",
    ),
    (
        "fit: a censored published cell is a term",
        NF,
        "                if not d.censored[k]:",
        "                if True:",
    ),
    (
        "fit: the SNR residual has another sign convention for the BER term",
        NF,
        "(math.log10(simulated) - math.log10(float(d.ber[k])))",
        "(math.log10(float(d.ber[k])) - math.log10(simulated))",
    ),
    (
        "fit: a resume does not check the replayed vector",
        NF,
        '            if rec["vector"] != vector or rec["i"] != n:',
        "            if False:",
    ),
    (
        "fit: a log of another run is resumed",
        NF,
        "        if first != dict(header):",
        "        if False:",
    ),
    (
        "fit: a log longer than the run is accepted",
        NF,
        "    if len(journal.recorded) > len(log.evaluations):",
        "    if False:",
    ),
    (
        "fit: a fit runs after a freeze record exists",
        NF,
        "    if nanf_freeze.freeze_record_present():\n        raise FitRefusedError",
        "    if False:\n        raise FitRefusedError",
    ),
    (
        "fit: seven workers are allowed",
        NF,
        "        if workers < 1 or workers > 6:",
        "        if workers < 1 or workers > 60:",
    ),
    (
        "fit: a published axis other than the declared grid is accepted",
        NF,
        "    if found != declared:",
        "    if False:",
    ),
    (
        "fit: the BER and SNR axes may differ",
        NF,
        "    if ber.x != snr.x:",
        "    if False:",
    ),
    (
        "fit: a vector is not clamped into its range",
        NF,
        "    return {s.name: min(max(float(values[s.name]), s.low), s.high) for s in B4_PARAMETERS}",
        "    return {s.name: float(values[s.name]) for s in B4_PARAMETERS}",
    ),
    (
        "fit: the stalled search reads as converged",
        NF,
        '                return OptimiserResult(False, count, "no step lowers the cost: search stalled")',
        '                return OptimiserResult(True, count, "no step lowers the cost: search stalled")',
    ),
    (
        "fit: a lost Jacobian point reads as converged",
        NF,
        '                return OptimiserResult(False, count, "a Jacobian point lost lock")',
        '                return OptimiserResult(True, count, "a Jacobian point lost lock")',
    ),
    (
        "fit: S2 is not tested (the predicted decrease is ignored)",
        NF,
        "            if predicted <= TAU and _lowest(seen)[0] >= (1.0 - TAU) * f:",
        "            if _lowest(seen)[0] >= (1.0 - TAU) * f:",
    ),
    (
        "fit: a point pushed outward at an edge is free",
        NF,
        "        i for i in range(_N) if not ((u[i] <= 0.0 and grad[i] > 0) or (u[i] >= 1.0 and grad[i] < 0))",
        "        i for i in range(_N) if True",
    ),
    (
        "fit: an unconverged search still gets an artefact",
        NF,
        "    if not result.converged:\n        status",
        "    if False:\n        status",
    ),
    (
        "fit: an undefined identifiability check is not a stop",
        NF,
        "    except IdentifiabilityUndefinedError:\n        return FitOutcome(STATUS_IDENTIFIABILITY_UNDEFINED, True, n_eval, log, chosen)",
        "    except IdentifiabilityUndefinedError:\n        raise",
    ),
    (
        "fit: the range edge is never reported",
        NF,
        "        if unit[i] <= RANGE_EDGE_TOL or unit[i] >= 1.0 - RANGE_EDGE_TOL",
        "        if False",
    ),
    (
        "fit: the artefact records the wrong number of calibration points",
        NF,
        '            "n_calibration_points": n_points,',
        '            "n_calibration_points": n_points + 1,',
    ),
    (
        "fit: the artefact cost is not the cost of the chosen vector",
        NF,
        '            "cost": chosen.objective,',
        '            "cost": 0.0,',
    ),
    (
        "fit: the lowest cost of the log is the last one on a tie",
        NF,
        "    return min(seen, key=lambda e: e[0])",
        "    return min(reversed(seen), key=lambda e: e[0])",
    ),
    (
        "fit: the B2B gate at the hashed vector is not evaluated",
        NF,
        "    gates = objective.gates(hashed)",
        "    gates = {}",
    ),
    (
        "fit: the design has 23 points",
        NF,
        "N_DESIGN = 24",
        "N_DESIGN = 23",
    ),
    (
        "fit: S1 a lost probe at the certificate is a penalty and not a stop",
        NF,
        "            jac = finite_difference(u, library=False)  # S1: a full finite-difference Jacobian here",
        "            jac = finite_difference(u, library=True)  # S1: a full finite-difference Jacobian here",
    ),
    (
        "fit: S3 the tested step is not evaluated",
        NF,
        "            if np.any(smallest != u):  # S3: the cost at the tested step is evaluated",
        "            if False:  # S3: the cost at the tested step is evaluated",
    ),
    (
        "fit: S4 the whole log is not searched for a lower point",
        NF,
        "            if predicted <= TAU and _lowest(seen)[0] >= (1.0 - TAU) * f:",
        "            if predicted <= TAU:",
    ),
    (
        "fit: tau is 0.5",
        NF,
        "TAU = 0.05 ",
        "TAU = 0.5 ",
    ),
    (
        "fit: the tested step is not bounded (rho is 5)",
        NF,
        "RHO = 0.15 ",
        "RHO = 5.0 ",
    ),
    (
        "fit: the library is told that a lost vector costs nothing",
        NF,
        "LOST_RESIDUAL = 1e3 ",
        "LOST_RESIDUAL = 0.0 ",
    ),
    (
        "fit: the stall rule is dropped (a round without a new evaluation goes on)",
        NF,
        "            if count == before and top[0] >= f:",
        "            if False:",
    ),
    (
        "fit: the range edge is only 1e-9 wide",
        NF,
        "RANGE_EDGE_TOL = 0.01 ",
        "RANGE_EDGE_TOL = 1e-9 ",
    ),
    (
        "fit: the search may use the whole budget (the re-evaluation has none)",
        NF,
        "SEARCH_BUDGET = BUDGET - 1 ",
        "SEARCH_BUDGET = BUDGET ",
    ),
    (
        "fit: the log header does not hold the fit code",
        NF,
        "        **(fit_identity() if fit_code is None else fit_code),",
        "        **({} if fit_code is None else fit_code),",
    ),
    (
        "fit: the log header leaves out the fit script",
        NF,
        '        "fit_script_sha256": hashlib.sha256(FIT_SCRIPT_PATH.read_bytes()).hexdigest(),\n',
        "",
    ),
    (
        "fit: the log header leaves out the library versions",
        NF,
        '        "numpy_version": np.__version__,\n        "scipy_version": scipy.__version__,\n',
        "",
    ),
    (
        "fit: a replay trusts the recorded cost",
        NF,
        "            if resid is not None and recorded != float(np.sum(resid * resid)):",
        "            if False:",
    ),
    (
        "fit: a replay accepts infinity without a lost point",
        NF,
        '            if (resid is None) != bool(rec["lost"]) or (resid is None) != (recorded == math.inf):',
        "            if (resid is None) != (recorded == math.inf):",
    ),
    (
        "fit: a replay accepts a lost point with a finite cost",
        NF,
        '            if (resid is None) != bool(rec["lost"]) or (resid is None) != (recorded == math.inf):',
        '            if (resid is None) != bool(rec["lost"]):',
    ),
    (
        "fit: the selected vector is not evaluated again",
        NF,
        "        if objective.fresh_cost(chosen.vector) != chosen.objective:  # the same cost, bit for bit",
        "        if False:  # the same cost, bit for bit",
    ),
    (
        "fit: the fresh cost reuses the points of an earlier call",
        NF,
        "        self._memo.pop(tuple(clamped[n] for n in _NAMES), None)\n",
        "        pass\n",
    ),
    (
        "fit: the re-evaluation allows a difference in the last bit",
        NF,
        "        if objective.fresh_cost(chosen.vector) != chosen.objective:  # the same cost, bit for bit",
        "        if abs(objective.fresh_cost(chosen.vector) - chosen.objective) > 1e-9:  # the same cost, bit for bit",
    ),
    (
        "fit: the artefact does not record the hash of the log",
        NF,
        '            "evaluation_log_sha256": hashlib.sha256(log_path.read_bytes()).hexdigest(),',
        '            "evaluation_log_sha256": "e" * 64,',
    ),
    (
        "freeze: the artefact checks do not name the log hash",
        FZ,
        '        "identifiability_eigenvalues",\n        "evaluation_log_sha256",\n    }',
        '        "identifiability_eigenvalues",\n    }',
    ),
    (
        "freeze: a malformed log hash is accepted",
        FZ,
        "    if not isinstance(log_hash, str) or _HEX64.fullmatch(log_hash) is None:",
        "    if False:",
    ),
    (
        "fit: the script has no commit rule",
        SF,
        '    print(f"RULE: commit {nanf_fit.DEFAULT_LOG_PATH.name} with the artefact, in the same commit")\n',
        "",
    ),
    (
        "fit: the script writes the log where the caller says",
        SF,
        "log_path=nanf_fit.DEFAULT_LOG_PATH,",
        "log_path=args.artifact.with_suffix('.jsonl'),",
    ),
    (
        "fit: the library method is dogbox",
        NF,
        'method="trf"',
        'method="dogbox"',
    ),
    (
        "fit: the library tolerance is 0.1",
        NF,
        "LIBRARY_TOL = 0.01 ",
        "LIBRARY_TOL = 0.1 ",
    ),
    (
        "holdout: another freeze record may read the holdout",
        NH,
        "        if held != freeze_hash:",
        "        if False:",
    ),
    (
        "holdout: an unreadable marker is not a refusal",
        NH,
        '            raise HoldoutAlreadyReadError("the holdout marker exists and cannot be read") from None',
        "            return",
    ),
    (
        "holdout: the record hash is not checked",
        NH,
        "    record = nanf_freeze.require_freeze(freeze_hash)",
        "    record = nanf_freeze.load_freeze_record()",
    ),
    (
        "holdout: the read does not ask for the holdout",
        NH,
        "reader(workbook_path, include_holdout=True, freeze_hash=freeze_hash)",
        "reader(workbook_path, include_holdout=False, freeze_hash=freeze_hash)",
    ),
    (
        "holdout: the read does not carry the freeze hash",
        NH,
        "reader(workbook_path, include_holdout=True, freeze_hash=freeze_hash)",
        "reader(workbook_path, include_holdout=True, freeze_hash=None)",
    ),
    (
        "holdout: the marker holds another hash",
        NH,
        'json.dumps({"freeze_hash": freeze_hash,',
        'json.dumps({"freeze_hash": "x",',
    ),
    (
        "holdout: the marker is not written",
        NH,
        "    marker.parent.mkdir(parents=True, exist_ok=True)\n    marker.write_text(",
        "    marker.parent.mkdir(parents=True, exist_ok=True)\n    (marker.parent / 'unused').write_text(",
    ),
    (
        "holdout: the cap of -5 dBm is -4 dBm",
        NH,
        "ROP_CAP_DBM = -5.0",
        "ROP_CAP_DBM = -4.0",
    ),
    (
        "holdout: the point at exactly -5 dBm is dropped",
        NH,
        "    return [i for i, x in enumerate(series.x) if x <= ROP_CAP_DBM]",
        "    return [i for i, x in enumerate(series.x) if x < ROP_CAP_DBM]",
    ),
    (
        "holdout: a failure reads as incomplete",
        NH,
        '    if failed:\n        return "failed: "',
        '    if False:\n        return "failed: "',
    ),
    (
        "holdout: an incomplete run reads as consistent",
        NH,
        "    return VERDICT_INCOMPLETE\n\n\n# --- the report",
        '    return "consistent with this one experiment"\n\n\n# --- the report',
    ),
    (
        "holdout: d of a lost point is computed",
        NH,
        "d_snr(n_snr, f_snr) if both_locked else None",
        "d_snr(n_snr, f_snr) if True else None",
    ),
    (
        "holdout: every d is discriminating",
        NH,
        "discriminating(d1, C1_TOL_DB)",
        "discriminating(d1, 0.0)",
    ),
    (
        "holdout: the report leaves out the sentence of G-A",
        NH,
        'NOT_BLIND = "The holdout is not fully blind"',
        'NOT_BLIND = "The holdout is blind"',
    ),
    (
        "holdout: the report drops the label",
        NH,
        'LABEL = "LITERATURE BENCHMARK / CALIBRATION ONLY"',
        'LABEL = "LITERATURE BENCHMARK"',
    ),
    (
        "holdout: C5 reads as run",
        NH,
        'C5_STATUS = "NOT RUN (links not declared)"',
        'C5_STATUS = "PASS"',
    ),
    (
        "holdout: the report claims a validation",
        NH,
        'It is no claim"\n        " of agreement',
        'It is a validation"\n        " of agreement',
    ),
    (
        "holdout: the real runner drops the link",
        NH,
        '        kwargs["link"] = nanf_chain.DECLARED_LINKS[task.link_key]',
        "        pass",
    ),
    (
        "holdout: the real runner uses index 0",
        NH,
        'kwargs: dict[str, Any] = {"point_index": task.point_index}',
        'kwargs: dict[str, Any] = {"point_index": 0}',
    ),
    (
        "holdout: the real runner does not score under the record",
        NH,
        "    arrays = curve_arrays([outcome])  # refuses a result that did not run under the record",
        "    arrays = type('A', (), {'ber': [outcome.result.ber if outcome.result else 0.0], 'snr_db': [outcome.result.snr_db if outcome.result else 0.0]})()",
    ),
    (
        "holdout: a second freeze is allowed",
        NH,
        "    if target.exists() or target.is_symlink():",
        "    if False:",
    ),
    (
        "holdout: a dirty work tree may freeze",
        NH,
        "    if dirty:\n        raise FreezeRefusedError",
        "    if False:\n        raise FreezeRefusedError",
    ),
    (
        "holdout: an untracked file in the identity is not seen",
        NH,
        '"--untracked-files=all"',
        '"--untracked-files=no"',
    ),
    (
        "holdout: a git failure reads as a clean tree",
        NH,
        '    if done.returncode != 0:\n        raise FreezeRefusedError("git could not report',
        '    if False:\n        raise FreezeRefusedError("git could not report',
    ),
    (
        "holdout: the plan may be dirty at the freeze",
        NH,
        "    files = [*nanf_freeze.identity_files(base), plan.relative_to(base).as_posix(), artifact_path]",
        "    files = [*nanf_freeze.identity_files(base), artifact_path]",
    ),
    (
        "holdout: the identity may be dirty at the freeze",
        NH,
        "    files = [*nanf_freeze.identity_files(base), plan.relative_to(base).as_posix(), artifact_path]",
        "    files = [plan.relative_to(base).as_posix(), artifact_path]",
    ),
    (
        "holdout: the artefact may be dirty at the freeze",
        NH,
        "    files = [*nanf_freeze.identity_files(base), plan.relative_to(base).as_posix(), artifact_path]",
        "    files = [*nanf_freeze.identity_files(base), plan.relative_to(base).as_posix()]",
    ),
    (
        "freeze: the holdout runner is outside the code identity",
        FZ,
        '    "opticps.measurement.nanf_holdout",  # the holdout runner (Amendment 11 J-G.5)\n',
        "",
    ),
    (
        "chain: the declared link table is empty",
        CH,
        '    "SSMF-4.53km-1550": _paper_link("SSMF", 4.53, 15.95, 1.4682),',
        '    "SSMF-4.53km-1550": _paper_link("SSMF", 4.53, 15.9, 1.4682),',
    ),
    (
        "chain: the declared indices stop at 17",
        CH,
        "DECLARED_POINT_INDICES: frozenset[int] = frozenset(range(19))",
        "DECLARED_POINT_INDICES: frozenset[int] = frozenset(range(18))",
    ),
    (
        "chain: the declared calibration grid has nine points per rate",
        CH,
        "(rate, -12.0 + k, k) for rate in (80, 100, 112) for k in range(8)",
        "(rate, -12.0 + k, k) for rate in (80, 100, 112) for k in range(9)",
    ),
]


def run(mutant: tuple[str, str, str, str] | None) -> str:
    """killed, SURVIVED, BROKEN or INVALID; None runs the unmutated copy."""
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp)
        shutil.copytree(ROOT / "src", work / "src", ignore=shutil.ignore_patterns("__pycache__"))
        for folder in ("configs", "docs", "reports"):
            shutil.copytree(ROOT / folder, work / folder, ignore=shutil.ignore_patterns("*.pyc"))
        for name in ("pyproject.toml", "uv.lock"):
            shutil.copy(ROOT / name, work / name)
        (work / "scripts").mkdir()
        shutil.copy(ROOT / SF, work / "scripts")
        (work / "tests").mkdir()
        shutil.copy(ROOT / "tests/nanf_profile_helpers.py", work / "tests")
        for test in TESTS:
            shutil.copy(ROOT / test, work / "tests")
        if mutant is not None:
            _, rel, old, new = mutant
            path = work / rel
            text = path.read_text()
            if text.count(old) != 1:
                return "INVALID"
            path.write_text(text.replace(old, new))
        git = ["git", "-C", str(work)]
        subprocess.run([*git, "init", "-q"], check=True)
        subprocess.run([*git, "add", "-A"], check=True, capture_output=True)
        env = {**os.environ, "PYTHONPATH": str(work / "src")}
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "pytest",
                "-o",
                "addopts=-rN",
                "-q",
                "-x",
                "-p",
                "no:cacheprovider",
                *(NEW_ORDER if mutant is None or mutant[0].startswith(NEW_PREFIXES) else RUN_ORDER),
            ],
            cwd=work,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=True,
        )
        try:
            proc.communicate(timeout=None if mutant is None else MUTANT_TIMEOUT_S)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGKILL)  # the whole group: pool workers hold the pipes
            proc.communicate()
            return "killed"  # a suite that no longer ends has noticed the removed guard
    if proc.returncode == 0:
        return "ok" if mutant is None else "SURVIVED"
    return "killed" if proc.returncode == 1 else "BROKEN"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("-j", type=int, default=4)
    parser.add_argument("-k", default="")
    args = parser.parse_args()
    baseline = run(None)
    print(f"{baseline:9} unmutated copy", flush=True)
    if baseline != "ok":
        return 2
    chosen = [m for m in MUTANTS if args.k in m[0]]
    outcomes = []
    with ThreadPoolExecutor(max_workers=args.j) as pool:
        futures = [pool.submit(run, m) for m in chosen]
        pending = dict(zip(futures, chosen, strict=True))
        for future in as_completed(pending):
            label, rel, _, _ = pending[future]
            outcome = future.result()
            outcomes.append(outcome)
            print(f"{outcome:9} {Path(rel).name}: {label}", flush=True)
    bad = [o for o in outcomes if o != "killed"]
    print(f"{len(chosen) - len(bad)} of {len(chosen)} killed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
