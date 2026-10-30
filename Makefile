.PHONY: setup lint format format-check test test-replay test-sensitivity check build verify-sdist run run\:loop sessions\:clean

run:
	uv run --locked python -m autoangler

run\:loop:
	@set -eu; \
	while true; do \
		echo "Starting AutoAngler (Ctrl-C to stop loop)..."; \
		if uv run --locked python -m autoangler; then \
			echo "AutoAngler exited; restarting in 1s..."; \
			sleep 1; \
		else \
			status=$$?; \
			echo "AutoAngler exited with status $$status; stopping loop."; \
			exit $$status; \
		fi; \
	done

sessions\:clean:
	rm -rf sessions screenshots
	mkdir -p sessions screenshots

setup:
	uv sync --locked --group dev

lint:
	uv run --locked ruff check .

format:
	uv run --locked ruff check --fix .
	uv run --locked ruff format .

format-check:
	uv run --locked ruff format --check .

test:
	uv run --locked pytest

test-replay:
	uv run --locked pytest tests/test_runtime_replay.py tests/test_worker_lifecycle.py tests/test_cli_roundtrip.py

test-sensitivity:
	uv run --locked python scripts/verify_test_sensitivity.py

check: lint format-check test

build:
	uv build

verify-sdist:
	uv run --locked python scripts/verify_sdist.py dist/*.tar.gz
