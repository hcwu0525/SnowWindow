from datetime import date

import pytest

from snowwindow.adapters import AdapterRegistry, resolve_model_adapter
from snowwindow.domain import (
    Environment,
    ManagementUnit,
    RunStatus,
    SimulationRequest,
    SimulationResult,
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
