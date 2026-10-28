"""Reproduction metadata and G2F-only weather inputs."""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path

import pandas as pd
import pytest
import yaml

from snowwindow import config as configuration
from snowwindow.cli import main
from snowwindow.config import ConfigError, ExperimentConfig, load_config
from snowwindow.experiment import WEATHER_COLUMNS, load_g2f_weather


@pytest.fixture
def experiment_config(tmp_path: Path) -> ExperimentConfig:
    config_path = tmp_path / "configs" / "example.yaml"
    config_path.parent.mkdir()
    config_path.write_text(
        """\
experiment_id: portable
data_dir: ../inputs
output_dir: ../results
model:
  name: aquacrop
  parameters:
    crop: MaizeGDD
    irrigation_smt: [70, 75, 80, 70]
selection:
  environments: [A_2022, A_2023]
  calibration_years: [2022]
  evaluation_years: [2023]
  source_experiment_id: source
simulation:
  scan_fractions: [0.90, 0.95]
  workers: 1
  scan_all_dates: true
  continuation_weather_by_environment:
    A_2022: A_2023
  parameter_sets:
    default: {}
    calibrated:
      source: calibration
""",
        encoding="utf-8",
    )
    return load_config(config_path)


def _write_weather_cache(root: Path, temperature: float = 20.0) -> list[Path]:
    paths = [
        root / "aquacrop_demo/weather/A_2022.csv",
        root / "aquacrop_crossyear/weather/A_2022_next_year.csv",
        root / "aquacrop_demo/weather_raw/A_2022.provenance.json",
        root / "aquacrop_crossyear/weather_raw/A_2022_next_year.provenance.json",
    ]
    for path, day in zip(paths[:2], ("2022-12-31", "2023-01-01"), strict=True):
        path.parent.mkdir(parents=True, exist_ok=True)
        pd.DataFrame(
            [{"Date": day, **dict.fromkeys(WEATHER_COLUMNS, temperature)}]
        ).to_csv(path, index=False)
    for path in paths[2:]:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"source": "synthetic test weather", "elevation_m": 123.0}),
            encoding="utf-8",
        )
    return paths


def test_snapshot_roundtrips_resolved_paths_and_nested_options(
    experiment_config: ExperimentConfig,
) -> None:
    path = configuration.save_config_snapshot(experiment_config)

    assert path == experiment_config.experiment_dir / "config.yaml"
    snapshot = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert snapshot["data_dir"] == str(experiment_config.data_dir)
    assert snapshot["output_dir"] == str(experiment_config.output_dir)
    assert snapshot["model"]["parameters"]["irrigation_smt"] == [70, 75, 80, 70]
    restored = load_config(path)
    assert replace(restored, source_path=experiment_config.source_path) == (
        experiment_config
    )


def test_identical_snapshot_is_not_rewritten(
    experiment_config: ExperimentConfig,
) -> None:
    path = configuration.save_config_snapshot(experiment_config)
    original = path.read_bytes()
    timestamp = path.stat().st_mtime_ns

    configuration.save_config_snapshot(experiment_config)

    assert path.read_bytes() == original
    assert path.stat().st_mtime_ns == timestamp


def test_different_configuration_cannot_replace_existing_snapshot(
    experiment_config: ExperimentConfig,
) -> None:
    path = configuration.save_config_snapshot(experiment_config)
    original = path.read_bytes()
    changed = replace(
        experiment_config,
        simulation=replace(experiment_config.simulation, workers=2),
    )

    with pytest.raises(ConfigError, match="experiment_id"):
        configuration.save_config_snapshot(changed)

    assert path.read_bytes() == original


def test_invalid_existing_snapshot_is_not_replaced(
    experiment_config: ExperimentConfig,
) -> None:
    path = experiment_config.experiment_dir / "config.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("invalid: [", encoding="utf-8")

    with pytest.raises(ConfigError):
        configuration.save_config_snapshot(experiment_config)

    assert path.read_text(encoding="utf-8") == "invalid: ["


def test_historical_outputs_without_snapshot_cannot_be_adopted(
    experiment_config: ExperimentConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = experiment_config.experiment_dir / "manifests/prepare_manifest.json"
    manifest.parent.mkdir(parents=True)
    original = '{"old_configuration": true}\n'
    manifest.write_text(original, encoding="utf-8")

    def forbidden_stage(command: str, config: ExperimentConfig) -> None:
        pytest.fail("unverified historical outputs must not reach writing stages")

    monkeypatch.setattr("snowwindow.cli._run_stage", forbidden_stage)

    assert main(["run", "--config", str(experiment_config.source_path)]) == 2
    assert not (experiment_config.experiment_dir / "config.yaml").exists()
    assert manifest.read_text(encoding="utf-8") == original


def test_snapshot_publication_failure_leaves_no_partial_file(
    experiment_config: ExperimentConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_publication(source, destination) -> None:
        raise OSError("synthetic filesystem error")

    with monkeypatch.context() as patch:
        patch.setattr(os, "link", fail_publication)
        with pytest.raises(OSError, match="synthetic filesystem error"):
            configuration.save_config_snapshot(experiment_config)

    assert list(experiment_config.experiment_dir.iterdir()) == []
    assert configuration.save_config_snapshot(experiment_config).is_file()


def test_competing_snapshot_writers_only_publish_complete_yaml(
    experiment_config: ExperimentConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    publish = os.link
    publications = []

    def inspect_publication(source, destination) -> None:
        # Competing writers must see either no snapshot or a complete document.
        restored = load_config(Path(source))
        assert restored.experiment_id == experiment_config.experiment_id
        publications.append(Path(destination))
        publish(source, destination)

    monkeypatch.setattr(os, "link", inspect_publication)
    with ThreadPoolExecutor(max_workers=4) as executor:
        paths = list(executor.map(
            lambda _: configuration.save_config_snapshot(experiment_config),
            range(8),
        ))

    assert publications
    assert len(set(paths)) == 1
    restored = replace(
        load_config(paths[0]), source_path=experiment_config.source_path
    )
    assert restored == experiment_config
    assert list(experiment_config.experiment_dir.iterdir()) == [paths[0]]


def test_cli_checks_snapshot_before_dispatching_writing_stage(
    experiment_config: ExperimentConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = []

    def stage(command: str, config: ExperimentConfig) -> None:
        assert (config.experiment_dir / "config.yaml").is_file()
        seen.append(command)

    monkeypatch.setattr("snowwindow.cli._run_stage", stage)
    assert main(["prepare", "--config", str(experiment_config.source_path)]) == 0
    snapshot = (experiment_config.experiment_dir / "config.yaml").read_bytes()
    config_path = experiment_config.source_path
    config_path.write_text(
        config_path.read_text(encoding="utf-8").replace("workers: 1", "workers: 2"),
        encoding="utf-8",
    )

    assert main(["scan", "--config", str(config_path)]) != 0
    assert seen == ["prepare"]
    assert (experiment_config.experiment_dir / "config.yaml").read_bytes() == snapshot


def test_cli_audit_remains_read_only(
    experiment_config: ExperimentConfig, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        "snowwindow.cli._run_stage", lambda command, config: {"counts": {}}
    )

    assert main(["audit", "--config", str(experiment_config.source_path)]) == 0
    assert not experiment_config.output_dir.exists()


def test_catalog_uses_configured_output_directory_not_working_directory(
    experiment_config: ExperimentConfig,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment_config.experiment_dir.mkdir(parents=True)
    working_directory = tmp_path / "elsewhere"
    working_directory.mkdir()
    monkeypatch.chdir(working_directory)

    assert main(["catalog", "--config", str(experiment_config.source_path)]) == 0
    catalog = experiment_config.output_dir / "experiments/catalog.json"
    records = json.loads(catalog.read_text(encoding="utf-8"))
    assert records[0]["experiment_id"] == "portable"
    assert not (working_directory / "outputs").exists()
    assert not (experiment_config.experiment_dir / "config.yaml").exists()


def test_catalog_rejects_missing_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "outputs/experiments").mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    assert main(["catalog", "--config", str(tmp_path / "missing.yaml")]) == 2
    assert not (tmp_path / "outputs/experiments/catalog.json").exists()


@pytest.mark.parametrize("layout", ["old", "migrated"])
def test_complete_external_weather_is_never_used_as_a_g2f_fallback(
    experiment_config: ExperimentConfig,
    layout: str,
) -> None:
    root = experiment_config.output_dir
    if layout == "migrated":
        root = root / "experiments/legacy"
    _write_weather_cache(root)

    with pytest.raises(FileNotFoundError, match="normalized/weather.parquet"):
        load_g2f_weather(experiment_config, "A_2022")
