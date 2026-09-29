"""Command-line entry point for SnowWindow experiment stages."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from snowwindow.config import ConfigError, load_config

COMMANDS = (
    "audit",
    "catalog",
    "prepare",
    "baseline",
    "calibrate",
    "validate",
    "simulate",
    "scan",
    "report",
    "run",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="snowwindow")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for command in COMMANDS:
        stage_parser = subparsers.add_parser(command)
        stage_parser.add_argument(
            "--config",
            required=True,
            type=Path,
            help="path to an experiment YAML configuration",
        )
    return parser


def _run_stage(command: str, config) -> object:
    from snowwindow.data import audit_g2f, prepare_g2f
    from snowwindow.reporting import report_stage
    from snowwindow.scan import scan_stage
    from snowwindow.stages import (
        baseline_stage,
        calibration_stage,
        simulate_stage,
        validation_stage,
    )

    handlers = {
        "audit": audit_g2f,
        "prepare": prepare_g2f,
        "baseline": baseline_stage,
        "calibrate": calibration_stage,
        "validate": validation_stage,
        "simulate": simulate_stage,
        "scan": scan_stage,
        "report": report_stage,
    }
    if command == "run":
        if not (config.experiment_dir / "manifests/prepare_manifest.json").is_file():
            prepare_g2f(config)
        baseline_stage(config)
        calibration_stage(config)
        validation_stage(config)
        scan_stage(config)
        return report_stage(config)
    return handlers[command](config)


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "catalog":
        from snowwindow.catalog import build_catalog

        try:
            _, _, catalog_path = build_catalog(Path.cwd() / "outputs")
        except Exception as exc:
            print(f"catalog failed: {exc}", file=sys.stderr)
            return 1
        print(f"catalog: {catalog_path}")
        return 0
    try:
        config = load_config(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    try:
        result = _run_stage(args.command, config)
    except Exception as exc:
        print(f"{args.command} failed: {exc}", file=sys.stderr)
        return 1
    if args.command == "audit":
        print(json.dumps(result["counts"], sort_keys=True))
    else:
        print(f"{args.command}: complete")
    return 0
