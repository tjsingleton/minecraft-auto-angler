# Validation

## Automated checks

Use uv 0.13.6 and Python 3.13:

```sh
make setup
uv run --locked python -c 'import tkinter; print(tkinter.TkVersion)'
make check
make build
uv run --locked python scripts/smoke_wheel.py dist/*.whl
```

On headless Linux install `xvfb`, `xauth`, `python3-tk`, `libgl1`, and `libglib2.0-0`.
Run `xvfb-run -a make test` and wrap the wheel smoke command in `xvfb-run -a` too.
The uv-managed Python must also provide Tk; installing system Tk alone does not repair
an unrelated Python build that omitted the module.

The smoke script creates an isolated environment outside the checkout, installs the built
wheel with lockfile constraints, checks CLI help and offline command help, and verifies templates and Swift source.
It rejects packaged native audio executables and local desktop artifacts. It does not
start fishing, screen capture, or audio capture. It requires network access for dependencies.

CI performs default tests and packaging checks on macOS and Linux. The macOS job also
compiles the Swift helper into the runner's temporary directory without executing it.
A passing local run does not establish that hosted CI has passed.

## Live macOS validation checklist

Status after repository setup: **pending**. These checks require Minecraft and a desktop
with Accessibility, Input Monitoring, and Screen Recording permissions for the launching app.
For audio, install Xcode Command Line Tools and grant the applicable system-audio permission.

- Launch with `make run`; confirm the Minecraft window and ROI are found.
- Move or resize Minecraft; confirm ROI recalibration. Exercise manual recalibration with F9.
- Exercise F12 start/stop and ESC stop. Confirm no fishing actions continue after stopping.
- Exercise F8 cast/reel and observe automatic bite/recast behavior and catch counts.
- Toggle recording with F7; confirm video, captures, and trace/profile data in the session folder.
- Open the Minecraft pause menu; confirm detection blocks fishing and recovery resumes safely.
- Toggle the debug view with F10 and exit cleanly with Cmd+Q.
- With `--audio-hints`, verify helper compilation and hint logging without losing vision behavior.

Record the Python/dependency versions, desktop permissions, session artifact path, observed
results, and any failed checks in the relevant Linear issue. Do not mark unperformed checks
as passed. The optional capability checks can be run separately with
`AUTOANGLER_INTEGRATION=1 uv run --locked pytest tests/test_capabilities_integration.py`;
they do not replace the fishing checklist.

## Setup verification on 2026-10-30

Verified locally on macOS ARM64 with Python 3.13.18 and uv 0.13.6:

- Locked setup, Ruff lint and formatting, and the default suite: 180 passed, 2 opt-in checks skipped.
- Fresh extraction of the source archive: locked setup, checks, and rebuilding both distributions passed.
- Wheel built from that extraction: isolated install with lockfile constraints, CLI/offline help,
  package location, and all five image assets passed.
- Distribution inspection: Swift source included; native executable, desktop metadata, and
  local cache/state excluded. The source archive contains the lockfile and setup/test files.
- Swift helper compiled successfully without execution; workflow validation passed actionlint 1.7.12.

Linux execution remains pending. A local container attempt failed while storing the Python
image with a Docker I/O error before tests ran; the host system disk was nearly full.
Hosted GitHub Actions also remains pending because these workflow changes have not been
published. Live Minecraft checks remain pending. The full codebase-memory index was refreshed through
`codebase-memory-mcp cli` and read back as ready with 919 nodes, 4,289 edges, no skipped
files, and the documented partial Makefile parsing.
