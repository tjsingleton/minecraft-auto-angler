# Architecture

AutoAngler is a Python desktop application with a Tk operator window. Its main runtime
coordinates screen capture, bite detection, input actions, and session recording. Separate
commands analyze frames and recorded sessions without launching the fishing UI.

## Runtime flow and ownership

1. `autoangler.__main__` parses CLI timing and feature flags, builds `RuntimeConfig`,
   configures session logging, and starts `AutoFishTkApp`.
2. `gui_tk.AutoFishTkApp` owns operator state, Tk callbacks, fishing phase, window/ROI
   context, action scheduling, and application shutdown. It creates the capture backend
   and passes it to the cursor camera and locator. GUI changes belong on the Tk thread.
3. The capture backend supplies RGB frames. `mss` is the default; the Pillow implementation
   is selected with `AUTOANGLER_CAPTURE_BACKEND=pil`. Window discovery uses Quartz on macOS
   and the PyAutoGUI path elsewhere.
4. `async_pipeline.VisionWorker` owns a worker thread, a single pending request, and a
   result queue. New pending work replaces an older pending frame, counting the dropped
   frame. The processor uses the line, rod, and pause-menu detectors. The GUI polls results
   and tracks epochs and sequence numbers before applying them.
5. `line_watcher.LineWatcher` maintains the rolling bite reference and weak-frame state.
   The GUI coordinates the resulting reel/recast actions and user hotkeys.
6. `async_pipeline.RecordingWorker` owns the recording command queue and its recorder.
   It copies queued frame data and serializes recording operations on its thread.
   `session_recorder.SessionRecorder` owns video writers and mark clips. The GUI also
   writes profiling and trace telemetry using paths from `logging_utils`.

The optional `audio_probe.AudioHintMonitor` runs a Swift ScreenCaptureKit helper and
collects splash candidates. Its helper is compiled from the adjacent Swift source when
needed. Source distributions and wheels exclude the checked-in ARM64 executable; macOS
users need Xcode Command Line Tools to compile it. Audio hints remain optional and use
the screen/system-audio permission path.

## Entry points and artifacts

- `autoangler` and `python -m autoangler`: desktop runtime.
- `python -m autoangler.analyze_image`: frame crop, mask, overlay, and JSON analysis.
- `python -m autoangler.profile_session`: recorded profile summaries.
- `python -m autoangler.experiment_harness`: detector replay and capture benchmarks.
- `python -m autoangler.audio_probe`: optional macOS audio probe.
- `auto-angler/auto-angler.py`: compatibility launcher for the same application.

Session logs, PNGs, video, trace CSVs, and profile CSVs normally live under
`~/.autoangler/sessions/<session>/`. The experiment log defaults to
`~/.autoangler/experiment-log.jsonld`. Frame analysis writes beside the input image.
Treat recorded captures and session data as user data, not test fixtures to delete.

## Test boundaries

Default pytest coverage exercises detectors with arrays and templates, worker behavior,
configuration, GUI coordination methods, and recording with temporary files or fakes.
GUI-related imports require Tk and, on Linux, an X display even when no window is opened.
CI uses Xvfb on Linux. Native screenshots and real Tk capability checks require the explicit
`AUTOANGLER_INTEGRATION=1` opt-in. See `validation.md` for live desktop validation.

## Codebase-memory navigation

Use `list_projects`, then `index_status` to select the graph rooted at this checkout.
Use `get_architecture`, `search_graph`, `get_code_snippet`, and `trace_path` for structure,
definitions, and call relationships. Check `has_more` or cursors and paginate as needed.
Call `check_index_coverage` for relevant paths and scopes; read flagged source directly.

The full index refreshed on 2026-10-30 contains 919 nodes and 4,289 edges, with no skipped
files. It records partial parsing at the first line of `Makefile`, which was inspected directly.
Image templates and screenshots are intentionally excluded by suffix; Git metadata, caches,
virtual environments, build output, and local `.omc` state are excluded. These exclusions do
not imply missing runtime assets.

The analysis-only MCP connector can read the graph. Use the installed CLI to refresh it:

```sh
codebase-memory-mcp cli index_repository --repo-path . --mode full --persistence false
```

Then use `index_status` and `check_index_coverage` through the CLI or MCP tools to verify
status, metadata freshness, and affected-path coverage. Select the project returned by the
indexing command. The CLI also supports `--help` after a tool name for its arguments.
No compressed graph artifact is committed; each checkout can refresh its local index.
Coverage remains best-effort evidence rather than a guarantee that no parse gaps exist.
