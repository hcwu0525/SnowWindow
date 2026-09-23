from pathlib import Path

import pytest
import tomli

from snowwindow.config import ConfigError, load_config


def _write_config(path: Path, body: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body.strip(), encoding="utf-8")
    return path


def _valid_yaml(overrides: str = "") -> str:
    return f"""
experiment_id: demo
data_dir: inputs
output_dir: generated
model:
  name: aquacrop
  parameters:
    crop: Maize
selection:
  environments: [INH1_2022, INH1_2023]
  calibration_years: [2022]
  evaluation_years: [2023]
  all_eligible_environments: false
  allow_assumed_rainfed: true
  exclude_default_soil_from_calibration: true
simulation:
  scan_fractions: [0.25, 1.0]
  workers: 2
  scan_all_dates: true
  parameter_sets:
    default: {{}}
    calibrated:
      source: calibration
{overrides}
"""


def test_load_config_resolves_paths_and_experiment_directory(tmp_path: Path) -> None:
    config_path = _write_config(tmp_path / "configs" / "demo.yaml", _valid_yaml())

    config = load_config(config_path)

    assert config.experiment_id == "demo"
    assert config.data_dir == (config_path.parent / "inputs").resolve()
    assert config.output_dir == (config_path.parent / "generated").resolve()
    assert config.experiment_dir == config.output_dir / "experiments" / "demo"
    assert config.model.name == "aquacrop"
    assert dict(config.model.parameters) == {"crop": "Maize"}
    assert config.selection.calibration_years == (2022,)
    assert config.selection.evaluation_years == (2023,)
    assert config.selection.allow_assumed_rainfed is True
    assert config.selection.exclude_default_soil_from_calibration is True
    assert config.simulation.scan_fractions == (0.25, 1.0)
    assert config.simulation.workers == 2


@pytest.mark.parametrize(
    ("yaml_text", "message"),
    [
        (
            _valid_yaml().replace("experiment_id: demo", "experiment_id: '  '"),
            "experiment_id",
        ),
        (_valid_yaml().replace("name: aquacrop", "name: ''"), "model.name"),
        (_valid_yaml().replace("[0.25, 1.0]", "[0.0]"), "scan_fractions"),
        (_valid_yaml().replace("[0.25, 1.0]", "[1.01]"), "scan_fractions"),
        (_valid_yaml().replace("workers: 2", "workers: 0"), "workers"),
        (
            _valid_yaml().replace(
                "evaluation_years: [2023]", "evaluation_years: [2022]"
            ),
            "disjoint",
        ),
    ],
)
def test_load_config_rejects_invalid_values(
    tmp_path: Path, yaml_text: str, message: str
) -> None:
    config_path = _write_config(tmp_path / "invalid.yaml", yaml_text)

    with pytest.raises(ConfigError, match=message):
        load_config(config_path)


@pytest.mark.parametrize(
    ("field_name", "valid_line", "invalid_line"),
    [
        (
            "selection.all_eligible_environments",
            "all_eligible_environments: false",
            'all_eligible_environments: "false"',
        ),
        (
            "selection.allow_assumed_rainfed",
            "allow_assumed_rainfed: true",
            'allow_assumed_rainfed: "false"',
        ),
        (
            "selection.exclude_default_soil_from_calibration",
            "exclude_default_soil_from_calibration: true",
            'exclude_default_soil_from_calibration: "false"',
        ),
        (
            "simulation.scan_all_dates",
            "scan_all_dates: true",
            'scan_all_dates: "false"',
        ),
    ],
)
def test_load_config_rejects_non_boolean_settings(
    tmp_path: Path, field_name: str, valid_line: str, invalid_line: str
) -> None:
    config_path = _write_config(
        tmp_path / "invalid-boolean.yaml",
        _valid_yaml().replace(valid_line, invalid_line),
    )

    with pytest.raises(ConfigError, match=field_name):
        load_config(config_path)


def test_load_config_recursively_freezes_nested_sequence_values(
    tmp_path: Path,
) -> None:
    yaml_text = _valid_yaml().replace(
        "    crop: Maize",
        """
    crop: Maize
    cultivars:
      - name: generic
        coefficients:
          - name: hi0
            value: 0.48
""".rstrip(),
    )
    config_path = _write_config(tmp_path / "nested.yaml", yaml_text)

    config = load_config(config_path)
    cultivars = config.model.parameters["cultivars"]

    assert isinstance(cultivars, tuple)
    assert isinstance(cultivars[0]["coefficients"], tuple)
    with pytest.raises(TypeError):
        cultivars[0]["coefficients"][0]["value"] = 0.5


@pytest.mark.parametrize(
    "missing_key",
    [
        "experiment_id",
        "data_dir",
        "output_dir",
        "model",
        "selection",
        "simulation",
    ],
)
def test_load_config_requires_top_level_sections(
    tmp_path: Path, missing_key: str
) -> None:
    lines = _valid_yaml().strip().splitlines()
    start = next(
        index
        for index, line in enumerate(lines)
        if line == f"{missing_key}:" or line.startswith(f"{missing_key}: ")
    )
    end = start + 1
    if lines[start].endswith(":"):
        while end < len(lines) and lines[end].startswith("  "):
            end += 1
    yaml_text = "\n".join(lines[:start] + lines[end:])
    config_path = _write_config(tmp_path / "missing.yaml", yaml_text)

    with pytest.raises(ConfigError, match=missing_key):
        load_config(config_path)


def test_bundled_configs_encode_required_experiment_policies() -> None:
    project_root = Path(__file__).resolve().parents[2]
    demo = load_config(project_root / "configs" / "g2f_demo.yaml")
    history = load_config(project_root / "configs" / "g2f_history.yaml")

    assert demo.selection.environments == (
        "INH1_2022",
        "MOH2_2022",
        "NYH2_2022",
        "INH1_2023",
        "MOH2_2023",
        "NYH2_2023",
    )
    assert demo.selection.calibration_years == (2022,)
    assert demo.selection.evaluation_years == (2023,)
    assert demo.simulation.scan_all_dates is True
    assert demo.simulation.options["scan_horizon"] == "cross_year"
    assert demo.simulation.options["continuation_weather_by_environment"] == {}
    assert set(demo.simulation.parameter_sets) == {"default", "calibrated"}
    assert demo.model.parameters["grain_standard_moisture_fraction"] == 0.155
    assert demo.model.parameters["default_soil_texture"] == "Loam"

    assert history.selection.calibration_years == tuple(range(2014, 2023))
    assert history.selection.evaluation_years == (2023,)
    assert history.selection.allow_assumed_rainfed is True
    assert history.selection.exclude_default_soil_from_calibration is True
    assert history.selection.all_eligible_environments is True
    assert history.simulation.scan_all_dates is True
    assert history.simulation.options["scan_horizon"] == "cross_year"
    assert history.simulation.options["continuation_weather_by_environment"] == {}
    assert history.model.parameters["grain_standard_moisture_fraction"] == 0.155
    assert history.model.parameters["default_soil_texture"] == "Loam"


def test_project_targets_python_310() -> None:
    project_root = Path(__file__).resolve().parents[2]
    with (project_root / "pyproject.toml").open("rb") as handle:
        project = tomli.load(handle)

    assert project["project"]["requires-python"] == ">=3.10,<3.13"
    assert project["tool"]["ruff"]["target-version"] == "py310"

    lock = (project_root / "requirements-aquacrop.lock.txt").read_text(
        encoding="utf-8"
    )
    assert "# Python 3.10+" in lock
