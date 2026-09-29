"""Executable baseline, calibration, and validation stages."""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

import pandas as pd

from snowwindow.adapters import ModelAdapter, resolve_model_adapter
from snowwindow.calibration import (
    apply_site_offsets,
    freeze_observation_set,
    make_validation_folds,
    run_coarse_fine_calibration,
    validate_parameter_sets,
)
from snowwindow.config import ExperimentConfig
from snowwindow.data import prepare_g2f
from snowwindow.domain import FoldStrategy, ModelCapabilities
from snowwindow.experiment import (
    build_observed_requests,
    load_prepared_tables,
    select_representative_units,
)


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
    return resolve_model_adapter(config)


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


def simulate_stage(
    config: ExperimentConfig, adapter: ModelAdapter | None = None
) -> pd.DataFrame:
    """Run observed planting-date simulations and persist the baseline summary."""

    return baseline_stage(config, adapter)


def simulation_parameter_sets(
    capabilities: ModelCapabilities,
    calibrated_parameters: dict[str, float],
    site_overrides: dict[str, dict[str, float]],
) -> dict[str, dict[str, Any]]:
    """Return validation parameter groups supported by a model."""

    parameter_sets: dict[str, dict[str, Any]] = {
        "default": {},
        "calibrated": calibrated_parameters,
    }
    if capabilities.supports_site_calibration:
        parameter_sets["site_calibrated"] = {
            **calibrated_parameters,
            "site_overrides": site_overrides,
        }
    return parameter_sets


def calibration_stage(
    config: ExperimentConfig, adapter: ModelAdapter | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    _ensure_prepared(config)
    model = _adapter(config, adapter)
    tables = load_prepared_tables(config)
    eligible_ids = set(
        tables["eligibility"].loc[
            tables["eligibility"]["calibration_eligible"].astype(bool),
            "management_unit_id",
        ]
    )
    calibration_candidates = tables["management_units"].loc[
        tables["management_units"]["management_unit_id"].isin(eligible_ids)
    ]
    units = select_representative_units(
        calibration_candidates, config.selection.environments
    )
    fixed = freeze_observation_set(
        units,
        tables["observations"],
        tables["eligibility"],
        calibration_years=config.selection.calibration_years,
        environments=config.selection.environments,
    )
    evaluation_ids = set()
    if "evaluation_eligible" in tables["eligibility"]:
        evaluation_ids = set(
            tables["eligibility"].loc[
                tables["eligibility"]["evaluation_eligible"].astype(bool),
                "management_unit_id",
            ]
        )
    validation_units = select_representative_units(
        tables["management_units"].loc[
            tables["management_units"]["management_unit_id"].isin(
                evaluation_ids | eligible_ids
            )
        ],
        config.selection.environments,
    )
    request_units = (
        pd.concat([units, validation_units], ignore_index=True)
        .drop_duplicates("management_unit_id")
        .reset_index(drop=True)
    )
    requests, _ = build_observed_requests(config, units=request_units)
    calibration_units = (
        pd.concat([units, validation_units], ignore_index=True)
        .drop_duplicates("management_unit_id")
        .reset_index(drop=True)
    )
    folds = make_validation_folds(
        calibration_units,
        calibration_years=config.selection.calibration_years,
        evaluation_years=config.selection.evaluation_years,
    )
    supported_folds = set(model.capabilities.supported_folds)
    folds = tuple(
        fold
        for fold in folds
        if (fold["name"] == "held_year" and FoldStrategy.HELD_YEAR in supported_folds)
        or (
            fold["name"].startswith("leave_site_")
            and FoldStrategy.LEAVE_SITE in supported_folds
        )
    )
    parameter_rows = []
    search_frames = []
    held_year_parameters = None
    capabilities = model.capabilities
    phenology = capabilities.phenology_parameter
    yield_parameter = capabilities.yield_parameter
    phenology_parameter_name = phenology.name
    yield_parameter_name = yield_parameter.name
    default_phenology = phenology.default
    default_yield = yield_parameter.default
    phenology_coarse = config.calibration.phenology_grid
    hi0_coarse = config.calibration.yield_grid
    phenology_fine_step = config.calibration.phenology_fine_step
    yield_fine_step = config.calibration.yield_fine_step
    for fold in folds:
        if not fold["train_ids"]:
            continue
        calibrated = run_coarse_fine_calibration(
            model,
            requests,
            fixed,
            training_ids=fold["train_ids"],
            default_phenology=default_phenology,
            default_hi0=default_yield,
            phenology_coarse=phenology_coarse,
            phenology_fine_step=phenology_fine_step,
            hi0_coarse=hi0_coarse,
            hi0_fine_step=yield_fine_step,
            phenology_parameter_name=phenology_parameter_name,
            yield_parameter_name=yield_parameter_name,
        )
        fingerprints = getattr(model, "source_fingerprints", {})
        parameter_rows.append(
            {
                "fold": fold["name"],
                **calibrated.parameters,
                "train_ids": json.dumps(fold["train_ids"], separators=(",", ":")),
                "test_ids": json.dumps(fold["test_ids"], separators=(",", ":")),
                "observation_set_hash": calibrated.observation_set_hash,
                "adapter_name": model.name,
                "adapter_version": model.version,
                **dict(fingerprints),
            }
        )
        if fold["name"] == "held_year":
            held_year_parameters = parameter_rows[-1]
        search = calibrated.search.copy()
        search.insert(0, "fold", fold["name"])
        for key, value in dict(fingerprints).items():
            search[key] = value
        search_frames.append(search)
    parameters = pd.DataFrame(parameter_rows).sort_values("fold").reset_index(drop=True)
    site_offsets = pd.DataFrame()
    if held_year_parameters is not None and capabilities.supports_site_calibration:
        global_parameters = {
            phenology_parameter_name: float(
                held_year_parameters[phenology_parameter_name]
            ),
            yield_parameter_name: float(held_year_parameters[yield_parameter_name]),
        }
        training_split = {
            unit_id: "train"
            for unit_id in json.loads(held_year_parameters["train_ids"])
        }
        global_predictions, _ = validate_parameter_sets(
            model,
            requests,
            fixed,
            fold_name="site_offset_training",
            split_by_unit=training_split,
            parameter_sets={"global": global_parameters},
        )
        site_offsets = apply_site_offsets(
            fixed,
            global_predictions,
            parameter_set_id="global",
            site_parameter_set_id="site_calibrated",
            minimum_training_years=int(
                config.selection.options.get("site_offset_minimum_years", 3)
            ),
        )
    search = pd.concat(search_frames, ignore_index=True)
    root = config.experiment_dir / "calibration"
    configured_eligibility = (
        tables["eligibility"]
        .loc[
            tables["eligibility"]["environment_id"].isin(config.selection.environments)
            if config.selection.environments
            else pd.Series(True, index=tables["eligibility"].index)
        ]
        .copy()
    )
    selected_ids = set(units["management_unit_id"])
    exclusions = configured_eligibility.loc[
        ~configured_eligibility["management_unit_id"].isin(selected_ids)
    ].copy()
    exclusions["selection_reason"] = exclusions.apply(
        lambda row: (
            "ineligible"
            if not bool(row["calibration_eligible"])
            else "other_management_unit_not_representative"
        ),
        axis=1,
    )
    _atomic_table(root / "fixed_observations.parquet", fixed)
    _atomic_table(root / "exclusions.parquet", exclusions)
    _atomic_table(root / "parameters.parquet", parameters)
    _atomic_table(root / "site_offsets.parquet", site_offsets)
    _atomic_table(root / "search.parquet", search)
    _atomic_json(root / "parameters.json", parameters.to_dict("records"))
    _atomic_json(
        root / "manifest.json",
        {
            "calibration_years": config.selection.calibration_years,
            "evaluation_years": config.selection.evaluation_years,
            "selected_management_unit_ids": sorted(selected_ids),
            "fixed_observation_ids": fixed["observation_id"].tolist(),
            "grid": {
                "phenology_coarse": phenology_coarse,
                "phenology_parameter_name": phenology_parameter_name,
                "phenology_fine_step": phenology_fine_step,
                "hi0_coarse": hi0_coarse,
                "yield_parameter_name": yield_parameter_name,
                "hi0_fine_step": yield_fine_step,
            },
            "parameters": parameters.to_dict("records"),
        },
    )
    return parameters, search


def validation_stage(
    config: ExperimentConfig, adapter: ModelAdapter | None = None
) -> tuple[pd.DataFrame, pd.DataFrame]:
    model = _adapter(config, adapter)
    capabilities = model.capabilities
    root = config.experiment_dir / "calibration"
    parameter_path = root / "parameters.parquet"
    observation_path = root / "fixed_observations.parquet"
    if not parameter_path.is_file() or not observation_path.is_file():
        raise FileNotFoundError("calibration artifacts are missing")
    parameters = pd.read_parquet(parameter_path)
    site_offsets = pd.DataFrame()
    site_offset_path = root / "site_offsets.parquet"
    if site_offset_path.is_file():
        site_offsets = pd.read_parquet(site_offset_path)
    site_overrides: dict[str, dict[str, float]] = {}
    if not site_offsets.empty:
        site_overrides = {
            str(offset["site"]): {
                capabilities.site_yield_parameter: float(offset["HI0_site"]),
                capabilities.site_phenology_parameter: float(
                    offset["phenology_scale_site"]
                ),
            }
            for offset in site_offsets.to_dict("records")
        }
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
        phenology_parameter_name = capabilities.phenology_parameter.name
        yield_parameter_name = capabilities.yield_parameter.name
        calibrated_parameters = {
            phenology_parameter_name: float(row[phenology_parameter_name]),
            yield_parameter_name: float(row[yield_parameter_name]),
        }
        predictions, metrics = validate_parameter_sets(
            model,
            requests,
            observations,
            fold_name=row["fold"],
            split_by_unit=split_by_unit,
            parameter_sets=simulation_parameter_sets(
                capabilities,
                calibrated_parameters,
                site_overrides,
            ),
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
    _atomic_json(
        validation_root / "manifest.json",
        {
            "row_count": len(predictions),
            "folds": sorted(predictions["fold"].unique()),
            "parameter_sets": sorted(predictions["parameter_set_id"].unique()),
            "evaluation_labels_used_for_calibration": False,
        },
    )
    return predictions, metrics
