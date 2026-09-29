# SnowWindow

SnowWindow is a reproducible G2F planting-date simulation pipeline. It normalizes
source tables, audits model eligibility, runs AquaCrop 3.1.0, APSIM NG, or DSSAT 4.8,
calibrates
representative maize parameters, validates held years and sites, and produces
full-year planting-window reports.

## Research documentation

持续维护的中文说明与实验记录见 [G2F 数据与作物模型研究记录](docs/README.md)：

- [G2F 数据、字段覆盖与模型输入映射](docs/g2f-data.md)
- [AquaCrop 与 APSIM 的理论、输入输出及适用范围](docs/model-comparison.md)
- [模型分析与使用日志、待核实问题和后续记录模板](docs/model-usage-log.md)

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

### Local APSIM engine

This workspace also has APSIM `2026.9.8116.0` and .NET runtime `8.0.31`
installed under `.tools/`. Use the project launcher from the repository root:

```bash
./bin/apsim --version
./bin/apsim /absolute/path/to/experiment.apsimx --single-threaded --csv
```

The launcher resolves the engine, runtime, and bundled native libraries relative
to its own location. It does not require the previous user-directory installation
or an activated Conda environment. This installation targets Linux x86_64 and
has been verified on Rocky Linux 9.3.

Run the prepared official Maize example with:

```bash
bash outputs/experiments/apsim_smoke/run-native.sh
```

Example results, installation fingerprints, and verification records are under
`outputs/experiments/apsim_smoke/`. The `.tools/` directory and downloaded APSIM
Debian packages are ignored by Git; a fresh checkout needs these runtime files
installed separately. SnowWindow can select the native adapter with
`model.name: apsim`.

### Local DSSAT engine

The native DSSAT adapter uses CERES-Maize 4.8.6.2 directly. Install the
`dscsm048` executable, `DSSATPRO.L48`, maize genotype files, `SOIL.SOL`,
and the official `UFGA8201.MZX` example in `.tools/dssat/4.8.6.2/`.
The installed profile must use short paths because DSSAT reads parts of it
with fixed-width Fortran buffers. This checkout uses
`/home/users/haochen.wu/.dssat` as a short alias to the installation.
The local source checkout also includes a fix for reading the real-valued
`CDAY` field in `MZCER048.ECO` into an integer model parameter. Confirm the
official example runs before using the adapter:

```bash
git -C dssat-csm-os apply --check ../patches/dssat-4.8.6.2-ecotype-cday.patch
git -C dssat-csm-os apply ../patches/dssat-4.8.6.2-ecotype-cday.patch
cmake -S dssat-csm-os -B .tools/dssat/build-local \
  -DCMAKE_Fortran_COMPILER=gfortran -DCMAKE_BUILD_TYPE=RELEASE \
  -DDYNAMIC_LINK=ON
cmake --build .tools/dssat/build-local -j 8
cp .tools/dssat/build-local/bin/dscsm048 .tools/dssat/4.8.6.2/dscsm048
cd outputs/experiments/dssat_runtime/smoke
/home/users/haochen.wu/code/SnowWindow/.tools/dssat/4.8.6.2/dscsm048 C UFGA8201.MZX 1
```

Apply the patch only to an unmodified DSSAT source checkout; this workspace
already has it applied. The official maize data distribution is needed to
populate the installation's `Genotype/`, `Soil/` and example directories.

Run the six selected G2F environments with:

```bash
.venv/bin/python -m snowwindow run --config configs/g2f_dssat_demo.yaml
```

The DSSAT scenario holds the official reference cultivar `IB0035` and
generic deep sandy-loam profile `IB00000007`, applies 120 kg N/ha at
planting, and assumes rainfed management. These are **reference
assumptions**, not measured G2F genotype, soil hydraulic properties, or
fertilizer records. P1 and G2 are selected using 2022 calibration
observations; 2023 remains an evaluation year. Each run retains its
weather/experiment/cultivar inputs, native outputs, source fingerprints,
and failure status under `outputs/experiments/g2f_dssat_demo/model_cache/dssat/`.

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

Use the APSIM six-environment workflow with:

```bash
.venv/bin/python -m snowwindow run --config configs/g2f_apsim_demo.yaml
```

This first APSIM workflow uses fixed exploratory soil, nitrogen, fertiliser, and
Dekalb_XL82 assumptions. It calibrates 2022 and evaluates 2023 before running
the full-year planting-date scan.

## 4. Experiment Flow

### Refined historical experiment

Use `configs/g2f_aquacrop_refined.yaml` for the 2014–2022 calibration candidate years and
independent 2023 evaluation experiment:

```bash
.venv/bin/python -m snowwindow audit --config configs/g2f_aquacrop_refined.yaml
.venv/bin/python -m snowwindow prepare --config configs/g2f_aquacrop_refined.yaml
.venv/bin/python -m snowwindow calibrate --config configs/g2f_aquacrop_refined.yaml
.venv/bin/python -m snowwindow validate --config configs/g2f_aquacrop_refined.yaml
.venv/bin/python -m snowwindow scan --config configs/g2f_aquacrop_refined.yaml
.venv/bin/python -m snowwindow report --config configs/g2f_aquacrop_refined.yaml
```

The refined experiment filters calibration samples, allows explicitly labelled
assumed rainfed conditions, records soil and planting-density provenance,
uses a soil-moisture-target strategy for confirmed
irrigation, and falls back to global parameters for sites without at least
three training years. Full-year scans are counterfactual scenarios; only the
actual G2F planting date is an observed validation point.

The full-year scan is resumable. Each completed request is appended to
`outputs/experiments/g2f_aquacrop_refined/model_cache/aquacrop/scan_progress.jsonl`.
If the command is interrupted, rerun the same `scan` command: completed dates
are skipped, and progress is reported every 100 requests.

### Six-environment demo

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

Implement further models by adding a package under `src/snowwindow/models/` and
following the existing AquaCrop boundary:

```python
from snowwindow.domain import SimulationRequest, SimulationResult


class NewModelAdapter:
    name = "new_model"
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
