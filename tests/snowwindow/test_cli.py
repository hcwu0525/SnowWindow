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


@pytest.mark.parametrize("command", COMMANDS)
def test_placeholder_stages_fail_clearly(
    command: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_path = tmp_path / "experiment.yaml"
    _write_config(config_path)

    exit_code = main([command, "--config", str(config_path)])

    assert exit_code != 0
    assert f"{command}: not implemented" in capsys.readouterr().err
