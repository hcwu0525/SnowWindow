from __future__ import annotations

import json
from pathlib import Path

from snowwindow.catalog import build_catalog


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("content\n", encoding="utf-8")


def test_build_catalog_classifies_complete_partial_legacy_and_setup(
    tmp_path: Path,
) -> None:
    experiments = tmp_path / "experiments"
    complete = experiments / "complete-demo"
    partial = experiments / "partial-demo"
    forecast = experiments / "forecast-demo"
    legacy = experiments / "legacy" / "annual"
    setup = experiments / "apsim_smoke"
    for path in (
        complete / "report/report.md",
        complete / "validation/metrics.csv",
        complete / "scan/summary.csv",
        complete / "scan/windows.csv",
        complete / "calibration/parameters.json",
        partial / "report/report.md",
        partial / "scan/summary.csv",
        forecast / "forecast/report.md",
        forecast / "forecast/manifest.json",
        legacy / "annual_scenarios.csv",
        setup / "verification.json",
    ):
        _touch(path)
    _touch(complete / "config.yaml")
    _touch(partial / "config.yaml")

    records, index_path, json_path = build_catalog(tmp_path)

    assert [record["experiment_id"] for record in records] == [
        "apsim_smoke",
        "complete-demo",
        "forecast-demo",
        "legacy/annual",
        "partial-demo",
    ]
    assert {record["status"] for record in records} == {
        "complete",
        "partial",
        "legacy",
        "setup",
    }
    complete_record = next(
        record for record in records if record["experiment_id"] == "complete-demo"
    )
    assert complete_record["model"] == "unknown"
    assert complete_record["report_path"] == "report/report.md"
    assert complete_record["metrics_path"] == "validation/metrics.csv"
    assert complete_record["summary_path"] == "scan/summary.csv"
    assert complete_record["windows_path"] == "scan/windows.csv"
    assert complete_record["parameters_path"] == "calibration/parameters.json"
    forecast_record = next(
        record for record in records if record["experiment_id"] == "forecast-demo"
    )
    assert forecast_record["status"] == "complete"
    assert forecast_record["forecast_report_path"] == "forecast/report.md"

    assert index_path == experiments / "INDEX.md"
    assert json_path == experiments / "catalog.json"
    assert index_path.is_file()
    assert json_path.is_file()
    persisted = json.loads(json_path.read_text(encoding="utf-8"))
    assert persisted == records
    assert "| complete-demo | unknown | complete | report/report.md |" in (
        index_path.read_text(encoding="utf-8")
    )
    assert "| forecast-demo | unknown | complete | forecast/report.md |" in (
        index_path.read_text(encoding="utf-8")
    )


def test_build_catalog_reads_model_from_config(tmp_path: Path) -> None:
    experiment = tmp_path / "experiments" / "demo"
    _touch(experiment / "config.yaml")
    (experiment / "config.yaml").write_text(
        "model:\n  name: aquacrop\n",
        encoding="utf-8",
    )

    records, _, _ = build_catalog(tmp_path)

    assert records[0]["model"] == "aquacrop"


def test_build_catalog_requires_experiments_directory(tmp_path: Path) -> None:
    try:
        build_catalog(tmp_path)
    except FileNotFoundError as exc:
        assert "experiments directory is missing" in str(exc)
    else:
        raise AssertionError("expected FileNotFoundError")
