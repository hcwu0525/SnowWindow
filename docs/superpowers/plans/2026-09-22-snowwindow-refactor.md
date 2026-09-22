# SnowWindow Simulation Pipeline Refactor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible G2F-to-AquaCrop workflow covering normalized inputs, calibration, validation, full-year planting-date scans, reports, and a model-adapter seam for later DSSAT/APSIM integrations.

**Architecture:** A new `snowwindow` package owns normalized domain records and experiment orchestration. Model-specific behavior sits behind a small adapter interface; AquaCrop 3.1.0 is the first adapter. Original `data/`, legacy code, and existing outputs remain unchanged.

**Tech Stack:** Python 3.10+, pandas, NumPy, PyYAML, PyArrow, AquaCrop-OSPy 3.1.0, matplotlib, pytest, Ruff.

## Global Constraints

- Raw `data/` is read-only; generated artifacts live under `outputs/experiments/<experiment_id>/`.
- Representative-maize observations average plot replicates within hybrid, then weight hybrids equally within a management unit.
- The historical split is 2014–2022 calibration, 2023 evaluation, and optional 2024 yield-only evaluation. The demo split is 2022 calibration and 2023 evaluation.
- Missing irrigation may be treated as assumed rainfed and must carry provenance. Known irrigated environments without event schedules are excluded by default.
- Default-soil environments may be scanned but cannot enter calibration.
- Candidate calibration runs are rejected if any observation in the fixed target set is unavailable because the model did not mature or failed.
- Full-year scans contain every requested calendar date, preserve failure statuses, and default to a cross-year horizon.
- Existing `aquacrop_demo/` code and prior outputs remain available for regression comparison.

## Task 1: Standard project and domain foundation

- [ ] Add `pyproject.toml`, package layout, CLI entry point, typed domain records, configuration loading, and deterministic experiment paths.
- [ ] Add unit tests for configuration validation, request/result serialization, and model-adapter registration.
- [ ] Add demo and history configuration files.

## Task 2: G2F normalization and audit

- [ ] Normalize environments, plot observations, management units, soil samples/profiles, and daily weather into versioned Parquet tables.
- [ ] Implement representative-maize aggregation and eligibility/provenance rules.
- [ ] Detect the known 2024 weather gaps and preserve all source rows and identifiers.
- [ ] Add data-dictionary and audit outputs plus focused unit/integration tests.

## Task 3: AquaCrop adapter

- [ ] Isolate AquaCrop weather ordering, soil/crop construction, model-version checks, run statuses, water-balance diagnostics, and cross-year calendar compatibility.
- [ ] Support content-addressed summaries and optional daily outputs.
- [ ] Port regression behavior through adapter-interface tests and real-model integration tests.

## Task 4: Calibration and validation

- [ ] Implement deterministic coarse/fine calibration for phenology scale and HI0.
- [ ] Freeze observation sets, prevent evaluation-label leakage, reject incomplete candidates, and calculate MAE/RMSE/bias/coverage.
- [ ] Implement held-year and leave-site validation with manifests and tests.

## Task 5: Full-year scan and reports

- [ ] Generate 365/366 dated requests per environment and parameter set.
- [ ] Compute valid planting windows, preserve abnormal states, and create CSV/JSON/Parquet summaries.
- [ ] Produce Chinese Markdown reports and plots with explicit assumptions and limitations.

## Task 6: End-to-end CLI and verification

- [ ] Wire `audit`, `prepare`, `baseline`, `calibrate`, `validate`, `simulate`, `scan`, `report`, and `run`.
- [ ] Run the six-environment workflow for default and calibrated parameter sets.
- [ ] Verify 4,380 scan summaries, cache reuse, report regeneration, tests, lint, and package installation.
- [ ] Document commands, output contracts, and the adapter extension path for DSSAT/APSIM.
