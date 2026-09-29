"""Deterministic calibration and validation primitives."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import Any

import numpy as np
import pandas as pd

from snowwindow.adapters import ModelAdapter
from snowwindow.domain import RunStatus, SimulationRequest

CALIBRATION_VARIABLES = ("pollen_dap", "dry_yield_mg_ha")


@dataclass(frozen=True)
class CalibrationResult:
    parameters: dict[str, float]
    search: pd.DataFrame
    observation_set_hash: str


@dataclass(frozen=True)
class FoldCalibrationResult:
    parameters: pd.DataFrame
    search: pd.DataFrame
    predictions: pd.DataFrame
    metrics: pd.DataFrame


def parameter_grid(lower: float, upper: float, step: float) -> tuple[float, ...]:
    """Build an inclusive decimal-stable parameter grid."""

    start = Decimal(str(lower))
    stop = Decimal(str(upper))
    increment = Decimal(str(step))
    if increment <= 0 or stop < start:
        raise ValueError("parameter grid requires 0 < step and lower <= upper")
    count = int((stop - start) // increment)
    values = [start + increment * index for index in range(count + 1)]
    if values[-1] != stop:
        values.append(stop)
    return tuple(float(value) for value in values)


def refined_grid(
    selected: float,
    *,
    lower: float,
    upper: float,
    radius: float,
    step: float,
) -> tuple[float, ...]:
    center = Decimal(str(selected))
    delta = Decimal(str(radius))
    start = max(Decimal(str(lower)), center - delta)
    stop = min(Decimal(str(upper)), center + delta)
    return parameter_grid(float(start), float(stop), step)


def freeze_observation_set(
    management_units: pd.DataFrame,
    observations: pd.DataFrame,
    eligibility: pd.DataFrame,
    *,
    calibration_years: tuple[int, ...],
    environments: tuple[str, ...] = (),
) -> pd.DataFrame:
    """Return the immutable, ordered observations used for calibration."""

    required_unit = {"management_unit_id", "environment_id", "year"}
    required_observation = {"management_unit_id", "variable", "value"}
    required_eligibility = {"management_unit_id", "calibration_eligible"}
    for frame, required, name in (
        (management_units, required_unit, "management_units"),
        (observations, required_observation, "observations"),
        (eligibility, required_eligibility, "eligibility"),
    ):
        missing = sorted(required - set(frame))
        if missing:
            raise ValueError(f"{name} is missing columns: {missing}")

    eligible_ids = set(
        eligibility.loc[
            eligibility["calibration_eligible"].astype(bool), "management_unit_id"
        ].astype(str)
    )
    units = management_units.loc[
        management_units["management_unit_id"].astype(str).isin(eligible_ids)
        & management_units["year"].isin(calibration_years)
    ].copy()
    if environments:
        units = units.loc[units["environment_id"].isin(environments)]
    unit_columns = ["management_unit_id", "environment_id", "year"]
    frozen = observations.loc[
        observations["management_unit_id"].isin(units["management_unit_id"])
        & observations["variable"].isin(CALIBRATION_VARIABLES)
        & pd.to_numeric(observations["value"], errors="coerce").notna()
    ].merge(units[unit_columns], on="management_unit_id", validate="many_to_one")
    frozen["value"] = pd.to_numeric(frozen["value"], errors="raise").astype(float)
    frozen["observation_id"] = (
        frozen["management_unit_id"].astype(str) + "::" + frozen["variable"].astype(str)
    )
    if frozen["observation_id"].duplicated().any():
        raise ValueError("calibration observation IDs must be unique")
    return frozen.sort_values("observation_id").reset_index(drop=True)


def observation_set_hash(observations: pd.DataFrame) -> str:
    columns = ["observation_id", "management_unit_id", "variable", "value"]
    payload = observations[columns].sort_values("observation_id").to_dict("records")
    encoded = json.dumps(
        payload, allow_nan=False, separators=(",", ":"), sort_keys=True
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def select_parameter(
    predictions: pd.DataFrame,
    *,
    parameter_name: str,
    default: float,
    expected_observation_ids: tuple[str, ...],
) -> tuple[float, pd.DataFrame]:
    """Select the lowest-MAE candidate without dropping failed observations."""

    expected = set(expected_observation_ids)
    rows: list[dict[str, Any]] = []
    for value, group in predictions.groupby(parameter_name, sort=True):
        identifiers = group["observation_id"].astype(str)
        unique = not identifiers.duplicated().any()
        complete = (
            unique and set(identifiers) == expected and len(group) == len(expected)
        )
        numeric_observed = pd.to_numeric(group["observed_value"], errors="coerce")
        numeric_predicted = pd.to_numeric(group["predicted_value"], errors="coerce")
        matured = group["status"].eq(RunStatus.MATURED.value)
        usable = (
            complete
            and int(matured.sum()) > 0
            and numeric_observed.loc[matured].map(math.isfinite).all()
            and numeric_predicted.loc[matured].map(math.isfinite).all()
        )
        loss = (
            float(
                np.abs(
                    numeric_predicted.loc[matured] - numeric_observed.loc[matured]
                ).mean()
            )
            if usable
            else float("inf")
        )
        rows.append(
            {
                parameter_name: float(value),
                "objective_mae": loss,
                "expected_count": len(expected),
                "valid_count": int((matured & numeric_predicted.notna()).sum()),
                "valid": bool(usable),
            }
        )
    scores = pd.DataFrame(rows).sort_values(parameter_name).reset_index(drop=True)
    finite = scores.loc[np.isfinite(scores["objective_mae"])]
    if finite.empty:
        raise ValueError("no calibration candidate is valid on the fixed target set")
    selected = min(
        finite.to_dict("records"),
        key=lambda row: (
            round(float(row["objective_mae"]), 12),
            abs(float(row[parameter_name]) - default),
            float(row[parameter_name]),
        ),
    )
    return float(selected[parameter_name]), scores


def compute_metrics(
    predictions: pd.DataFrame, *, expected_count: int | None = None
) -> dict[str, float | int | None]:
    expected = len(predictions) if expected_count is None else expected_count
    observed = pd.to_numeric(predictions["observed_value"], errors="coerce")
    predicted = pd.to_numeric(predictions["predicted_value"], errors="coerce")
    usable = (
        predictions["status"].eq(RunStatus.MATURED.value)
        & observed.notna()
        & predicted.notna()
    )
    residual = predicted.loc[usable].to_numpy() - observed.loc[usable].to_numpy()
    return {
        "n": int(usable.sum()),
        "expected_count": int(expected),
        "coverage": float(usable.sum() / expected) if expected else 0.0,
        "mae": float(np.abs(residual).mean()) if len(residual) else None,
        "rmse": float(np.sqrt(np.mean(residual**2))) if len(residual) else None,
        "bias": float(residual.mean()) if len(residual) else None,
    }


def make_validation_folds(
    management_units: pd.DataFrame,
    *,
    calibration_years: tuple[int, ...],
    evaluation_years: tuple[int, ...],
) -> tuple[dict[str, Any], ...]:
    units = management_units.copy()
    units["site"] = units["environment_id"].astype(str).str.rsplit("_", n=1).str[0]
    calibration = units.loc[units["year"].isin(calibration_years)]
    evaluation = units.loc[units["year"].isin(evaluation_years)]
    folds: list[dict[str, Any]] = [
        {
            "name": "held_year",
            "train_ids": tuple(sorted(calibration["management_unit_id"].astype(str))),
            "test_ids": tuple(sorted(evaluation["management_unit_id"].astype(str))),
        }
    ]
    for site in sorted(calibration["site"].unique()):
        folds.append(
            {
                "name": f"leave_site_{site}",
                "train_ids": tuple(
                    sorted(
                        calibration.loc[
                            calibration["site"].ne(site), "management_unit_id"
                        ].astype(str)
                    )
                ),
                "test_ids": tuple(
                    sorted(
                        calibration.loc[
                            calibration["site"].eq(site), "management_unit_id"
                        ].astype(str)
                    )
                ),
            }
        )
    return tuple(folds)


def _prediction_rows(
    adapter: ModelAdapter,
    requests: dict[str, SimulationRequest],
    observations: pd.DataFrame,
    *,
    parameter_name: str,
    parameter_values: tuple[float, ...],
    fixed_parameters: dict[str, float],
    prediction_name: str,
) -> pd.DataFrame:
    rows = []
    for value in parameter_values:
        ordered_observations = observations.sort_values("observation_id").to_dict(
            "records"
        )
        for observation in ordered_observations:
            unit_id = str(observation["management_unit_id"])
            request = requests[unit_id]
            parameters = {
                **dict(request.model_parameters),
                **fixed_parameters,
                parameter_name: float(value),
            }
            candidate = replace(
                request,
                request_id=f"{request.request_id}:{parameter_name}={value}",
                model_parameters=parameters,
            )
            result = adapter.run(candidate)
            rows.append(
                {
                    "observation_id": observation["observation_id"],
                    "management_unit_id": unit_id,
                    parameter_name: float(value),
                    "status": result.status.value,
                    "predicted_value": result.summary.get(prediction_name),
                    "observed_value": float(observation["value"]),
                    "cache_key": result.diagnostics.get("cache_key"),
                    "failure_reason": result.failure_reason,
                }
            )
    return pd.DataFrame(rows)


def run_two_stage_calibration(
    adapter: ModelAdapter,
    requests: dict[str, SimulationRequest],
    observations: pd.DataFrame,
    *,
    training_ids: tuple[str, ...],
    phenology_values: tuple[float, ...],
    hi0_values: tuple[float, ...],
    default_phenology: float,
    default_hi0: float,
    phenology_parameter_name: str = "phenology_scale",
    yield_parameter_name: str = "HI0",
) -> CalibrationResult:
    training = observations.loc[
        observations["management_unit_id"].isin(training_ids)
    ].copy()
    flowering = training.loc[training["variable"].eq("pollen_dap")]
    yield_observations = training.loc[training["variable"].eq("dry_yield_mg_ha")]
    if flowering.empty or yield_observations.empty:
        raise ValueError("calibration requires flowering and dry-yield observations")

    flowering_predictions = _prediction_rows(
        adapter,
        requests,
        flowering,
        parameter_name=phenology_parameter_name,
        parameter_values=phenology_values,
        fixed_parameters={yield_parameter_name: default_hi0},
        prediction_name="flowering_proxy_dap",
    )
    phenology, phenology_scores = select_parameter(
        flowering_predictions,
        parameter_name=phenology_parameter_name,
        default=default_phenology,
        expected_observation_ids=tuple(flowering["observation_id"]),
    )
    phenology_scores.insert(0, "phase", "phenology")

    yield_predictions = _prediction_rows(
        adapter,
        requests,
        yield_observations,
        parameter_name=yield_parameter_name,
        parameter_values=hi0_values,
        fixed_parameters={phenology_parameter_name: phenology},
        prediction_name="dry_yield_mg_ha",
    )
    hi0, yield_scores = select_parameter(
        yield_predictions,
        parameter_name=yield_parameter_name,
        default=default_hi0,
        expected_observation_ids=tuple(yield_observations["observation_id"]),
    )
    yield_scores.insert(0, "phase", "yield")
    search = pd.concat(
        [
            phenology_scores.rename(
                columns={phenology_parameter_name: "parameter_value"}
            ),
            yield_scores.rename(columns={yield_parameter_name: "parameter_value"}),
        ],
        ignore_index=True,
    )
    search["parameter_name"] = search["phase"].map(
        {
            "phenology": phenology_parameter_name,
            "yield": yield_parameter_name,
        }
    )
    search = search[
        [
            "phase",
            "parameter_name",
            "parameter_value",
            "objective_mae",
            "expected_count",
            "valid_count",
            "valid",
        ]
    ]
    return CalibrationResult(
        parameters={
            phenology_parameter_name: phenology,
            yield_parameter_name: hi0,
        },
        search=search,
        observation_set_hash=observation_set_hash(training),
    )


def run_coarse_fine_calibration(
    adapter: ModelAdapter,
    requests: dict[str, SimulationRequest],
    observations: pd.DataFrame,
    *,
    training_ids: tuple[str, ...],
    default_phenology: float = 1.0,
    default_hi0: float = 0.48,
    phenology_coarse: tuple[float, float, float] = (0.8, 1.2, 0.02),
    phenology_fine_step: float = 0.005,
    hi0_coarse: tuple[float, float, float] = (0.35, 0.55, 0.01),
    hi0_fine_step: float = 0.0025,
    phenology_parameter_name: str = "phenology_scale",
    yield_parameter_name: str = "HI0",
) -> CalibrationResult:
    coarse = run_two_stage_calibration(
        adapter,
        requests,
        observations,
        training_ids=training_ids,
        phenology_values=parameter_grid(*phenology_coarse),
        hi0_values=parameter_grid(*hi0_coarse),
        default_phenology=default_phenology,
        default_hi0=default_hi0,
        phenology_parameter_name=phenology_parameter_name,
        yield_parameter_name=yield_parameter_name,
    )
    fine = run_two_stage_calibration(
        adapter,
        requests,
        observations,
        training_ids=training_ids,
        phenology_values=refined_grid(
            coarse.parameters[phenology_parameter_name],
            lower=phenology_coarse[0],
            upper=phenology_coarse[1],
            radius=phenology_coarse[2],
            step=phenology_fine_step,
        ),
        hi0_values=refined_grid(
            coarse.parameters[yield_parameter_name],
            lower=hi0_coarse[0],
            upper=hi0_coarse[1],
            radius=hi0_coarse[2],
            step=hi0_fine_step,
        ),
        default_phenology=default_phenology,
        default_hi0=default_hi0,
        phenology_parameter_name=phenology_parameter_name,
        yield_parameter_name=yield_parameter_name,
    )
    coarse_search = coarse.search.copy()
    coarse_search["resolution"] = "coarse"
    fine_search = fine.search.copy()
    fine_search["resolution"] = "fine"
    combined = pd.concat([coarse_search, fine_search], ignore_index=True)
    combined["invalid_count"] = combined["expected_count"] - combined["valid_count"]
    combined["selected"] = (
        combined["phase"].eq("phenology")
        & combined["parameter_value"].eq(
            fine.parameters[phenology_parameter_name]
        )
    ) | (
        combined["phase"].eq("yield")
        & combined["parameter_value"].eq(fine.parameters[yield_parameter_name])
        & combined["resolution"].eq("fine")
    )
    combined["boundary"] = (
        combined["phase"].eq("phenology")
        & combined["parameter_value"].isin([phenology_coarse[0], phenology_coarse[1]])
    ) | (
        combined["phase"].eq("yield")
        & combined["parameter_value"].isin([hi0_coarse[0], hi0_coarse[1]])
    )
    combined[f"effective_{phenology_parameter_name}"] = fine.parameters[
        phenology_parameter_name
    ]
    combined[f"effective_{yield_parameter_name}"] = fine.parameters[
        yield_parameter_name
    ]
    return CalibrationResult(
        parameters=fine.parameters,
        search=combined,
        observation_set_hash=fine.observation_set_hash,
    )


def validate_parameter_sets(
    adapter: ModelAdapter,
    requests: dict[str, SimulationRequest],
    observations: pd.DataFrame,
    *,
    fold_name: str,
    split_by_unit: dict[str, str],
    parameter_sets: dict[str, dict[str, float]],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run complete row-level validation and aggregate metrics."""

    observation_map = observations.set_index(["management_unit_id", "variable"])
    prediction_names = {
        "pollen_dap": "flowering_proxy_dap",
        "dry_yield_mg_ha": "dry_yield_mg_ha",
    }
    rows: list[dict[str, Any]] = []
    for parameter_set_id, parameters in sorted(parameter_sets.items()):
        for unit_id in sorted(split_by_unit):
            request = requests[unit_id]
            if request is None:
                continue
            model_parameters = {**dict(request.model_parameters), **parameters}
            site_overrides = dict(parameters.get("site_overrides", {}))
            if site_overrides:
                site = request.environment.environment_id.rsplit("_", 1)[0]
                if site in site_overrides:
                    model_parameters.update(site_overrides[site])
            model_parameters.pop("site_overrides", None)
            result = adapter.run(
                replace(
                    request,
                    request_id=f"{request.request_id}:validation:{parameter_set_id}",
                    parameter_set_id=parameter_set_id,
                    model_parameters=model_parameters,
                )
            )
            for variable, prediction_name in prediction_names.items():
                key = (unit_id, variable)
                observed = (
                    float(observation_map.loc[key, "value"])
                    if key in observation_map.index
                    else None
                )
                rows.append(
                    {
                        "observation_id": f"{unit_id}::{variable}",
                        "fold": fold_name,
                        "split": split_by_unit[unit_id],
                        "parameter_set_id": parameter_set_id,
                        "management_unit_id": unit_id,
                        "environment_id": request.environment.environment_id,
                        "site": request.environment.environment_id.rsplit("_", 1)[0],
                        "year": request.environment.year,
                        "variable": variable,
                        "observed_value": observed,
                        "predicted_value": result.summary.get(prediction_name),
                        "residual": (
                            result.summary.get(prediction_name) - observed
                            if observed is not None
                            and result.summary.get(prediction_name) is not None
                            else None
                        ),
                        "status": result.status.value,
                        "request_id": result.request_id,
                        "failure_reason": result.failure_reason,
                        "cache_key": result.diagnostics.get("cache_key"),
                    }
                )
    predictions = pd.DataFrame(rows)
    metric_rows = []
    for keys, group in predictions.groupby(
        ["fold", "split", "parameter_set_id", "variable"], sort=True
    ):
        metrics = compute_metrics(group, expected_count=len(group))
        metric_rows.append(
            dict(
                zip(("fold", "split", "parameter_set_id", "variable"), keys),
                **metrics,
            )
        )
    return predictions, pd.DataFrame(metric_rows)


def apply_site_offsets(
    observations: pd.DataFrame,
    global_predictions: pd.DataFrame,
    *,
    parameter_set_id: str,
    site_parameter_set_id: str,
    minimum_training_years: int = 3,
    maximum_scale: float = 2.0,
) -> pd.DataFrame:
    """Derive conservative HI0 and phenology multipliers for mature sites."""

    if parameter_set_id not in set(global_predictions["parameter_set_id"]):
        raise ValueError("global predictions are missing for site offsets")
    required = {
        "management_unit_id",
        "environment_id",
        "parameter_set_id",
        "status",
        "observed_value",
        "predicted_value",
    }
    missing = sorted(required - set(global_predictions))
    if missing:
        raise ValueError(f"global predictions are missing columns: {missing}")
    if site_parameter_set_id == parameter_set_id:
        raise ValueError("site parameter set must differ from global parameter set")
    if minimum_training_years < 1 or not 0 < maximum_scale <= 4:
        raise ValueError("site-offset bounds are invalid")

    usable = global_predictions.loc[
        global_predictions["parameter_set_id"].eq(parameter_set_id)
        & global_predictions["status"].eq(RunStatus.MATURED.value)
    ].copy()
    usable["site"] = usable["environment_id"].astype(str).str.rsplit("_", n=1).str[0]
    usable["observation_id"] = (
        usable["management_unit_id"].astype(str) + "::" + usable["variable"]
    )
    training_observation_ids = set(
        observations.loc[
            observations["variable"].isin(CALIBRATION_VARIABLES), "observation_id"
        ]
    )
    usable = usable.loc[usable["observation_id"].isin(training_observation_ids)].copy()
    rows = []
    for site, group in usable.groupby("site", sort=True):
        years = sorted(group["year"].unique())
        if len(years) < minimum_training_years:
            continue
        yield_group = group.loc[group["variable"].eq("dry_yield_mg_ha")]
        flowering_group = group.loc[group["variable"].eq("pollen_dap")]
        hi0_site = (
            float(
                (
                    pd.to_numeric(yield_group["observed_value"], errors="coerce")
                    / pd.to_numeric(yield_group["predicted_value"], errors="coerce")
                )
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .median()
            )
            if not yield_group.empty
            else 1.0
        )
        phenology_site = (
            float(
                (
                    pd.to_numeric(flowering_group["observed_value"], errors="coerce")
                    / pd.to_numeric(flowering_group["predicted_value"], errors="coerce")
                )
                .replace([np.inf, -np.inf], np.nan)
                .dropna()
                .median()
            )
            if not flowering_group.empty
            else 1.0
        )
        if not math.isfinite(hi0_site) or hi0_site <= 0:
            hi0_site = 1.0
        if not math.isfinite(phenology_site) or phenology_site <= 0:
            phenology_site = 1.0
        hi0_site = min(max(hi0_site, 1.0 / maximum_scale), maximum_scale)
        phenology_site = min(max(phenology_site, 1.0 / maximum_scale), maximum_scale)
        train_ids = sorted(group["management_unit_id"].astype(str).unique())
        rows.append(
            {
                "fold": f"site_offset_{site}",
                "site": site,
                "HI0_site": hi0_site,
                "phenology_scale_site": phenology_site,
                "training_years": len(years),
                "train_ids": json.dumps(train_ids, separators=(",", ":")),
                "test_ids": json.dumps(train_ids, separators=(",", ":")),
                "parameter_set_id": site_parameter_set_id,
                "base_parameter_set_id": parameter_set_id,
            }
        )
    return pd.DataFrame(rows)
