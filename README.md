# SnowWindow

SnowWindow is a reproducible G2F planting-date simulation pipeline. It normalizes
source tables, audits model eligibility, runs AquaCrop 3.1.0, calibrates
representative maize parameters, validates held years and sites, and produces
full-year planting-window reports. The current implementation is model-ready for
future DSSAT and APSIM adapters, but only AquaCrop is installed.

## 1. Environment

Create the Python 3.10 environment and install the project:

```bash
uv venv --python 3.10 --seed .venv
.venv/bin/python -m pip install -r requirements-aquacrop.lock.txt
.venv/bin/python -m pip install -e .
.venv/bin/python -m pip check
```

If `uv` is unavailable, use any working Python 3.10 installation and create a
virtual environment with `python3.10 -m venv .venv` before running the
same `pip` commands.

## 2. Data Layout

Place the supplied G2F files under `data/`:

```text
data/
  Training_data/
    1_Training_Trait_Data_2014_2023.csv
    2_Training_Meta_Data_2014_2023.csv
    3_Training_Soil_Data_2015_2023.csv
  Testing_data/
    2_Testing_Meta_Data_2024.csv
    3_Testing_Soil_Data_2024.csv
```

Source tables are read-only. Normalized tables, manifests, model caches,
figures, and reports are written under
`outputs/experiments/<experiment_id>/`.

## 3. Configuration

Use `configs/g2f_demo.yaml` for the six-environment demo:

```yaml
experiment_id: g2f_demo
data_dir: ../data
output_dir: ../outputs

model:
  name: aquacrop
  parameters:
    model_version: "3.1.0"

selection:
  calibration_years: [2022]
  evaluation_years: [2023]
```

The full config also sets `model.parameters`, environment selection, planting-window
fractions, and parameter sets. `g2f_history.yaml` uses all eligible environments
and calibration years 2014–2022. Keep calibration and evaluation years
disjoint. `simulation.workers` controls parallel execution; set it to `1` for
deterministic serial runs.

## 4. Experiment Flow

Run one stage at a time:

```bash
.venv/bin/python -m snowwindow audit --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow prepare --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow baseline --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow calibrate --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow validate --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow simulate --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow scan --config configs/g2f_demo.yaml
.venv/bin/python -m snowwindow report --config configs/g2f_demo.yaml
```

Or run the complete cached demo:

```bash
.venv/bin/python -m snowwindow run --config configs/g2f_demo.yaml
```

The stages are:

1. `audit`: inspect source data and write counts and issues.
2. `prepare`: normalize environment, management, soil, weather, and observation tables.
3. `baseline`: simulate observed planting dates with default parameters.
4. `calibrate`: search phenology and harvest-index parameters on frozen 2022 observations.
5. `validate`: compare default and calibrated parameters by held year and leave-site folds.
6. `simulate`: persist row-level observed-date results.
7. `scan`: materialize the full-year planting-date scan.
8. `report`: generate figures and the Markdown report.

## 5. Results

Open:

```text
outputs/experiments/g2f_demo/report/report.md
```

Key artifacts are:

- `normalized/`: model-ready source tables.
- `calibration/parameters.json`: selected parameters and fold assignments.
- `validation/metrics.csv`: MAE, RMSE, bias, and coverage.
- `scan/summary.csv`: full-year daily results.
- `scan/windows.csv`: 90% and 95% planting windows.
- `report/figures/`: environment yield curves.

The demo currently uses the existing hashed NASA POWER/AquaCrop cache for the
full-year scan. It does not treat incomplete 2024 competition weather as
complete forcing. Historical all-environment scans also require complete cached
continuation weather for every environment.

## 6. Model Interface

Implement DSSAT or APSIM by adding a package under `src/snowwindow/models/` and
following the existing AquaCrop boundary:

```python
from snowwindow.domain import SimulationRequest, SimulationResult


class DSSATAdapter:
    name = "dssat"
    version = "..."

    def validate(self, request: SimulationRequest) -> None: ...
    def run(self, request: SimulationRequest) -> SimulationResult: ...
```

Keep engine imports inside the model package, map native outcomes to
`RunStatus`, fingerprint model sources or executables in cache identity, and
return the same model-independent summary fields. Calibration and scan code
must not need model-specific branches.

## 7. Verification

Before committing:

```bash
.venv/bin/python -m pytest -q
.venv/bin/ruff check src tests/snowwindow
```
