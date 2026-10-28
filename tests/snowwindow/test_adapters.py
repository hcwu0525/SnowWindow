from datetime import date

import pytest

from snowwindow.adapters import (
    AdapterRegistry,
    default_adapter_registry,
    resolve_model_adapter,
)
from snowwindow.domain import (
    Environment,
    FoldStrategy,
    ManagementUnit,
    RunStatus,
    ScanRequestStrategy,
    SimulationRequest,
    SimulationResult,
    WeatherStrategy,
)


class StubAdapter:
    name = "stub"
    version = "1.0"

    def validate(self, request: SimulationRequest) -> None:
        if request.end_date < request.start_date:
            raise ValueError("end date precedes start date")

    def run(self, request: SimulationRequest) -> SimulationResult:
        self.validate(request)
        return SimulationResult(
            request_id=request.request_id,
            adapter_name=self.name,
            adapter_version=self.version,
            status=RunStatus.MATURED,
        )


def _request() -> SimulationRequest:
    return SimulationRequest(
        request_id="request-1",
        environment=Environment(
            environment_id="INH1_2022",
            year=2022,
            location="INH1",
            latitude=40.0,
            longitude=-86.0,
        ),
        management=ManagementUnit(
            management_unit_id="unit-1",
            environment_id="INH1_2022",
            planting_date=date(2022, 5, 10),
        ),
        start_date=date(2022, 4, 1),
        end_date=date(2022, 12, 31),
    )


def test_registry_registers_and_runs_adapter() -> None:
    registry = AdapterRegistry()
    adapter = StubAdapter()

    registry.register(adapter)

    assert registry.names() == ("stub",)
    assert registry.get("stub") is adapter
    assert registry.get("stub").run(_request()).status is RunStatus.MATURED


def test_registry_rejects_duplicate_adapter_names() -> None:
    registry = AdapterRegistry([StubAdapter()])

    with pytest.raises(ValueError, match="already registered"):
        registry.register(StubAdapter())


def test_registry_unknown_adapter_error_lists_available_names() -> None:
    registry = AdapterRegistry([StubAdapter()])

    with pytest.raises(KeyError, match=r"missing.*stub"):
        registry.get("missing")


def test_resolve_model_adapter_uses_registry_and_config_name() -> None:
    adapter = StubAdapter()
    registry = AdapterRegistry([adapter])
    config = type("Config", (), {"model": type("Model", (), {"name": "stub"})})()

    assert resolve_model_adapter(config, registry) is adapter


def test_resolve_model_adapter_reports_unknown_configured_model() -> None:
    config = type("Config", (), {"model": type("Model", (), {"name": "missing"})})()

    with pytest.raises(ValueError, match="unknown configured model.*stub"):
        resolve_model_adapter(config, AdapterRegistry([StubAdapter()]))


def test_default_registry_includes_all_crop_models() -> None:
    registry = default_adapter_registry()

    assert registry.names() == ("apsim", "aquacrop", "dssat")


def test_builtin_model_capabilities_declare_calibration_contracts() -> None:
    registry = default_adapter_registry()
    aquacrop = registry.get("aquacrop").capabilities
    apsim = registry.get("apsim").capabilities
    dssat = registry.get("dssat").capabilities

    assert aquacrop.phenology_parameter.name == "phenology_scale"
    assert aquacrop.yield_parameter.name == "HI0"
    assert aquacrop.phenology_parameter.default == 1.0
    assert aquacrop.yield_parameter.default == 0.48
    assert aquacrop.phenology_parameter.coarse_grid == (0.8, 1.2, 0.02)
    assert aquacrop.yield_parameter.coarse_grid == (0.35, 0.55, 0.01)
    assert aquacrop.phenology_parameter.fine_step == 0.005
    assert aquacrop.yield_parameter.fine_step == 0.0025
    assert aquacrop.supports_site_calibration is True
    assert aquacrop.site_phenology_parameter == "phenology_scale_site"
    assert aquacrop.site_yield_parameter == "HI0_site"
    assert aquacrop.supported_folds == (
        FoldStrategy.HELD_YEAR,
        FoldStrategy.LEAVE_SITE,
    )
    assert aquacrop.weather_strategy is WeatherStrategy.G2F
    assert aquacrop.scan_request_strategy is ScanRequestStrategy.PER_DATE

    assert apsim.phenology_parameter.name == "juvenile_tt"
    assert apsim.yield_parameter.name == "grain_number_scale"
    assert apsim.phenology_parameter.default == 211.0
    assert apsim.yield_parameter.default == 1.0
    assert apsim.phenology_parameter.coarse_grid == (100.0, 350.0, 25.0)
    assert apsim.yield_parameter.coarse_grid == (0.5, 1.5, 0.1)
    assert apsim.phenology_parameter.fine_step == 5.0
    assert apsim.yield_parameter.fine_step == 0.02
    assert apsim.supports_site_calibration is False
    assert apsim.supported_folds == (FoldStrategy.HELD_YEAR,)
    assert apsim.weather_strategy is WeatherStrategy.G2F
    assert apsim.scan_request_strategy is ScanRequestStrategy.PER_DATE

    assert dssat.phenology_parameter.name == "P1"
    assert dssat.yield_parameter.name == "G2"
    assert dssat.phenology_parameter.default == 259.0
    assert dssat.yield_parameter.default == 924.3
    assert dssat.phenology_parameter.coarse_grid == (150.0, 350.0, 50.0)
    assert dssat.yield_parameter.coarse_grid == (700.0, 950.0, 50.0)
    assert dssat.phenology_parameter.fine_step == 10.0
    assert dssat.yield_parameter.fine_step == 10.0
    assert dssat.supports_site_calibration is False
    assert dssat.supported_folds == (FoldStrategy.HELD_YEAR,)
    assert dssat.weather_strategy is WeatherStrategy.G2F
    assert dssat.scan_request_strategy is ScanRequestStrategy.SLICE_WEATHER_HORIZON


def test_model_capabilities_declare_display_and_report_notes() -> None:
    registry = default_adapter_registry()

    assert registry.get("aquacrop").capabilities.display_name == "AquaCrop"
    assert registry.get("apsim").capabilities.display_name == "APSIM"
    assert registry.get("dssat").capabilities.display_name == "DSSAT"
    for adapter in registry.names():
        capabilities = registry.get(adapter).capabilities
        assert capabilities.report_notes
        assert all(note.strip() for note in capabilities.report_notes)
