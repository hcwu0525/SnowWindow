# SnowWindow

SnowWindow is a reproducible G2F planting-date simulation pipeline. It
normalizes source tables, audits model eligibility, runs AquaCrop 3.1.0,
calibrates representative-maize parameters, validates held years and sites,
and produces full-year planting-window reports.

## Setup

```bash
uv venv --python 3.9 --seed .venv-py39
.venv-py39/bin/python -m pip install -r requirements-aquacrop.lock.txt
.venv-py39/bin/python -m pip install -e .
```

## Workflow

Run individual stages or the complete demo:

```bash
.venv-py39/bin/python -m snowwindow prepare --config configs/g2f_demo.yaml
.venv-py39/bin/python -m snowwindow baseline --config configs/g2f_demo.yaml
.venv-py39/bin/python -m snowwindow calibrate --config configs/g2f_demo.yaml
.venv-py39/bin/python -m snowwindow validate --config configs/g2f_demo.yaml
.venv-py39/bin/python -m snowwindow scan --config configs/g2f_demo.yaml
.venv-py39/bin/python -m snowwindow report --config configs/g2f_demo.yaml
```

Generated files live under `outputs/experiments/<experiment_id>/`. Raw
`data/` and legacy outputs are read-only. The demo scan uses the existing,
hashed NASA POWER cache because the supplied 2024 G2F weather is incomplete.

## Architecture

- `snowwindow.data`: source normalization, audit, and eligibility.
- `snowwindow.models.aquacrop`: AquaCrop translation, validation, execution,
  status mapping, and cache artifacts.
- `snowwindow.calibration`: fixed observation sets, deterministic parameter
  search, folds, and metrics.
- `snowwindow.scan` and `snowwindow.reporting`: daily scans, windows, figures,
  and the Chinese report.

## Adding DSSAT or APSIM

Implement `ModelAdapter` with stable `name`, `version`, `validate`, and `run`
members. Keep engine imports inside its model package. Map native outcomes to
`RunStatus`, fingerprint source/executables in cache identity, and return the
same model-independent summary fields. Calibration and scan code should not
need model-specific branches.

Run `.venv-py39/bin/python -m pytest -q` and
`.venv-py39/bin/ruff check src tests/snowwindow` before committing.
