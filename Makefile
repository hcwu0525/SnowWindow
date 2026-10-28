.DEFAULT_GOAL := help

PYTHON ?= .venv/bin/python
VENV_PYTHON ?= python3.10
CONFIG ?= configs/g2f_demo.yaml

.PHONY: help venv install setup check lint test test-integration \
	audit prepare baseline calibrate validate simulate scan report forecast run catalog

help:
	@echo "make setup                  Create Python 3.10 environment and install"
	@echo "make check                  Check dependencies, style and unit tests"
	@echo "make test-integration       Run local real-model/data tests"
	@echo "make run CONFIG=...         Run the main pipeline (not forecast)"
	@echo "make forecast CONFIG=...    Run retrospective forecast after source run"
	@echo "make catalog CONFIG=...     Index the configured output directory"
	@echo "Override PYTHON or VENV_PYTHON to select an interpreter."

venv:
	@if command -v uv >/dev/null 2>&1; then \
		uv venv --python "$(VENV_PYTHON)" --seed .venv; \
	else \
		$(VENV_PYTHON) -m venv .venv; \
	fi

install:
	$(PYTHON) -m pip install -r requirements-aquacrop.lock.txt -e '.[dev]'
	$(PYTHON) -m pip check

setup: venv
	$(MAKE) install

lint:
	$(PYTHON) -m ruff check src tests/snowwindow scripts

test:
	PYTEST_ADDOPTS="-m 'not integration'" $(PYTHON) -m pytest -q

test-integration:
	PYTEST_ADDOPTS="-m integration" $(PYTHON) -m pytest -q

check:
	$(PYTHON) -m pip check
	$(MAKE) lint
	$(MAKE) test

audit prepare baseline calibrate validate simulate scan report forecast run catalog:
	$(PYTHON) -m snowwindow $@ --config "$(CONFIG)"
