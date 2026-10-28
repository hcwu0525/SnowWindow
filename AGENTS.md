# Repository Guidelines

## Project Structure & Module Organization

Production code lives in `src/snowwindow/`. Data auditing and normalization are
under `src/snowwindow/data/`; model-independent contracts are in `domain.py` and `adapters.py`;
the AquaCrop implementation is under `models/aquacrop/`. Calibration, scanning,
reporting, and executable stages have dedicated modules. Experiment YAML files
live in `configs/`, and tests mirror the package under `tests/snowwindow/`.

Treat source files in `data/` as read-only. Write normalized tables, caches,
figures, manifests, and reports under `outputs/experiments/<experiment_id>/`.

## Build, Test, and Development Commands

Run commands from the repository root:

- `uv venv --python 3.10 --seed .venv`: create the supported environment.
- `.venv/bin/python -m pip install -r requirements-aquacrop.lock.txt -e '.[dev]'`
  installs pinned scientific and development dependencies.
- `.venv/bin/python -m pip check` verifies dependency compatibility.
- `.venv/bin/python -m snowwindow run --config configs/g2f_demo.yaml`
  runs preparation through reporting.
- `make check` checks dependencies, style and engine/data-independent tests.
- `make test-integration` runs local real-model/data tests.
- `.venv/bin/python -m pytest -q` runs all tests. For selection, use
  `PYTEST_ADDOPTS="-m 'not integration'"` instead of passing `-m` directly;
  AquaCrop 3.1.0 uses that argument during import.
- `.venv/bin/python -m ruff check src tests/snowwindow scripts` checks style.

Individual CLI stages include `audit`, `prepare`, `baseline`, `calibrate`,
`validate`, `simulate`, `scan`, `report`, `forecast`, and `catalog`. `run` does not
include `forecast`; all commands require `--config`.

## Coding Style & Naming Conventions

Use four-space indentation, type annotations, snake_case functions and modules,
PascalCase classes, and uppercase constants. Preserve units in field names such
as `dry_yield_mg_ha`. Keep engine-specific translation inside its model package
and expose it through the shared `ModelAdapter` contract. Ruff configuration is
defined in `pyproject.toml`.

## Testing Guidelines

Use pytest files and functions named `test_*.py` and `test_*`. Cover date
boundaries, failure statuses, fixed calibration samples, data provenance, and
water-balance invariants. Tests must not require modifying raw data.

## Commit & Pull Request Guidelines

Use concise imperative subjects, following existing commits such as
`Harden AquaCrop adapter contracts`. PRs should explain scientific behavior,
list validation commands, identify configuration or data assumptions, and
include regenerated figures when report outputs change.

## Reproducibility Rules

Preserve input fingerprints and failed simulation records. Never relabel failed
runs as matured or use evaluation-year observations during parameter selection.
