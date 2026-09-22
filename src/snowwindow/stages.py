"""Executable baseline, calibration, and validation stages."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from snowwindow.adapters import ModelAdapter
from snowwindow.calibration import (
    freeze_observation_set,
    make_validation_folds,
    run_coarse_fine_calibration,
    validate_parameter_sets,
)
from snowwindow.config import ExperimentConfig
from snowwindow.data import prepare_g2f
from snowwindow.experiment import (
    build_observed_requests,
    load_prepared_tables,
    select_representative_units,
)
from snowwindow.models.aquacrop import AquaCropAdapter


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


def _adapter(config: ExperimentConfig, adapter: ModelAdapter | None) -> ModelAdapter:
    if adapter is not None:
        return adapter
    if config.model.name != "aquacrop":
        raise ValueError(f"unsupported configured adapter: {config.model.name}")
    return AquaCropAdapter()


def _ensure_prepared(config: ExperimentConfig) -> None:
    marker = config.experiment_dir / "manifests/prepare_manifest.json"
    if not marker.is_file():
        prepare_g2f(config)


def _result_row(request, result) -> dict[str, Any]:
    return {
        "request_id": result.request_id,
        "management_unit_id": request.management.management_unit_id,
        "environment_id": request.environment.environment_id,
        "year": request.environment.year,
        "planting_date": request.management.planting_date.isoformat(),
        "parameter_set_id": request.parameter_set_id,
        "status": result.status.value,
        "failure_reason": result.failure_reason,
        "cache_key": result.diagnostics.get("cache_key"),
        **dict(result.summary),
    }


def baseline_stage(
    config: ExperimentConfig, adapter: ModelAdapter | None = None
) -> pd.DataFrame:
    _ensure_prepared(config)
    model = _adapter(config, adapter)
    requests, provenance = build_observed_requests(config)
    rows = [_result_row(request, model.run(request)) for request in requests.values()]
    result = pd.DataFrame(rows).sort_values("management_unit_id").reset_index(drop=True)
    _atomic_table(config.experiment_dir / "baseline/summary.parquet", result)
    _atomic_table(config.experiment_dir / "baseline/summary.csv", result)
    _atomic_table(
        config.experiment_dir / "baseline/weather_provenance.parquet", provenance
    )
    return result


def calibration_stage(
    config: ExperimentConfig, adapter: ModelAdapter | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    _ensure_prepared(config)
    model = _adapter(config, adapter)
    tables = load_prepared_tables(config)
    units = select_representative_units(
        tables["management_units"], config.selection.environments
    )
    fixed = freeze_observation_set(
        units,
        tables["observations"],
        tables["eligibility"],
        calibration_years=config.selection.calibration_years,
        environments=config.selection.environments,
    )
    requests, _ = build_observed_requests(config)
    folds = make_validation_folds(
        units,
        calibration_years=config.selection.calibration_years,
        evaluation_years=config.selection.evaluation_years,
    )
    parameter_rows = []
    search_frames = []
    for fold in folds:
        if not fold["train_ids"]:
            continue
        calibrated = run_coarse_fine_calibration(
            model,
            requests,
            fixed,
            training_ids=fold["train_ids"],
        )
        parameter_rows.append(
            {
                "fold": fold["name"],
                **calibrated.parameters,
                "train_ids": json.dumps(fold["train_ids"], separators=(",", ":")),
                "test_ids": json.dumps(fold["test_ids"], separators=(",", ":")),
                "observation_set_hash": calibrated.observation_set_hash,
                "adapter_name": model.name,
                "adapter_version": model.version,
            }
        )
        search = calibrated.search.copy()
        search.insert(0, "fold", fold["name"])
        search_frames.append(search)
    parameters = pd.DataFrame(parameter_rows).sort_values("fold").reset_index(drop=True)
    search = pd.concat(search_frames, ignore_index=True)
    root = config.experiment_dir / "calibration"
    _atomic_table(root / "fixed_observations.parquet", fixed)
    _atomic_table(root / "parameters.parquet", parameters)
    _atomic_table(root / "search.parquet", search)
    _atomic_json(root / "parameters.json", parameters.to_dict("records"))
    return parameters, search


def validation_stage(
    config: ExperimentConfig, adapter: ModelAdapter | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    model = _adapter(config, adapter)
    root = config.experiment_dir / "calibration"
    parameter_path = root / "parameters.parquet"
    observation_path = root / "fixed_observations.parquet"
    if not parameter_path.is_file() or not observation_path.is_file():
        raise FileNotFoundError("calibration artifacts are missing")
    parameters = pd.read_parquet(parameter_path)
    tables = load_prepared_tables(config)
    observations = tables["observations"].copy()
    observations["observation_id"] = (
        observations["management_unit_id"].astype(str)
        + "::"
        + observations["variable"].astype(str)
    )
    requests, _ = build_observed_requests(config)
    prediction_frames = []
    metric_frames = []
    for row in parameters.to_dict("records"):
        train_ids = tuple(json.loads(row["train_ids"]))
        test_ids = tuple(json.loads(row["test_ids"]))
        split_by_unit = {unit_id: "train" for unit_id in train_ids}
        split_by_unit.update({unit_id: "test" for unit_id in test_ids})
        selected_ids = set(requests).intersection(split_by_unit)
        split_by_unit = {
            unit_id: split_by_unit[unit_id] for unit_id in sorted(selected_ids)
        }
        predictions, metrics = validate_parameter_sets(
            model,
            requests,
            observations,
            fold_name=row["fold"],
            split_by_unit=split_by_unit,
            parameter_sets={
                "default": {},
                "calibrated": {
                    "phenology_scale": float(row["phenology_scale"]),
                    "HI0": float(row["HI0"]),
                },
            },
        )
        prediction_frames.append(predictions)
        metric_frames.append(metrics)
    predictions = pd.concat(prediction_frames, ignore_index=True)
    metrics = pd.concat(metric_frames, ignore_index=True)
    validation_root = config.experiment_dir / "validation"
    _atomic_table(validation_root / "predictions.parquet", predictions)
    _atomic_table(validation_root / "predictions.csv", predictions)
    _atomic_table(validation_root / "metrics.parquet", metrics)
    _atomic_table(validation_root / "metrics.csv", metrics)
    return predictions, metrics
