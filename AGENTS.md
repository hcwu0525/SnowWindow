# Repository Guidelines

## Project Structure & Module Organization

`aquacrop_demo/` contains the Python experiment package: `data.py` prepares inputs, `physics.py` computes ET0 and planting windows, `model.py` adapts AquaCrop, and `pipeline.py` orchestrates calibration and scenarios. Annual and cross-year workflows live in `optimize.py` and `crossyear.py`; report and plotting modules generate deliverables. Configuration lives in `aquacrop_demo/config.yaml`; detailed workflow documentation is in `aquacrop_demo/README.md`.

`tests/` contains demo, annual, and cross-year regression tests. Treat original `data/` inputs as read-only. Write generated weather, simulation caches, tables, figures, and reports under the appropriate `outputs/aquacrop_demo/`, `outputs/aquacrop_annual/`, or `outputs/aquacrop_crossyear/` directory.

## Build, Test, and Development Commands

Run commands from the repository root. There is no separate build step.

- `uv venv --python 3.10 --seed .venv`: create the documented Python environment.
- `.venv/bin/python -m pip install -r requirements-aquacrop.lock.txt`: install pinned dependencies, including AquaCrop 3.1.0.
- `.venv/bin/python -m pip check`: check dependency compatibility; verify installation on your platform.
- `.venv/bin/python -m aquacrop_demo smoke`: validate the model using a bundled example.
- `.venv/bin/python -m aquacrop_demo all`: run preparation, baseline, calibration, validation, scenarios, and reporting.
- `.venv/bin/python -m aquacrop_demo.optimize`: run annual optimization after the demo workflow.
- `.venv/bin/python -m aquacrop_demo.crossyear`: run cross-year scenarios after annual optimization.
- `.venv/bin/python -m pytest -q`: run the test suite.

Initial weather preparation requires NASA POWER access. Reuse cached weather afterward. Use `--config path/to/config.yaml` with the main CLI; set `workers: 1` for serial debugging.

## Coding Style & Naming Conventions

Use four-space indentation, snake_case modules/functions, PascalCase classes, and uppercase constants. Match surrounding code and preserve explicit units in scientific fields. Keep model adaptation in `model.py` and reusable calculations in `physics.py`. No formatter or linter configuration is present.

## Testing Guidelines

Use pytest files named `test_*.py` and functions named `test_*`. Cover date boundaries, abnormal model statuses, calibration isolation, and water-balance invariants. Integration tests require prepared outputs; some skip when prerequisites are missing. No coverage threshold is configured. Record skipped tests when reporting results.

## Commit & Pull Request Guidelines

Git history is unavailable in this checkout. Use concise imperative commit subjects. PRs should describe the scientific or behavioral change, link relevant issues, list validation commands and prerequisites, and include updated figures when plots change.

## Reproducibility Rules

Preserve input fingerprints and failure records; never relabel failed simulations as matured. Keep 2023 evaluation data out of parameter selection. Document configuration and assumption changes alongside regenerated results.
