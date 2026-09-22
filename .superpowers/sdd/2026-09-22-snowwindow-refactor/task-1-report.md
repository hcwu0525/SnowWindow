# Task 1 report — Standard project and domain foundation

## Files changed

- `pyproject.toml`
- `configs/g2f_demo.yaml`
- `configs/g2f_history.yaml`
- `src/snowwindow/__init__.py`
- `src/snowwindow/__main__.py`
- `src/snowwindow/adapters.py`
- `src/snowwindow/cli.py`
- `src/snowwindow/config.py`
- `src/snowwindow/domain.py`
- `tests/snowwindow/test_adapters.py`
- `tests/snowwindow/test_cli.py`
- `tests/snowwindow/test_config.py`
- `tests/snowwindow/test_domain.py`
- `.superpowers/sdd/2026-09-22-snowwindow-refactor/task-1-report.md`

## RED and GREEN

- RED: `.venv-py39/bin/python -m pytest -q tests/snowwindow`
  - Outcome: collection stopped with four expected `ModuleNotFoundError`
    errors because the `snowwindow` package did not exist.
- RED: `.venv-py39/bin/python -m pytest -q
  tests/snowwindow/test_config.py::test_bundled_configs_encode_required_experiment_policies`
  - Outcome: one expected failure because
    `SelectionConfig.all_eligible_environments` did not exist.
- GREEN: `.venv-py39/bin/python -m pytest -q tests/snowwindow`
  - Outcome: 30 passed.
- GREEN: `.venv-py39/bin/python -m pytest -q`
  - Outcome: 44 passed, including 14 legacy tests.
- GREEN: `.venv-py39/bin/ruff check src tests/snowwindow`
  - Outcome: all checks passed.
- GREEN: `.venv-py39/bin/ruff format --check src tests/snowwindow`
  - Outcome: all files formatted after applying Ruff once.
- GREEN: `.venv-py39/bin/python -m pip check`
  - Outcome: no broken requirements found.
- GREEN: `.venv-py39/bin/snowwindow audit --config configs/g2f_demo.yaml`
  - Outcome: exited 2 with `audit: not implemented`, as required for
    placeholder stages.

## Design decisions

- The package uses a standard `src/` layout with setuptools and declares only
  PyYAML as a runtime dependency; pytest and Ruff are optional development
  dependencies.
- Domain records are frozen dataclasses. Nested mappings and sequences are
  converted to immutable containers during construction.
- Domain serialization recursively converts dates, paths, enums, nested
  records, and containers to JSON-compatible values. Canonical JSON sorts
  mapping keys before SHA-256 content hashing.
- Model-specific inputs remain inside `model.parameters` and
  `SimulationRequest.model_parameters`; the foundation does not import
  AquaCrop.
- Configuration records retain explicit shared fields and preserve additional
  selection/simulation settings in immutable option mappings for later tasks.
- The history configuration explicitly enables all eligible environments,
  assumed-rainfed inputs, and default-soil exclusion from calibration.
- CLI stages validate their configuration before returning a nonzero,
  stage-specific `not implemented` message.

## Remaining concerns

- Stage implementations are intentionally deferred to later refactor tasks.
- Domain fields may be extended as normalization and adapter work defines
  additional model-independent values; the serialization and hashing contract
  is intended to remain stable.

## Fix round 1 — 2026-09-22

### Files changed

- `src/snowwindow/domain.py`
- `src/snowwindow/config.py`
- `tests/snowwindow/test_domain.py`
- `tests/snowwindow/test_config.py`
- `.superpowers/sdd/2026-09-22-snowwindow-refactor/task-1-report.md`

### RED and GREEN

- RED: `.venv-py39/bin/python -m pytest -q
  tests/snowwindow/test_domain.py::test_equal_records_with_signed_zero_are_not_python_hashable`
  - Outcome: one expected failure because equal records containing `-0.0` and
    `0.0` still provided the custom SHA-derived Python hash.
- GREEN: `.venv-py39/bin/python -m pytest -q tests/snowwindow/test_domain.py`
  - Outcome: 4 passed after making domain records explicitly unhashable.
- RED: `.venv-py39/bin/python -m pytest -q
  tests/snowwindow/test_config.py::test_load_config_rejects_non_boolean_settings`
  - Outcome: four expected failures because quoted boolean strings were
    accepted through `bool(value)`.
- GREEN: `.venv-py39/bin/python -m pytest -q
  tests/snowwindow/test_config.py::test_load_config_rejects_non_boolean_settings`
  - Outcome: 4 passed after requiring actual YAML booleans.
- RED: `.venv-py39/bin/python -m pytest -q
  tests/snowwindow/test_config.py::test_load_config_recursively_freezes_nested_sequence_values`
  - Outcome: one expected failure because mappings inside a list remained
    mutable.
- GREEN: `.venv-py39/bin/python -m pytest -q
  tests/snowwindow/test_config.py::test_load_config_recursively_freezes_nested_sequence_values`
  - Outcome: 1 passed after recursively freezing list and tuple elements.
- GREEN: `.venv-py39/bin/python -m pytest -q tests/snowwindow`
  - Outcome: 36 passed.
- GREEN: `.venv-py39/bin/python -m pytest -q`
  - Outcome: 50 passed, including 14 legacy tests.
- GREEN: `.venv-py39/bin/ruff check src tests/snowwindow`
  - Outcome: all checks passed.
- GREEN: `.venv-py39/bin/ruff format --check src tests/snowwindow`
  - Outcome: all files formatted.

### Design decisions

- Domain records no longer implement Python hashing. This avoids violating
  Python's equal-object hash contract for values such as `-0.0` and `0.0`;
  `content_hash()` remains the deterministic, mapping-order-independent
  content identifier.
- Explicit boolean configuration fields accept only YAML booleans. Strings,
  numbers, and other truthy or falsey values raise `ConfigError`.
- Configuration mappings now recursively freeze mappings nested at any depth
  inside list or tuple values.

### Remaining concerns

- None introduced by this fix round.
