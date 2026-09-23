from snowwindow.stages import simulate_stage


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
