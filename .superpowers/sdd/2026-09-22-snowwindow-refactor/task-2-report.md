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
