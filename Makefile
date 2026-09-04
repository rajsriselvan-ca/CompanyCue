PYTHON ?= python3

.PHONY: install dev test check

install:
	@test -d .venv || $(PYTHON) -m venv .venv
	.venv/bin/pip install -e './backend[test]'
	npm --prefix frontend install

dev:
	./scripts/dev.sh

test:
	.venv/bin/pytest -q backend
	npm --prefix frontend test -- --runInBand

check: test
	npm --prefix frontend run lint
	npm --prefix frontend run build
