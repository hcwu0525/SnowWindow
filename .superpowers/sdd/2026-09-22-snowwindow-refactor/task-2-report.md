# Task 2 report — G2F normalization and audit

## Files changed

- `src/snowwindow/data.py`
- `src/snowwindow/__init__.py`
- `tests/snowwindow/test_data.py`
- `tests/snowwindow/test_config.py`
- `configs/g2f_demo.yaml`
- `configs/g2f_history.yaml`
- `pyproject.toml`
- `.superpowers/sdd/2026-09-22-snowwindow-refactor/task-2-report.md`

No raw data, prior outputs, legacy `aquacrop_demo/` code, or legacy tests were
modified.

## RED and GREEN evidence

- RED: `.venv-py39/bin/python -m pytest -q tests/snowwindow/test_data.py`
  - Collection failed with the expected `ModuleNotFoundError` because
    `snowwindow.data` did not exist.
- RED: focused checks for severe issue classification, training
  `Field_Location` propagation, and explicit bundled preparation assumptions
  produced three expected failures.
- GREEN: `.venv-py39/bin/python -m pytest -q tests/snowwindow/test_data.py -m
  'not integration' -W error::FutureWarning`
  - 19 passed, 1 deselected.
- GREEN: `.venv-py39/bin/python -m pytest -q
  tests/snowwindow/test_data.py -m integration`
  - 1 passed, 18 deselected in 68.11 seconds.
- Independent controller verification:
  `.venv-py39/bin/python -m pytest -q tests/snowwindow/test_data.py`
  - 20 passed in 69.25 seconds.
- GREEN: `.venv-py39/bin/python -m pytest -q tests/snowwindow -m 'not
  integration'`
  - 55 passed, 1 deselected.
- GREEN: `.venv-py39/bin/python -m pytest -q -k 'not
  test_real_data_audit_measures_known_g2f_coverage'`
  - 69 passed, 1 deselected.
- GREEN: `.venv-py39/bin/ruff check src tests/snowwindow`
  - All checks passed.
- GREEN: `.venv-py39/bin/ruff format --check src tests/snowwindow`
  - 12 files already formatted.

The expensive real-data audit was run once by this implementation and once
independently by the controller. It was not repeated during finalization.

## Measured real-data counts

- Training plot rows: 173,960.
- Training environments: 272.
- Testing environments: 23.
- Parsed training management units: 418.
- Training full-year weather: 98,236 rows for 269 environments.
- Testing 2024 weather: 7,245 rows for 23 environments.
- Combined normalized weather source rows: 105,481.
- Testing submission-template rows: 10,057.
- Testing observed-value rows: 9,486.
- Soil samples preserved: 207, comprising 186 training samples and 21 testing
  samples.
- Training weather is absent for `TXH2_2015`, `TXH2_2016`, and `TXH2_2017`.
- All 23 testing environments end on November 10, 2024.
- All 23 testing environments have invalid core forcing on July 12–14, 2024,
  totaling 69 environment-date gaps.

## Decisions

- `prepare_g2f(config)` writes the eleven required normalized, audit, and
  manifest artifacts beneath `config.experiment_dir`; every file is written to
  a unique temporary sibling and atomically replaced.
- `audit_g2f(config)` performs the same source validation and eligibility
  derivation entirely in memory and does not create the experiment directory.
- The manifest records source paths, byte sizes, SHA-256 hashes, generated
  artifact hashes and row counts, schema version, and normalization
  assumptions. Stable fixture inputs produce byte-identical manifests.
- Training plots retain the five-field natural key, hybrid, source filename,
  and 1-based source row. Testing template rows are left joined to the
  `(Env, Hybrid)` observed-value table so unavailable 2024 observations remain
  null.
- Representative observations average valid plots within each hybrid before
  equally weighting hybrid means. Dry yield uses the configured 0.155 standard
  moisture fraction and records contributing source-row counts.
- Coordinates use a complete valid weather-station pair, then complete valid
  field-corner pairs for a centroid. Irrigation uncertainty is preserved until
  eligibility evaluation.
- Soil samples retain raw `E Depth` separately. Profiles use recognized
  AquaCrop texture names, deterministic modal selection with lexical
  tie-breaking, and explicit default/conflict provenance.
- Weather validation covers date parsing, unique `(Env, Date)` keys,
  environment-year alignment, physical bounds, missing core values, and full
  calendar coverage. Source units are recorded in the data dictionary.
- Yield magnitude is not referenced by environment or management-unit
  selection.

## Concerns

- The raw source inventory intentionally uses the nine tables required to
  construct these artifacts. Seasonal weather, genotype, EC, merged, and 6D
  tables are not model inputs.
- Preparation assumptions are stored in the existing Task 1
  `model.parameters` mapping because Task 1 did not define a separate
  preparation namespace. A later configuration refactor should prevent these
  keys from being forwarded blindly to a model adapter.
- AquaCrop 3.1.0 suppresses its public imports when the literal `-m` appears in
  `sys.argv`; therefore the full suite excludes the already-run integration
  audit with pytest `-k` rather than pytest `-m`.
- The supplied 2024 weather cannot support a complete full-year or cross-year
  scan without additional forcing.

## Fix round 1 — 2026-09-22

### Files changed

- Replaced `src/snowwindow/data.py` with the focused
  `src/snowwindow/data/` package:
  - `sources.py` for source schemas, loading, inventory, and key validation.
  - `normalization.py` for source normalization and aggregation.
  - `audit.py` for weather coverage, exclusions, and eligibility.
  - `preparation.py` for orchestration, artifacts, and manifests.
  - `__init__.py` as the small public facade.
- Updated `tests/snowwindow/test_data.py` and
  `tests/snowwindow/test_config.py`.
- Updated `configs/g2f_demo.yaml` and `configs/g2f_history.yaml`.

### RED and GREEN evidence

- RED:
  `.venv-py39/bin/python -m pytest -q tests/snowwindow/test_data.py -k
  'not test_real_data_audit_measures_known_g2f_coverage' -W
  error::FutureWarning`
  - 9 failed, 17 passed, 1 deselected.
  - The failures covered null natural keys, negated severe comments, default
    soil samples participating in modal selection, excluded-source inventory,
    missing-date source exclusions, explicit cross-year continuation forcing,
    and runtime manifest metadata.
- GREEN:
  `.venv-py39/bin/python -m pytest -q tests/snowwindow/test_data.py -k
  'not test_real_data_audit_measures_known_g2f_coverage' -W
  error::FutureWarning`
  - 26 passed, 1 deselected in 1.04 seconds.
- Real-data audit, run once:
  `.venv-py39/bin/python -m pytest -q
  tests/snowwindow/test_data.py::test_real_data_audit_measures_known_g2f_coverage`
  - 1 passed in 68.51 seconds.
- Fast focused verification:
  `.venv-py39/bin/python -m pytest -q tests/snowwindow/test_data.py
  tests/snowwindow/test_config.py -k
  'not test_real_data_audit_measures_known_g2f_coverage' -W
  error::FutureWarning`
  - 45 passed, 1 deselected in 1.10 seconds.
- Full suite excluding the already-run real-data audit:
  `.venv-py39/bin/python -m pytest -q -k
  'not test_real_data_audit_measures_known_g2f_coverage'`
  - 76 passed, 1 deselected in 4.41 seconds.
- Ruff lint:
  `.venv-py39/bin/ruff check src tests/snowwindow`
  - All checks passed.
- The first Ruff format check identified only formatting in
  `tests/snowwindow/test_data.py`; `.venv-py39/bin/ruff format
  tests/snowwindow/test_data.py` reformatted that file.
- Final Ruff format check:
  `.venv-py39/bin/ruff format --check src tests/snowwindow`
  - 11 files already formatted.

### Measured real-data counts

- Training plot rows: 173,960.
- Training environments: 272.
- Testing environments: 23.
- Parsed training management units: 418.
- Training rows excluded from management-unit formation because planting date
  is missing: 363. Each exclusion records its reason, source filename, source
  row number, and environment.
- Training full-year weather remains absent for `TXH2_2015`, `TXH2_2016`, and
  `TXH2_2017`.
- All 23 testing environments end on November 10, 2024.
- All 23 testing environments have core forcing gaps on July 12–14, 2024,
  totaling 69 environment-date gaps.

### Decisions

- Cross-year scan eligibility requires an exact
  `continuation_weather_by_environment` entry whose target is complete weather
  for the following year. No location relationship is inferred from an
  environment prefix. Missing or invalid continuation forcing produces
  `crossyear_weather_missing`.
- Both seasons-only weather tables and both EC tables are hashed and listed in
  the manifest and audit as `excluded_from_model_inputs`; only sources marked
  `model_input` are loaded into normalized model tables.
- Training rows with no parsed planting date remain in plot observations and
  are also represented in the deterministic source-exclusion audit. They do
  not create management units.
- Severe issue detection evaluates clauses and ignores a severe term when the
  same clause explicitly negates or reports absence of that issue.
- Every soil sample maps to either a recognized AquaCrop texture or the
  configured default before modal selection. Conflict compares those mapped
  categories, and a default-derived winner records `profile_source=default`.
- Training natural keys reject null components before duplicate detection.
- The preparation manifest records the SnowWindow producer version and Python,
  pandas, and PyArrow versions.

### Concerns

- The severe-comment rule is a deterministic clause-level heuristic. New
  source wording may require another explicit regression case.
- The checked-in cross-year configurations intentionally have empty
  continuation mappings, so cross-year scan units remain ineligible until
  verified continuation environments are configured.

## Fix round 2 — 2026-09-22

- Added the exact `MNH1_2016` comment as a regression case. A later
  `lodging not reported as an issue` statement now suppresses earlier
  measurement-label mentions of root and stalk lodging in the same clause.
- Focused data tests: 26 passed, 1 deselected.
- Real-data audit: 1 passed in 67.71 seconds.
- Ruff lint and format checks passed.
