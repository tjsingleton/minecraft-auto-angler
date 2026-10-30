.PHONY: setup lint format format-check test check build run run\:loop sessions\:clean

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

check: lint format-check test

build:
	uv build
