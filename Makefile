.PHONY: run run\:loop sessions\:clean

run:
	uv run python -m autoangler

run\:loop:
	@set -eu; \
	while true; do \
		echo "Starting AutoAngler (Ctrl-C to stop loop)..."; \
		if uv run python -m autoangler; then \
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
