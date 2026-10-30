# Working on AutoAngler

Use Python 3.13 and uv 0.13.6. Install the pinned uv release with `uv self update 0.13.6`
for standalone installations, or the equivalent versioned installer for your package manager.

## Commands

- `make setup`: install the locked runtime and development dependencies.
- `make check`: Ruff lint, Ruff format check, and the default pytest suite.
- `make format`: apply Ruff fixes and formatting; inspect the resulting diff.
- `make build`: build the wheel and source distribution.
- `uv run --locked python scripts/smoke_wheel.py dist/*.whl`: install and check the built wheel.
- `make run`: launch the actual desktop application. This can capture the screen and control input.

On headless Linux, run tests and wheel checks under `xvfb-run -a`. CI installs the display,
Tk, and native-library prerequisites. Verify Tk imports with
`uv run --locked python -c 'import tkinter; print(tkinter.TkVersion)'`.

## Architecture and test boundaries

Read `docs/architecture.md` for state ownership, runtime flow, and codebase-memory CLI
refresh instructions. `autoangler.__main__`
parses configuration, `gui_tk.AutoFishTkApp` coordinates Tk and fishing state, and
`async_pipeline` owns vision and recording workers. Detectors and offline analysis commands
are independently testable. Preserve the CLI, hotkeys, legacy launcher, and artifact formats.

Default tests use fixtures and fakes. Keep live screen and Tk capability tests opt-in with
`AUTOANGLER_INTEGRATION=1`. Do not enable them on CI. Live fishing and audio validation need
a permitted desktop and Minecraft; follow `docs/validation.md` and report unperformed checks.

On macOS, use supported browser tools for browsing. If a future project test launches Chrome
or Chromium through Playwright, request narrowly scoped execution outside the Codex sandbox
before the first launch, preserve temporary profiles, and verify the test result.

Sessions, recordings, profiles, and traces live under `~/.autoangler/sessions/`.
Offline analysis can write beside its input; experiment results default to
`~/.autoangler/experiment-log.jsonld`. Preserve unrelated changes and user data.
Do not run `make sessions:clean` as routine verification. Keep `.DS_Store` and local agent
artifacts ignored. CI rejects tracked `.DS_Store` files at any directory depth.

Use `pyproject.toml` and `uv.lock` for dependency changes. Update them together with the
pinned uv release, then run `make check`, build, and the wheel smoke check. No handwritten
requirements file is maintained. CI checks macOS and Linux on Python 3.13.

## Agent skills

### Issue tracker

Track work in the Minecraft Auto Angler project on Linear's TJ Singleton team.
See `docs/agents/issue-tracker.md`.

### Triage labels

Use the five canonical triage labels. See `docs/agents/triage-labels.md`.

### Domain docs

Use a single-context layout. See `docs/agents/domain.md`.
