"""Prepare next-year NASA POWER weather at each base environment coordinate."""
from __future__ import annotations

import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd
import yaml

from .data import _download_weather, sha256_file, write_json

SOURCE = Path("outputs/aquacrop_annual")
OUT = Path("outputs/aquacrop_crossyear")


def prepare() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(Path("aquacrop_demo/config.yaml").read_text())
    cfg["output_dir"] = str(OUT)
    cfg["cross_year"] = True
    cfg["crossyear_weather_provenance"] = "NASA POWER AG, same coordinate for both years of each base environment"
    shutil.copy2(SOURCE / "environments.csv", OUT / "environments.csv")
    shutil.copytree(SOURCE / "weather", OUT / "base_weather", dirs_exist_ok=True)
    units = pd.read_csv(OUT / "environments.csv").to_dict("records")
    next_rows = [{**u, "year": int(u["year"]) + 1, "Env": f"{u['Env']}_next_year"} for u in units]
    with ThreadPoolExecutor(max_workers=3) as pool:
        metadata = list(pool.map(lambda row: _download_weather(cfg, row), next_rows))
    combined = OUT / "weather_combined"
    combined.mkdir(exist_ok=True)
    manifest = []
    for u, next_row, source in zip(units, next_rows, metadata):
        base_path = OUT / "base_weather" / f"{u['Env']}.csv"
        next_path = OUT / "weather" / f"{next_row['Env']}.csv"
        base = pd.read_csv(base_path, parse_dates=["Date"])
        later = pd.read_csv(next_path, parse_dates=["Date"])
        frame = pd.concat([base, later], ignore_index=True)
        expected = pd.date_range(f"{u['year']}-01-01", f"{u['year']+1}-12-31")
        if not frame.Date.equals(pd.Series(expected)) or frame.Date.duplicated().any():
            raise ValueError(f"Incomplete or duplicated two-year weather for {u['Env']}")
        target = combined / f"{u['Env']}.csv"
        frame.to_csv(target, index=False)
        manifest.append({"Env": u["Env"], "base_weather_sha256": sha256_file(base_path),
                         "next_weather_sha256": sha256_file(next_path), "combined_sha256": sha256_file(target),
                         "next_year_provenance": source, "rows": len(frame)})
    write_json(OUT / "weather_manifest.json", manifest)
    (OUT / "config.yaml").write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    print(f"Prepared {len(manifest)} two-year weather records", flush=True)
    return cfg


if __name__ == "__main__":
    prepare()
