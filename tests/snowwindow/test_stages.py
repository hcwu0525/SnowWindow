from snowwindow.domain import ModelCapabilities
from snowwindow.stages import simulate_stage, simulation_parameter_sets


def test_simulate_stage_delegates_to_baseline(
    monkeypatch,
) -> None:
    config = object()
    adapter = object()
    seen = []

    def baseline(config, adapter=None):
        seen.append((config, adapter))

    monkeypatch.setattr("snowwindow.stages.baseline_stage", baseline)

    simulate_stage(config, adapter)  # type: ignore[arg-type]

    assert seen == [(config, adapter)]


def test_validation_omits_site_calibration_without_support() -> None:
    capabilities = ModelCapabilities(site_calibration_supported=False)

    parameter_sets = simulation_parameter_sets(
        capabilities,
        {"phenology_scale": 1.1, "HI0": 0.4},
        {"A": {"phenology_scale_site": 1.2, "HI0_site": 0.5}},
    )

    assert list(parameter_sets) == ["default", "calibrated"]
