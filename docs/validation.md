# Validation

## Automated checks

Use uv 0.13.6 and Python 3.13:

```sh
make setup
uv run --locked python -c 'import tkinter; print(tkinter.TkVersion)'
make check
make build
uv run --locked python scripts/smoke_wheel.py dist/*.whl
make test-sensitivity
make verify-sdist
```

On headless Linux install `xvfb`, `xauth`, `python3-tk`, `libgl1`, and `libglib2.0-0`.
Run `xvfb-run -a make test` and wrap replay, sensitivity, wheel, and source-distribution
verification commands in `xvfb-run -a` too.
The uv-managed Python must also provide Tk; installing system Tk alone does not repair
an unrelated Python build that omitted the module.

The smoke script creates an isolated environment outside the checkout, installs the built
wheel with lockfile constraints, checks CLI help and offline command help, and verifies
templates and Swift source. It also runs actual image analysis, profile summarization,
and detector replay through subprocess CLIs, including two append-only experiment writes.
It rejects packaged native audio executables and local desktop artifacts. It does not
start fishing, screen capture, or audio capture. It requires network access for dependencies.
`make verify-sdist` extracts the source archive into a separate directory, installs locked
development dependencies, runs lint/format/tests, rebuilds both distributions, and runs
the expanded installed-wheel check against that rebuilt wheel.

CI performs default tests and packaging checks on macOS and Linux. The macOS job also
compiles the Swift helper into the runner's temporary directory without executing it.
A passing local run does not establish that hosted CI has passed.

## Runtime replay and refactor gates

`make test-replay` runs the connected runtime and offline CLI scenarios. These tests are
also part of the default `make check` suite. The shared driver constructs the real GUI
coordinator, detectors, vision worker, recording worker, and recorder. It replaces screen
capture, window discovery, global listening, audio input, game input, and Tk timing.
Native capture and unexpected input calls fail immediately. Workers use real threads;
events and bounded waits control their progress. The driver advances virtual time and
explicitly pumps real coordinator ticks rather than waiting for wall-clock fishing delays.

The scenarios cover complete fishing cycles, weak/disappearing lines, stop/restart with
pending work, pause recovery, stale/duplicate results, frame replacement, window geometry,
recalibration, capture errors, movement/audio options, recording toggles and mark clips,
queue pressure, copied frames, shutdown, and CLI/artifact compatibility. MP4 checks decode
frames and verify dimensions. They do not compare codec bytes or platform-specific GUI pixels.
The synthetic scenes establish behavior contracts; they do not measure detection accuracy
across real Minecraft lighting, texture packs, or desktop configurations.

`make test-sensitivity` verifies that selected scenarios pass in a disposable copy, then
checks that each of three intentional regressions causes an assertion failure: removing
the scheduled-action generation guard, removing stale-epoch rejection, and retaining the
oldest pending vision request. Each mutation starts from the same source snapshot. The
script never changes the working checkout. CI runs this check on macOS and Linux.

Replay tests save input frames, detector masks, observed action timelines, state transitions,
session artifacts, and assertion failures under pytest's temporary directory. CLI scenarios
save subprocess arguments, exit status, stdout, and stderr. CI uploads these files and pytest
reports on failure with seven-day retention. Verification scripts retain temporary directories
on failure and print their paths. Use `--work <new-directory>` to retain successful script
runs too. Each explicit directory must be new, so rerunning cannot overwrite prior evidence.

Before refactoring, require default checks, sensitivity checks, and installed-package checks
to pass. Repeat the relevant connected scenarios after each small change. Review a newly
exposed bug separately; do not regenerate expected results to accept it silently. For
performance-sensitive changes, compare the same replay workload on the same machine and
retain measurements. Shared-runner timing is not an acceptance threshold.

## Opt-in Tk wiring

```sh
AUTOANGLER_INTEGRATION=1 uv run --locked pytest tests/test_tk_runtime_integration.py
```

This test opens the real application UI in a bounded child process. It exercises menus,
global-hotkey callback dispatch onto the Tk thread, real preview rendering, indicators,
recording/manual-action routing, saved window geometry, and the window-close protocol.
Screen capture, hotkey listening, audio, and game input remain replaced with fakes. It
does not need Minecraft or capture/input permissions. It remains opt-in and disabled in CI.
When explicitly enabled, startup or callback failures fail the test rather than being skipped.
On headless Linux, wrap the command with Xvfb.

## Live macOS validation checklist

Status after repository setup: **pending**. These checks require Minecraft and a desktop
with Accessibility, Input Monitoring, and Screen Recording permissions for the launching app.
For audio, install Xcode Command Line Tools and grant the applicable system-audio permission.

- In a controlled Minecraft scene, launch with
  `uv run --locked python -m autoangler --no-auto-strafe`; confirm the window and ROI.
- Move or resize Minecraft; confirm ROI recalibration. Exercise manual recalibration with F9.
- Exercise F12 start/stop, including stopping during a pending recast. Confirm no further
  automatic fishing actions occur. Global ESC is ignored; use the Minecraft pause menu
  to exercise pause detection.
- Exercise F8 cast/reel and complete at least five automatic fishing cycles. Observe
  bite/recast behavior and catch counts. Verify auto-strafe separately after the base run.
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
