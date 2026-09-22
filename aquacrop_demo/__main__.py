from __future__ import annotations

import argparse
import time
from pathlib import Path

import yaml


def main():
    parser = argparse.ArgumentParser(description="G2F AquaCrop-OSPy quick planting-date experiment")
    parser.add_argument("stage", choices=["smoke", "prepare", "baseline", "calibrate", "validate", "scenarios", "report", "all"])
    parser.add_argument("--config", default="aquacrop_demo/config.yaml")
    args = parser.parse_args()
    cfg = yaml.safe_load(Path(args.config).read_text())
    from .data import prepare, write_json
    from .model import smoke
    from .pipeline import baseline, calibrate, validate, scenarios
    def report(config):
        from .report import build_report
        return build_report(config)
    functions = {"smoke": smoke, "prepare": prepare, "baseline": baseline, "calibrate": calibrate, "validate": validate, "scenarios": scenarios, "report": report}
    stages = list(functions) if args.stage == "all" else [args.stage]
    timings = {}
    for stage in stages:
        print(f"\nStarting stage: {stage}", flush=True)
        start = time.perf_counter()
        functions[stage](cfg)
        timings[stage] = time.perf_counter() - start
        print(f"Finished {stage}: {timings[stage]:.1f} seconds", flush=True)
        write_json(Path(cfg["output_dir"]) / f"timing_{stage}.json", {"stage": stage, "seconds": timings[stage]})


if __name__ == "__main__":
    main()
