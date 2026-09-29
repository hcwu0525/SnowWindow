from pathlib import Path

import pytest

from snowwindow.cli import COMMANDS, build_parser, main


def _write_config(path: Path) -> None:
    path.write_text(
        """
experiment_id: cli-test
data_dir: data
output_dir: outputs
model:
  name: aquacrop
  parameters: {}
selection:
  calibration_years: [2022]
  evaluation_years: [2023]
simulation:
  scan_fractions: [1.0]
  workers: 1
""".strip(),
        encoding="utf-8",
    )


def test_parser_exposes_all_stage_commands_and_requires_config() -> None:
    parser = build_parser()

    for command in COMMANDS:
        parsed = parser.parse_args([command, "--config", "experiment.yaml"])
        assert parsed.command == command
        assert parsed.config == Path("experiment.yaml")

        with pytest.raises(SystemExit):
            parser.parse_args([command])


def test_catalog_command_dispatches_with_output_root() -> None:
    assert "catalog" in COMMANDS


@pytest.mark.parametrize("command", COMMANDS)
def test_stage_commands_dispatch(
    command: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_path = tmp_path / "experiment.yaml"
    _write_config(config_path)
    if command == "catalog":
        (tmp_path / "outputs" / "experiments").mkdir(parents=True)
    seen = []
    monkeypatch.setattr(
        "snowwindow.cli._run_stage",
        lambda selected, config: (
            seen.append((selected, config.experiment_id)) or {"counts": {}}
        ),
    )

    exit_code = main([command, "--config", str(config_path)])

    assert exit_code == 0
    if command == "catalog":
        assert seen == []
        return
    assert seen == [(command, "cli-test")]
    output = capsys.readouterr().out
    assert "{}" in output if command == "audit" else f"{command}: complete" in output
