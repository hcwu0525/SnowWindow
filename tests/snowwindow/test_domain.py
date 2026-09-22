from datetime import date
from pathlib import Path

import pytest

from snowwindow.domain import (
    Environment,
    ManagementUnit,
    Observation,
    RunStatus,
    SimulationRequest,
    SimulationResult,
    SoilLayer,
    WeatherRecord,
)


def _request(parameter_order: tuple[str, str] = ("phenology_scale", "hi0")):
    weather = WeatherRecord(
        environment_id="INH1_2022",
        date=date(2022, 5, 10),
        values={"rain_mm": 2.5, "tmax_c": 24.0},
        source="G2F",
    )
    soil = SoilLayer(
        top_depth_m=0.0,
        bottom_depth_m=0.3,
        properties={"clay_fraction": 0.25, "field_capacity": 0.31},
        source="measured",
    )
    environment = Environment(
        environment_id="INH1_2022",
        year=2022,
        location="INH1",
        latitude=40.0,
        longitude=-86.0,
        weather=(weather,),
        soil=(soil,),
        metadata={"soil_source": "measured"},
    )
    management = ManagementUnit(
        management_unit_id="unit-1",
        environment_id="INH1_2022",
        planting_date=date(2022, 5, 10),
        cultivar_id="generic_maize",
        population_plants_m2=8.0,
        irrigation_assumption="rainfed",
    )
    parameters = {
        parameter_order[0]: 1.1 if parameter_order[0] == "phenology_scale" else 0.48,
        parameter_order[1]: 1.1 if parameter_order[1] == "phenology_scale" else 0.48,
    }
    return SimulationRequest(
        request_id="request-1",
        environment=environment,
        management=management,
        model_parameters=parameters,
        start_date=date(2022, 4, 1),
        end_date=date(2022, 12, 31),
        output_dir=Path("runs/request-1"),
    )


def test_domain_records_serialize_to_json_compatible_values() -> None:
    request = _request()
    observation = Observation(
        observation_id="obs-1",
        management_unit_id="unit-1",
        variable="yield_mg_ha",
        value=10.25,
        unit="Mg/ha",
        observed_on=date(2022, 10, 15),
        source_ids=("plot-2", "plot-1"),
    )
    result = SimulationResult(
        request_id=request.request_id,
        adapter_name="aquacrop",
        adapter_version="3.1.0",
        status=RunStatus.NOT_MATURED,
        summary={"biomass_mg_ha": 15.0},
        artifacts={"daily": Path("tables/daily.parquet")},
        diagnostics={"last_date": date(2022, 12, 31)},
        failure_reason="calendar ended before maturity",
    )

    request_dict = request.to_dict()
    observation_dict = observation.to_json_dict()
    result_dict = result.to_dict()

    assert request_dict["environment"]["weather"][0]["date"] == "2022-05-10"
    assert request_dict["management"]["planting_date"] == "2022-05-10"
    assert request_dict["output_dir"] == "runs/request-1"
    assert observation_dict["observed_on"] == "2022-10-15"
    assert observation_dict["source_ids"] == ["plot-2", "plot-1"]
    assert result_dict["status"] == "not_matured"
    assert result_dict["artifacts"] == {"daily": "tables/daily.parquet"}
    assert result_dict["diagnostics"] == {"last_date": "2022-12-31"}


def test_domain_records_are_deeply_immutable_and_hash_mapping_keys_stably() -> None:
    first = _request(("phenology_scale", "hi0"))
    second = _request(("hi0", "phenology_scale"))

    with pytest.raises(TypeError):
        first.model_parameters["hi0"] = 0.5

    assert first == second
    assert hash(first) == hash(second)
    assert first.content_hash() == second.content_hash()


def test_run_status_contains_all_terminal_states() -> None:
    assert [status.value for status in RunStatus] == [
        "matured",
        "crop_died",
        "not_germinated",
        "not_matured",
        "insufficient_thermal_time",
        "model_limit",
        "invalid_input",
        "execution_failed",
    ]
