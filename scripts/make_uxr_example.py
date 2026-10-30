"""Regenerate reports/UXR_Receiver_Analysis_Example from mock-receiver captures.

The captures are produced by the mock receiver (data_source = simulated, no real instrument):
each exported Profile A waveform is repeated, passed through the simulated link and written in
the capture format, then run through ingest-uxr, compare-uxr and uxr-report. The raw capture
files are temporary and are not kept; only the analysis outputs, figures and the report are.
Run from the repository root: uv run python scripts/make_uxr_example.py
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import csv
import json
import shutil
import tempfile
from pathlib import Path

import yaml

from opticps.instruments.mock_receiver import capture_waveform
from opticps.measurement.demo import link_for
from opticps.measurement.uxr_compare import compare_uxr
from opticps.measurement.uxr_ingest import ingest_uxr
from opticps.reporting.uxr_report import build_uxr_report

ROOT = Path("output/keysight_m8199b")
PROFILE = "A_initial_8GBd"
RESULTS = Path("results/uxr_example")
REPORTS = Path("reports")
SIMULATION = Path("results/synthetic/demo_results.json")
WAVEFORMS = ("PAM4_Uniform", "PAM4_Fixed_PS70", "PAM4_Fixed_PS80", "PAM4_Adaptive")
ATTENUATION_DB = 18.4  # between two simulated attenuation points
FRAMES = 5  # periods of the exported waveform in one capture
TITLE = "UXR Receiver Analysis, Example from Mock Captures"


def main() -> None:
    config = yaml.safe_load(Path("configs/demo.yaml").read_text())
    link = link_for(config, config["profile_A"], extra_attenuation_db=ATTENUATION_DB)
    with (ROOT / PROFILE / "experiment_manifest.csv").open(newline="") as handle:
        manifest = {Path(r["waveform_filename"]).stem: r for r in csv.DictReader(handle)}
    if RESULTS.exists():
        shutil.rmtree(RESULTS)
    with tempfile.TemporaryDirectory() as work_name:
        work = Path(work_name)
        for name in WAVEFORMS:
            row = manifest[name]
            lines = (ROOT / PROFILE / row["waveform_filename"]).read_text().splitlines()
            tiled = work / f"{name}_tiled.csv"
            tiled.write_text("\n".join([lines[0], *lines[1:] * FRAMES]) + "\n")
            captured = capture_waveform(
                tiled,
                float(row["sample_rate_Sa_per_s"]),
                float(row["symbol_rate_Bd"]),
                row["experiment_id"],
                [float(row[f"probability_{k}"]) for k in ("minus3", "minus1", "plus1", "plus3")],
                f"mock-{name}-r1",
                "r1",
                "test",
                work,
                link,
                time_axis=True,
            )
            ingest_uxr(
                captured.data_path,
                captured.metadata_path,
                ROOT,
                PROFILE,
                RESULTS,
                registry=work / "registry.json",
            )
    summary = compare_uxr(RESULTS)
    print(json.dumps(summary["comparisons"], indent=2))
    print(
        build_uxr_report(RESULTS, REPORTS, SIMULATION, ROOT, "UXR_Receiver_Analysis_Example", TITLE)
    )


if __name__ == "__main__":
    main()
