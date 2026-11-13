# Reproducing the external-benchmark numbers

Run times were measured on a heavily loaded laptop (several other jobs running); expect less on
an idle machine. Commands run from the repository root.

## 0. Fresh clone

```sh
git clone <repository URL> OpticPS && cd OpticPS
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/pip install pytest ruff mypy pypdf types-PyYAML
```

Python 3.11 to 3.14. A fresh clone has no `data/external/` (it is ignored by git). The captures
and the Ran Source Data are never in the repository.

## 1. What needs no external data (works in a fresh clone)

| Step | Command | Expected output | Measured time |
|---|---|---|---|
| Wiegart and Ran rows, evidence matrix check | `.venv/bin/python scripts/build_evidence_matrix.py --check` | `docs/benchmarks/EVIDENCE_MATRIX.yaml matches the code (23 rows)`, exit 0 | 25 s |
| Rewrite the matrix from the code | `.venv/bin/python scripts/build_evidence_matrix.py --write` | `wrote docs/benchmarks/EVIDENCE_MATRIX.yaml (23 rows)`; `git diff` empty | 25 s |
| Status table of the report | `.venv/bin/python scripts/build_evidence_matrix.py --table` | the 23-row table in `BENCHMARK_REPORT.md` | 25 s |
| All five figures | `.venv/bin/python scripts/make_benchmark_figures.py --out build/figures` | five PNG paths, each under 300 kB, each with the text chunk `OpticPS-figure-spec-sha256` equal to that of the committed PNG | 28 s |
| Register metadata, opens nothing | `.venv/bin/python -m opticps.cli.main benchmark inspect-format --metadata-only` | prints the B2B file's register metadata; ends with `metadata only: the file was not opened`; exit 0, no `data/external/` needed | not timed |
| E3 numerics (W1 to W9, R1 to R4) | `.venv/bin/python -m pytest -o addopts= tests/test_benchmark_e3.py` | `131 passed` | 34 s |
| E4 checks | `.venv/bin/python -m pytest -o addopts= tests/test_benchmark_e4.py` | `51 passed` | 55 s |

Wiegart numbers (rows W1 to W3, ours against the paper's running text, tolerance 0.01 dB), printed
by the matrix, are: W1 0.8328 against 0.83 (dev +0.0028), W2 0.7097 against 0.71 (-0.0003), W3
0.6268 against 0.63 (-0.0032). W4a and W4b: our optima 0.3982 (SMD) and 0.3958 (BMD), status
NOT COMPARABLE. Ran analytical first nulls: 68.20 GHz (5 km), 48.22 GHz (10 km). To print them:

```sh
.venv/bin/python -c "from opticps.benchmarks.e3_wiegart import wiegart_rows; \
[print(r.row_id, r.result.status.value, r.result.model_value) for r in wiegart_rows()]"
.venv/bin/python -c "from opticps.benchmarks.e3_ran import ran_rows; \
[print(r.row_id, r.result.status.value, r.our_text) for r in ran_rows()]"
```

The TERIPHIC rows and the TERIPHIC figures are read from records committed in the repository
(`docs/benchmarks/teriphic_e2/`, `teriphic_e2c/`, `teriphic_prbs/`), so they regenerate without
the captures. Those records are results of runs that already happened; reading them is the
reproduction at this level.

## 2. What needs `data/external/` and what happens without it

The TERIPHIC captures sit in `data/external/teriphic/` (Zenodo record 7886498, DOI
10.5281/zenodo.7886498, file names and MD5 in `docs/benchmarks/SOURCE_REGISTER.md`). Without the
directory:

* the tests that need a capture skip (nine skips in the full suite at the E3 gate, all for the
  absent directory), nothing fails;
* the commands below need those files; they were not run without them, and they are not part
  of any test. `inspect-format --metadata-only` is not among them: it reads only the register
  metadata and runs without `data/external/` (run at the E4 fix round, exit 0; see section 1).
  Without `--metadata-only`, `inspect-format` needs the B2B file.

With the directory, these commands exist. The E4 Dev did not run any of them: re-running a fit or a
holdout scoring is outside E4, and the results they produce are already committed.

| Purpose | Command | Result of record |
|---|---|---|
| B2B format check (holdout files refused) | `.venv/bin/python -m opticps.cli.main benchmark inspect-format` | B2B Keysight BIN v10 findings in `MISSING_PARAMETERS.md` section 4 |
| B2B model and pre-registration | `.venv/bin/python scripts/freeze_teriphic_e2.py prepare` | `docs/benchmarks/teriphic_e2/b2b_model.yaml`, `preregistered_predictions.yaml` |
| Holdout scoring, run once for 2 km | `.venv/bin/python scripts/score_teriphic_e2.py HOLDOUT.bin --b2b B2B.bin --freeze-commit SHA` | `docs/benchmarks/teriphic_e2/two_km_result.json` (FAIL); the 10 km run is refused by the code after a FAIL and the file stays unspent |
| E2c law-model study | `.venv/bin/python scripts/power_study_e2c.py fit` | `docs/benchmarks/teriphic_e2c/law_model_v2.yaml` (`FIT_INVALID`) |
| B2B pattern search | `.venv/bin/python scripts/prbs_search_b2b.py` | `docs/benchmarks/teriphic_prbs/b2b_sequence_candidate.yaml` (`INFERRED_REFERENCE`); refuses to overwrite |

The scoring script needs the freeze commit id the owner recorded outside the repository, and the
2 km capture is no longer a holdout (E2c used it for calibration). Do not point any command at the
10 km capture.

The Ran Source Data spreadsheet was not obtained, so there is no command for it: row R3 is
`BLOCKED`. The Wiegart author manuscript is not needed to reproduce any number: the numbers of
the paper's running text are written in `src/opticps/benchmarks/e3_wiegart.py`.

## 3. Help text

Each command above answers `--help` with exit 0:

```sh
.venv/bin/python scripts/build_evidence_matrix.py --help
.venv/bin/python scripts/make_benchmark_figures.py --help
.venv/bin/python scripts/freeze_teriphic_e2.py --help
.venv/bin/python scripts/score_teriphic_e2.py --help
.venv/bin/python scripts/power_study_e2c.py --help
.venv/bin/python scripts/prbs_search_b2b.py --help
.venv/bin/python -m opticps.cli.main benchmark inspect-format --help
```

## 4. Checks run at E4

Tests and lint are listed in `docs/orchestration/opticps-v2/handoff/E4_dev.md` with their summary
lines and times.

```sh
.venv/bin/python -m pytest -o addopts= tests/test_benchmark_e4.py tests/test_benchmark_e3.py \
  tests/test_benchmark_provenance.py tests/test_benchmark_e2_freeze.py
.venv/bin/ruff check src tests scripts
.venv/bin/mypy
```
