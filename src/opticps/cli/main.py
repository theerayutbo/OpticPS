"""Command-line interface. Nothing here can connect to or enable an instrument."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from opticps import __version__

DEFAULT_ROOT = Path("output/keysight_m8199b")
DEFAULT_CONFIG = Path("configs/m8199b_profiles.yaml")
DEFAULT_DEMO = Path("configs/demo.yaml")
DEFAULT_RESULTS = Path("results/synthetic")
DEFAULT_FIBER_CONFIG = Path("configs/fiber_validation.yaml")
DEFAULT_FIBER_RESULTS = Path("results/fiber_validation")


def cmd_generate(args: argparse.Namespace) -> int:
    from opticps.measurement.validate_export import validate_profile
    from opticps.transmitter.export import generate_all

    settings, profiles, selection = generate_all(args.config, args.output)
    print(f"Adaptive P(+-3) = {selection.p_outer} ({selection.source})")
    failed = 0
    for profile in profiles:
        results = validate_profile(args.output / profile.name, settings.data_out)
        counts = Counter(r.passed for r in results)
        failed += counts[False]
        print(f"{profile.name}: {counts[True]} checks passed, {counts[False]} failed")
    return 1 if failed else 0


def cmd_validate(args: argparse.Namespace) -> int:
    from opticps.measurement.capture import load_capture
    from opticps.measurement.validate_export import validate_profile

    failed = 0
    if args.captures:
        for path in sorted(args.captures.glob("*.json")):
            load_capture(path)
            print(f"{path.name}: valid")
        return 0
    for folder in sorted(p for p in args.output.iterdir() if p.is_dir()):
        results = validate_profile(folder, args.data_out)
        bad = [r for r in results if not r.passed]
        failed += len(bad)
        print(f"{folder.name}: {len(results) - len(bad)} passed, {len(bad)} failed")
        for item in bad:
            print(f"  FAIL {item.waveform} {item.check}: {item.detail}")
    return 1 if failed else 0


def cmd_simulate(args: argparse.Namespace) -> int:
    from opticps.measurement.demo import BANNER, run_demo

    results = run_demo(args.config, args.output / "adaptive_selection.json", args.results)
    print(BANNER)
    print(f"Finished in {results['runtime_s']:.0f} s; results in {args.results}")
    return 0


def cmd_fiber_validate(args: argparse.Namespace) -> int:
    from opticps.measurement.fiber_validation import BANNER, run_fiber_validation
    from opticps.reporting.fiber_report import build_fiber_report

    results = run_fiber_validation(
        args.config, args.output / "adaptive_selection.json", args.results
    )
    print(BANNER)
    print(f"Finished in {results['runtime_s']:.0f} s; results in {args.results}")
    print(build_fiber_report(args.results / "fiber_results.json", args.report_dir))
    return 0


def cmd_ingest(args: argparse.Namespace) -> int:
    from opticps.measurement.capture import load_capture

    paths = sorted(args.input.glob("*.json"))
    if not paths:
        print(f"No capture metadata in {args.input}", file=sys.stderr)
        return 1
    for path in paths:
        capture = load_capture(path)
        meta = capture.metadata
        print(f"{meta['capture_id']}: {capture.samples.size} samples, {meta['data_source']}")
    return 0


def cmd_analyze(args: argparse.Namespace) -> int:
    from opticps.measurement.compare import analyze_directory

    summary = analyze_directory(args.input, args.output, args.profile, args.results)
    print(json.dumps({k: summary[k] for k in ("data_sources", "test_captures")}, indent=2))
    print(f"Results in {args.results}")
    return 0


def cmd_compare(args: argparse.Namespace) -> int:
    summary_path = args.results / "analysis_summary.json"
    if not summary_path.exists():
        print(f"Run opticps analyze first; {summary_path} is missing", file=sys.stderr)
        return 1
    summary = json.loads(summary_path.read_text())
    for row in summary["fairness_audit"]:
        print(f"{row['variable']:<32}{row['status']:<18}{row['range']}")
    for item in summary["comparisons"]:
        print(item)
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from opticps.reporting.report import build_report

    print(build_report(args.results / "demo_results.json", args.output_dir))
    return 0


def cmd_slides(args: argparse.Namespace) -> int:
    from opticps.reporting.slides import build_slides

    print(build_slides(args.results / "demo_results.json", args.output_dir))
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    from opticps.reporting.report import build_report
    from opticps.reporting.slides import build_slides

    for command, namespace in (
        (cmd_generate, argparse.Namespace(config=DEFAULT_CONFIG, output=args.output)),
        (
            cmd_simulate,
            argparse.Namespace(config=DEFAULT_DEMO, output=args.output, results=args.results),
        ),
    ):
        if command(namespace):
            return 1
    print(build_report(args.results / "demo_results.json", Path("reports")))
    print(build_slides(args.results / "demo_results.json", Path("slides")))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opticps", description=__doc__)
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command", required=True)

    def add(name: str, handler: object, help_text: str) -> argparse.ArgumentParser:
        command = sub.add_parser(name, help=help_text)
        command.set_defaults(handler=handler)
        command.add_argument("--output", type=Path, default=DEFAULT_ROOT, help="waveform root")
        return command

    command = add("generate", cmd_generate, "generate and validate M8199B waveform packages")
    command.add_argument("--config", type=Path, default=DEFAULT_CONFIG)

    command = add("validate", cmd_validate, "validate waveform packages or a capture folder")
    command.add_argument("--captures", type=Path, help="validate captures in this folder instead")
    command.add_argument("--data-out", default="DataOut1", choices=("DataOut1", "DataOut2"))

    command = add("simulate", cmd_simulate, "run the simulated comparison")
    command.add_argument("--config", type=Path, default=DEFAULT_DEMO)
    command.add_argument("--results", type=Path, default=DEFAULT_RESULTS)

    command = add("fiber-validate", cmd_fiber_validate, "validate the ITU-T G.652 fiber model")
    command.add_argument("--config", type=Path, default=DEFAULT_FIBER_CONFIG)
    command.add_argument("--results", type=Path, default=DEFAULT_FIBER_RESULTS)
    command.add_argument("--report-dir", type=Path, default=Path("reports"))

    command = add("ingest", cmd_ingest, "check a folder of captures")
    command.add_argument("--input", type=Path, required=True)

    command = add("analyze", cmd_analyze, "analyze captures against exported references")
    command.add_argument("--input", type=Path, required=True)
    command.add_argument("--profile", required=True)
    command.add_argument("--results", type=Path, default=Path("results/analysis"))

    command = add("compare", cmd_compare, "print the fairness audit and paired comparisons")
    command.add_argument("--results", type=Path, default=Path("results/analysis"))

    command = add("report", cmd_report, "build the PDF and Markdown report")
    command.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    command.add_argument("--output-dir", type=Path, default=Path("reports"))

    command = add("slides", cmd_slides, "build the PowerPoint and PDF slides")
    command.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    command.add_argument("--output-dir", type=Path, default=Path("slides"))

    command = add("demo", cmd_demo, "regenerate waveforms, simulation, report and slides")
    command.add_argument("--results", type=Path, default=DEFAULT_RESULTS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    sys.exit(main())
