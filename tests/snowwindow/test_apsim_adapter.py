from dataclasses import replace
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from snowwindow.domain import (
    Environment,
    ManagementUnit,
    RunStatus,
    SimulationRequest,
    WeatherRecord,
)
from snowwindow.models.apsim.adapter import (
    APSIMAdapter,
    build_apsim_document,
    parse_report,
    render_met,
    render_met_batch,
)


def _request(tmp_path: Path, request_id: str = "request-1") -> SimulationRequest:
    weather = tuple(
        WeatherRecord(
            environment_id="INH1_2022",
            date=current,
            values={
                "T2M_MIN": 10.0,
                "T2M_MAX": 25.0,
                "PRECTOTCORR": 2.0,
                "ALLSKY_SFC_SW_DWN": 18.0,
                "RH2M": 60.0,
                "WS2M": 2.0,
                "PS": 98.0,
            },
        )
        for current in pd.date_range("2022-01-01", "2022-01-03").date
    )
    return SimulationRequest(
        request_id=request_id,
        environment=Environment(
            environment_id="INH1_2022",
            year=2022,
            location="INH1",
            latitude=40.48,
            longitude=-87.0,
            weather=weather,
        ),
        management=ManagementUnit(
            management_unit_id="unit-1",
            environment_id="INH1_2022",
            planting_date=date(2022, 1, 2),
            population_plants_m2=7.5,
            irrigation_assumption="rainfed_confirmed",
        ),
        start_date=date(2022, 1, 1),
        end_date=date(2022, 1, 3),
        model_parameters={
            "model_version": "2026.9.8116.0",
            "juvenile_tt": 225.0,
            "grain_number_scale": 1.2,
        },
        output_dir=tmp_path,
    )


def test_render_met_maps_g2f_weather_to_apsim_columns(tmp_path: Path) -> None:
    text = render_met(_request(tmp_path))

    assert "latitude = 40.48" in text
    assert "year day radn maxt mint rain" in text
    assert "2022 1 18.000 25.000 10.000 2.000" in text


def test_render_met_batch_merges_compatible_weather_subsets(
    tmp_path: Path,
) -> None:
    first = _request(tmp_path, "first")
    second = replace(
        first,
        request_id="second",
        environment=replace(
            first.environment,
            weather=first.environment.weather[1:],
        ),
        start_date=date(2022, 1, 2),
    )

    text = render_met_batch((first, second))

    assert text.count("2022 1 ") == 1
    assert text.count("2022 3 ") == 1


def test_build_document_sets_dates_sowing_and_cultivar_parameters(
    tmp_path: Path,
) -> None:
    document, simulation_names = build_apsim_document(
        Path(".tools/apsim/2026.9.8116.0/Examples/Maize.apsimx"),
        [_request(tmp_path)],
        weather_filename="weather.met",
    )

    simulation = next(
        child
        for child in document["Children"]
        if child.get("$type", "").startswith("Models.Core.Simulation,")
    )
    by_name = {child["Name"]: child for child in simulation["Children"]}
    assert by_name["Clock"]["Start"].startswith("2022-01-01")
    assert by_name["Clock"]["End"].startswith("2022-01-03")
    assert by_name["Weather"]["FileName"] == "weather.met"
    manager = next(
        child
        for child in by_name["Field"]["Children"]
        if child["Name"] == "Sow using a variable rule"
    )
    assert "2022, 1, 2" in "\n".join(manager["CodeArray"])
    report = next(
        child
        for child in by_name["Field"]["Children"]
        if child["Name"] == "Report"
    )
    assert report["EventNames"] == ["[Maize].Harvesting"]
    replacements = next(
        child for child in document["Children"] if child["Name"] == "Replacements"
    )
    assert replacements["$type"] == "Models.Core.Folder, Models"
    cultivar = replacements["Children"][0]
    dekalb = next(
        child
        for child in cultivar["Children"]
        if child["Name"] == "CultivarFolder"
    )["Children"]
    dekalb = next(child for child in dekalb if child["Name"] == "Dekalb_XL82")
    commands = "\n".join(dekalb["Command"])
    assert "Juvenile.Target.FixedValue = 225" in commands
    assert "PotentialMaximumGrainsPerCob.FixedValue = 660" in commands
    assert simulation_names == {simulation["Name"]: "request-1"}


def test_parse_report_maps_matured_output_and_units(tmp_path: Path) -> None:
    request = _request(tmp_path)
    report = pd.DataFrame(
        {
            "SimulationName": ["sim_0000", "sim_0000", "sim_0000"],
            "Clock.Today": ["2022-07-01", "2022-09-20", "2022-09-21"],
            "Maize.Phenology.CurrentStageName": [
                "Flowering",
                "Maturity",
                None,
            ],
            "FloweringDAS": [180.0, 180.0, 180.0],
            "MaturityDAS": [0.0, 261.0, 261.0],
            "YieldKgHa": [0.0, 9500.0, 0.0],
            "BiomassKgHa": [8000.0, 18000.0, 0.0],
        }
    )

    result = parse_report(
        report,
        {"sim_0000": request},
        adapter_version="2026.9.8116.0",
    )["request-1"]

    assert result.status is RunStatus.MATURED
    assert result.summary["flowering_proxy_dap"] == 180.0
    assert result.summary["flowering_date"] == "2022-07-01"
    assert result.summary["dry_yield_mg_ha"] == pytest.approx(9.5)
    assert result.summary["maturity_date"] == "2022-09-20"


def test_parse_report_derives_flowering_date_from_dap(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    report = pd.DataFrame(
        {
            "SimulationName": ["sim_0000"],
            "Clock.Today": ["2022-09-20"],
            "Maize.Phenology.CurrentStageName": ["Maturity"],
            "FloweringDAS": [180.0],
            "MaturityDAS": [261.0],
            "YieldKgHa": [9500.0],
            "BiomassKgHa": [18000.0],
        }
    )

    result = parse_report(
        report,
        {"sim_0000": request},
        adapter_version="2026.9.8116.0",
    )["request-1"]

    assert result.summary["flowering_date"] == "2022-07-01"


def test_parse_report_preserves_not_matured_status(tmp_path: Path) -> None:
    request = _request(tmp_path)
    report = pd.DataFrame(
        {
            "SimulationName": ["sim_0000"],
            "Clock.Today": ["2022-01-03"],
            "Maize.Phenology.CurrentStageName": ["Emerging"],
            "FloweringDAS": [0.0],
            "MaturityDAS": [0.0],
            "YieldKgHa": [0.0],
            "BiomassKgHa": [12.0],
        }
    )

    result = parse_report(
        report,
        {"sim_0000": request},
        adapter_version="2026.9.8116.0",
    )["request-1"]

    assert result.status is RunStatus.NOT_MATURED
    assert result.summary["dry_yield_mg_ha"] is None


def test_parse_report_treats_missing_harvest_event_as_not_matured(
    tmp_path: Path,
) -> None:
    request = _request(tmp_path)
    result = parse_report(
        pd.DataFrame(
            columns=[
                "SimulationName",
                "Clock.Today",
                "Maize.Phenology.CurrentStageName",
                "FloweringDAS",
                "MaturityDAS",
                "YieldKgHa",
                "BiomassKgHa",
            ]
        ),
        {"sim_0000": request},
        adapter_version="2026.9.8116.0",
    )["request-1"]

    assert result.status is RunStatus.NOT_MATURED
    assert result.failure_reason == "no harvest event before simulation end"


def test_adapter_rejects_noncontiguous_weather(tmp_path: Path) -> None:
    request = _request(tmp_path)
    broken = replace(
        request,
        environment=replace(
            request.environment,
            weather=request.environment.weather[::2],
        ),
    )

    with pytest.raises(ValueError, match="calendar day"):
        APSIMAdapter().validate(broken)
