VENV_BIN := .venv/bin
RUFF := $(VENV_BIN)/ruff
PYTEST := $(VENV_BIN)/pytest

.PHONY: lint test check

lint:
	$(RUFF) check src tests

test:
	$(PYTEST) -q

check: lint test
