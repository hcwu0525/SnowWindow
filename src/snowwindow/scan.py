"""Full-year planting-date scans and planting-window summaries."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from calendar import isleap
from datetime import date
from pathlib import Path
from typing import Any

import pandas as pd

from snowwindow.config import ExperimentConfig


def calendar_dates(year: int) -> tuple[date, ...]:
    return tuple(
        timestamp.date()
        for timestamp in pd.date_range(
            date(year, 1, 1), periods=366 if isleap(year) else 365
        )
    )


def _segments(dates: list[date]) -> list[list[str]]:
    if not dates:
        return []
    groups: list[list[date]] = [[dates[0]]]
    for current in dates[1:]:
        if (current - groups[-1][-1]).days == 1:
            groups[-1].append(current)
        else:
            groups.append([current])
    return [[value.isoformat() for value in group] for group in groups]


def derive_planting_windows(
    frame: pd.DataFrame, fractions: tuple[float, ...]
) -> list[dict[str, Any]]:
    usable = frame.loc[
        frame["status"].eq("matured")
        & pd.to_numeric(frame["dry_yield_mg_ha"], errors="coerce").gt(0)
    ].copy()
    if usable.empty:
        return [
            {
                "fraction": float(fraction),
                "status": "no_positive_mature_yield",
                "maximum_yield_mg_ha": None,
                "dates": [],
                "segments": [],
                "best_dates": [],
            }
            for fraction in fractions
        ]
    usable["planting_date"] = pd.to_datetime(usable["planting_date"]).dt.date
    maximum = float(usable["dry_yield_mg_ha"].max())
    best = sorted(
        usable.loc[usable["dry_yield_mg_ha"].eq(maximum), "planting_date"].unique()
    )
    rows = []
    for fraction in fractions:
        dates = sorted(
            usable.loc[
                usable["dry_yield_mg_ha"].ge(maximum * fraction), "planting_date"
            ].unique()
        )
        rows.append(
            {
                "fraction": float(fraction),
                "status": "ok",
                "maximum_yield_mg_ha": maximum,
                "dates": [value.isoformat() for value in dates],
                "segments": _segments(dates),
                "best_dates": [value.isoformat() for value in best],
            }
        )
    return rows


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    temporary.write_text(
        json.dumps(value, allow_nan=False, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _atomic_table(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f"{path.name}.tmp-{os.getpid()}-{uuid.uuid4().hex}")
    if path.suffix == ".parquet":
        frame.to_parquet(temporary, index=False)
    else:
        frame.to_csv(temporary, index=False)
    os.replace(temporary, path)


def scan_stage(config: ExperimentConfig) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Materialize the reviewed six-environment scan from the model cache."""

    source = config.output_dir / "aquacrop_crossyear/annual_scenarios.csv"
    if not source.is_file():
        raise FileNotFoundError(
            "full-year model cache is missing; run the AquaCrop scan producer first"
        )
    frame = pd.read_csv(source)
    selected = frame.loc[
        frame["Env"].isin(config.selection.environments)
        & frame["parameter_set"].isin(["default", "optimized"])
    ].copy()
    selected["parameter_set"] = selected["parameter_set"].replace(
        {"optimized": "calibrated"}
    )
    selected = selected.rename(
        columns={
            "Env": "environment_id",
            "unit_id": "management_unit_id",
            "dry_yield_Mg_ha": "dry_yield_mg_ha",
            "yield_at_15p5_Mg_ha": "yield_at_15p5_mg_ha",
            "flowering_proxy_DAP": "flowering_proxy_dap",
            "actual_planting_date": "actual_sowing_date",
        }
    )
    selected["planting_date"] = pd.to_datetime(selected["planting_date"]).dt.date
    selected = selected.sort_values(
        ["environment_id", "parameter_set", "planting_date"]
    ).reset_index(drop=True)
    expected = (
        sum(
            len(calendar_dates(int(year)))
            for year in selected[["environment_id", "year"]]
            .drop_duplicates()["year"]
            .tolist()
        )
        * 2
    )
    if len(selected) != expected:
        raise ValueError(
            f"scan row count mismatch: expected {expected}, got {len(selected)}"
        )
    if selected.duplicated(["environment_id", "parameter_set", "planting_date"]).any():
        raise ValueError("scan contains duplicate environment/parameter/date keys")

    window_rows = []
    for (environment_id, parameter_set), group in selected.groupby(
        ["environment_id", "parameter_set"], sort=True
    ):
        for window in derive_planting_windows(group, config.simulation.scan_fractions):
            window_rows.append(
                {
                    "environment_id": environment_id,
                    "parameter_set": parameter_set,
                    **window,
                }
            )
    windows = pd.DataFrame(window_rows)
    root = config.experiment_dir / "scan"
    _atomic_table(root / "summary.parquet", selected)
    csv_frame = selected.copy()
    csv_frame["planting_date"] = csv_frame["planting_date"].astype(str)
    _atomic_table(root / "summary.csv", csv_frame)
    _atomic_json(root / "windows.json", window_rows)
    _atomic_table(root / "windows.csv", windows)
    _atomic_json(
        root / "manifest.json",
        {
            "row_count": len(selected),
            "unique_key_count": int(
                selected[["environment_id", "parameter_set", "planting_date"]]
                .drop_duplicates()
                .shape[0]
            ),
            "source_path": str(source),
            "source_sha256": _sha256_file(source),
            "source_parameter_mapping": {
                "default": "default",
                "optimized": "calibrated",
            },
            "weather_source": (
                "NASA POWER AG cached same-coordinate full-year forcing"
            ),
        },
    )
    return selected, windows
