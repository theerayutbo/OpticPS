"""Mutation check of the NANF fibre-profile guards (Gate N2a).

Each mutant is one text replacement in `optical_channel/fiber.py` or `link.py`, applied to a scratch
copy of the files the NANF tests need. The NANF test files run against that copy; a mutant is
"killed" when a test fails (pytest exit code 1). A survivor means a guard has no test that notices
its removal. A mutant that breaks collection (exit code 2 or more) is reported BROKEN, never
killed, and the unmutated copy must pass first. The exit code is 0 only when every listed mutant is
killed.

    python scripts/mutate_nanf.py [-j JOBS] [-k LABEL_SUBSTRING]

The list is a hand-written sample of the guards (the 14 gaps of the third N1 review, the N2a
guards, the N2 fix-round guards, the N3 part a guards, the 14 survivors of the first N3 part a
review and the guards added in the N3 part a fix round). It proves nothing about mutants that are
not in it.
The label says what the mutant does.
"""

# SPDX-License-Identifier: MIT
# ruff: noqa: E501  (mutant texts are source lines and may be long)
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
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
TESTS = (
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
    "tests/test_nanf_n3a_scoring.py",
    "tests/test_nanf_n3a_freeze.py",
)
# Reviewed as equivalent and left out: dropping `link` or `nanf_import` from ENTRY_MODULES (both stay
# reachable by imports from nanf_chain and nanf_benchmark); reading infinity as censored in
# `is_censored` (the range check still refuses it); allowing NaN fields in `Crossing` (the per-kind
# finiteness checks still refuse them).
# Fast files first, so that most mutants are killed early; the slow chain tests run last.
RUN_ORDER = (
    "tests/test_nanf_n3a_scoring.py",
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
        "    keep = r <= ROP_CAP_DBM\n    p, s = p[keep], s[keep]",
        "    keep = r < ROP_CAP_DBM\n    p, s = p[keep], s[keep]",
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
        "        or cost < 0\n",
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
        done = subprocess.run(
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
                *RUN_ORDER,
            ],
            cwd=work,
            env=env,
            capture_output=True,
            text=True,
        )
    if done.returncode == 0:
        return "ok" if mutant is None else "SURVIVED"
    return "killed" if done.returncode == 1 else "BROKEN"


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
    with ThreadPoolExecutor(max_workers=args.j) as pool:
        outcomes = list(pool.map(run, chosen))
    for (label, rel, _, _), outcome in zip(chosen, outcomes, strict=True):
        print(f"{outcome:9} {Path(rel).name}: {label}", flush=True)
    bad = [o for o in outcomes if o != "killed"]
    print(f"{len(chosen) - len(bad)} of {len(chosen)} killed")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
