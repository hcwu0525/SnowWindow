# Native AquaCrop Full-Year Scan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace legacy scan-cache materialization with native AquaCrop simulations for every configured environment, parameter set, and planting date, then regenerate the complete report.

**Architecture:** Build one `SimulationRequest` per environment/parameter/date using existing normalized tables and cached POWER forcing, execute requests through `AquaCropAdapter`, preserve all statuses, and derive windows from the native output. Keep scan logic deterministic and model-independent except for adapter resolution.

**Tech Stack:** Python 3.10 target, AquaCrop 3.1.0, pandas, pytest, existing SnowWindow adapter contracts.

**Spec:** User request: complete the minimal end-to-end loop and provide the complete full-year scan results and report.

## Global Constraints

- Scan must produce 6 environments × 2 parameter sets × 365 dates = 4,380 rows.
- Preserve every result status, including abnormal results.
- Use default and calibrated parameters.
- Do not use `outputs/aquacrop_crossyear/annual_scenarios.csv` as the scan source.
- Produce 90% and 95% windows, figures, and `report/report.md`.
- Verify uniqueness of `environment_id`, `parameter_set`, and `planting_date`.
- Keep calibration and validation behavior unchanged.

---

### Task 1: Native scan request builder

**Files:**
- Modify: `src/snowwindow/scan.py`
- Test: `tests/snowwindow/test_scan.py`

**Interfaces:**
- Consumes: `ExperimentConfig`, normalized prepared tables, cached POWER weather, `SimulationRequest`, `AquaCropAdapter`.
- Produces: `native_scan_requests(config, adapter=None)` returning deterministic request rows and provenance.

- [ ] Write failing test proving one environment/date/parameter request is generated with calibrated parameters and a stable request ID.
- [ ] Run the test and confirm it fails because the function is absent.
- [ ] Implement request generation with explicit planting-date replacement.
- [ ] Run the test and confirm it passes.

### Task 2: Native scan execution

**Files:**
- Modify: `src/snowwindow/scan.py`
- Test: `tests/snowwindow/test_scan.py`

**Interfaces:**
- Consumes: `native_scan_requests(config, adapter=None)`.
- Produces: `scan_stage(config, adapter=None)` executing every request and writing `scan/summary.parquet`, `scan/summary.csv`, `scan/windows.json`, and `scan/windows.csv`.

- [ ] Write a failing test with a fake adapter proving all dates execute and statuses are preserved.
- [ ] Run the test and confirm it fails because `scan_stage` still materializes the legacy cache.
- [ ] Replace legacy materialization with native adapter execution.
- [ ] Reuse the existing window derivation and artifact writers.
- [ ] Confirm the fake-adapter test passes.

### Task 3: Full experiment regeneration

**Files:**
- Modify: `outputs/experiments/g2f_demo/scan/*`
- Modify: `outputs/experiments/g2f_demo/report/*`

**Interfaces:**
- Consumes: `configs/g2f_demo.yaml`, prepared normalized data, calibration parameters, complete cached POWER forcing.
- Produces: 4,380 native scan rows and 24 window rows.

- [ ] Run `snowwindow scan --config configs/g2f_demo.yaml`.
- [ ] Run `snowwindow report --config configs/g2f_demo.yaml`.
- [ ] Verify row count, unique keys, statuses, and window count.
- [ ] Verify all six environment figures and the Markdown report exist.

### Task 4: Regression verification

**Files:**
- Test: all tests under `tests/snowwindow`

**Interfaces:**
- Produces: a clean Git commit on `main`.

- [ ] Run the complete pytest suite.
- [ ] Run Ruff.
- [ ] Run `pip check`.
- [ ] Inspect report content and key output files.
- [ ] Commit the implementation.
