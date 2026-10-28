"""Installable repository contracts, independent of private data and engines."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
import tomli
from packaging.requirements import Requirement

from snowwindow.config import load_config
from snowwindow.data.sources import SOURCE_CATALOG

ROOT = Path(__file__).resolve().parents[2]
CONFIGURATIONS = {
    "g2f_demo": "aquacrop",
    "g2f_history": "aquacrop",
    "g2f_aquacrop_refined": "aquacrop",
    "g2f_apsim_demo": "apsim",
    "g2f_dssat_demo": "dssat",
    "g2f_forecast_demo": "aquacrop",
    "g2f_forecast_demo_radius30": "aquacrop",
    "g2f_apsim_forecast_demo": "apsim",
    "g2f_apsim_forecast_demo_radius30": "apsim",
    "g2f_dssat_forecast_demo": "dssat",
    "g2f_dssat_forecast_demo_radius30": "dssat",
}


def test_locked_versions_satisfy_runtime_and_development_requirements() -> None:
    project = tomli.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    lines = (ROOT / "requirements-aquacrop.lock.txt").read_text(
        encoding="utf-8"
    ).splitlines()
    locked = [
        Requirement(line)
        for line in lines
        if line.strip() and not line.startswith("#")
    ]
    assert len({requirement.name for requirement in locked}) == len(locked)
    versions = {
        requirement.name: next(iter(requirement.specifier)).version
        for requirement in locked
    }
    dependencies = [
        *project["project"]["dependencies"],
        *project["project"]["optional-dependencies"]["dev"],
    ]
    for dependency in dependencies:
        requirement = Requirement(dependency)
        assert requirement.name in versions, f"unlocked dependency: {dependency}"
        assert requirement.specifier.contains(versions[requirement.name]), (
            f"{requirement.name}=={versions[requirement.name]} "
            f"conflicts with {dependency}"
        )


@pytest.mark.parametrize("experiment_id, model", CONFIGURATIONS.items())
def test_each_distributed_configuration_loads_without_external_inputs(
    experiment_id: str, model: str
) -> None:
    config = load_config(ROOT / "configs" / f"{experiment_id}.yaml")

    assert config.experiment_id == experiment_id
    assert config.model.name == model
    assert config.data_dir == ROOT / "data"
    assert config.output_dir == ROOT / "outputs"
    assert set(config.selection.calibration_years).isdisjoint(
        config.selection.evaluation_years
    )
    if "forecast" in experiment_id:
        source_id = config.selection.options["source_experiment_id"]
        source = load_config(ROOT / "configs" / f"{source_id}.yaml")
        assert source.model.name == model
        assert source.selection.calibration_years == config.selection.calibration_years


def test_configuration_inventory_documents_all_yaml_entrypoints() -> None:
    inventory = (ROOT / "configs/README.md").read_text(encoding="utf-8")
    documented = set(re.findall(r"\[([a-z0-9_]+\.yaml)\]\(", inventory))
    distributed = {path.name for path in (ROOT / "configs").glob("*.yaml")}
    assert documented == distributed == {f"{name}.yaml" for name in CONFIGURATIONS}
    for name in CONFIGURATIONS:
        config = load_config(ROOT / "configs" / f"{name}.yaml")
        row = next(
            line for line in inventory.splitlines()
            if line.startswith(f"| [{name}.yaml]")
        )
        command = "forecast" if "forecast" in name else "run"
        assert f"make {command} CONFIG=configs/{name}.yaml" in row
        assert f"outputs/experiments/{name}/" in row
        assert config.model.name in row.casefold()
        for years in (
            config.selection.calibration_years,
            config.selection.evaluation_years,
        ):
            assert str(min(years)) in row
            assert str(max(years)) in row
        if "forecast" in name:
            assert config.selection.options["source_experiment_id"] in row


def test_data_guide_lists_every_required_input_including_audit_only_files() -> None:
    guide = (ROOT / "docs/getting-started.md").read_text(encoding="utf-8")
    assert len(SOURCE_CATALOG) == 13
    for source in SOURCE_CATALOG.values():
        assert Path(source.relative_path).name in guide
    assert "excluded_from_model_inputs" in guide


def test_git_ignore_excludes_local_assets_but_not_nested_source_packages(
    tmp_path: Path,
) -> None:
    if shutil.which("git") is None:
        pytest.skip("Git is required to exercise ignore rules")
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".gitignore").write_text(
        (ROOT / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8"
    )
    excluded = {
        "data/raw.csv",
        "outputs/experiments/example/config.yaml",
        ".tools/apsim/Models.dll",
        "dssat-csm-os/Plant/model.for",
        ".venv/lib/package.py",
        "build/lib/snowwindow/__init__.py",
        "dist/snowwindow.whl",
        ".env",
        "configs/example.local.yaml",
    }
    included = {
        "src/snowwindow/data/sources.py",
        "tests/snowwindow/data/example.csv",
        "docs/outputs/description.md",
        "configs/g2f_demo.yaml",
        ".env.example",
    }
    completed = subprocess.run(
        ["git", "-C", str(tmp_path), "check-ignore", "--no-index", "--stdin"],
        input="\n".join(sorted(excluded | included)) + "\n",
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0
    assert set(completed.stdout.splitlines()) == excluded


def test_makefile_exposes_local_checks_without_requiring_installed_engines() -> None:
    if shutil.which("make") is None:
        pytest.skip("make is required to exercise the optional convenience entrypoint")
    completed = subprocess.run(
        ["make", "--no-print-directory", "-n", "check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert "pip check" in completed.stdout
    assert "ruff check" in completed.stdout
    assert "pytest" in completed.stdout
    assert "PYTEST_ADDOPTS" in completed.stdout
