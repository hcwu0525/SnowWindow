"""Command-line entry point for SnowWindow experiment stages."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Optional

from snowwindow.config import ConfigError, load_config

COMMANDS = (
    "audit",
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


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        load_config(args.config)
    except ConfigError as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return 2

    print(f"{args.command}: not implemented", file=sys.stderr)
    return 2
