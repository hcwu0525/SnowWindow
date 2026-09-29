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


def test_apsim_validation_omits_site_calibrated_parameter_set() -> None:
    parameter_sets = simulation_parameter_sets(
        "apsim",
        {"juvenile_tt": 150.0, "grain_number_scale": 1.2},
        {},
    )

    assert parameter_sets == {
        "default": {},
        "calibrated": {"juvenile_tt": 150.0, "grain_number_scale": 1.2},
    }
