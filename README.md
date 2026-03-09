# minecraft-auto-angler

A toy project to automate fishing in minecraft.

Why?

1. It's an easy source of XP. Unlike a mob farm, fishing doesn't decrease hunger. 
2. You get treasure enchants. Hello "Mending I" books!
3. It impresses my kids. 

## Setup and run

Install [uv](https://docs.astral.sh/uv/) (e.g. `curl -LsSf https://astral.sh/uv/install.sh | sh`), then from the repo root:

```bash
uv sync
uv run python -m autoangler
```

Optional (recommended for contributors):

```bash
uv sync --group dev
```

Experimental macOS audio probe:

```bash
uv run python -m autoangler.audio_probe --title-hint Minecraft
```

This probe uses ScreenCaptureKit to target Minecraft app audio and prints `BITE_CANDIDATE` lines when
it sees a strong transient that looks like a fishing splash. It is macOS-only and currently separate
from the main Tk auto-angler loop.

Legacy launcher (kept for backward compatibility):

```bash
cd auto-angler && uv run python auto-angler.py
```

Note: this project now uses `tkinter`. If you see `ModuleNotFoundError: No module named '_tkinter'`, install a Python
distribution with Tk support (common fix on macOS when using `asdf`: `brew install tcl-tk@8` then reinstall Python).
Screen capture now defaults to `mss`. To force the old Pillow capture path for comparison or fallback, launch with
`AUTOANGLER_CAPTURE_BACKEND=pil`.

macOS permissions: this project uses screen capture and input control. You may need to enable permissions for the app
you launch it from (Terminal, iTerm, VS Code, etc.) in System Settings → Privacy & Security:

- Accessibility (needed for global hotkeys and input control)
- Input Monitoring (needed for global hotkeys via `pynput`)
- Screen Recording (needed for screenshots via `PIL.ImageGrab`)

The experimental audio probe also depends on the same macOS screen/system-audio capture permission path
because ScreenCaptureKit is what provides application audio.

## How to Use

When you start AutoAngler, click `Locate Minecraft` once so the app can anchor itself to the Java game window.
Then click `Start Fishing` or press `F12`. The button path waits 5 seconds so you can refocus Minecraft. `F12`
starts immediately from inside Minecraft.
The app restores its last window position on launch.
The control row also shows whether the line is currently in or out.

Press `F9` to calibrate the cursor tracking box without clicking back to the AutoAngler window. This is useful after the
line is in the water, since clicking away from Minecraft opens the menu screen. Press `F8` to save the current debug
preview and log the filename to the active session log. Press `F7` to arm or disarm recording. While armed and fishing,
AutoAngler writes these artifacts into a per-run folder under `~/.autoangler/sessions/<session>/`:

- periodic PNG captures
- a whole-window raw video (`...-window.mp4`)
- a debug composite video (`...-debug.mp4`)

Press `M` to mark a manual bite in the session trace when you see a fish hit but AutoAngler does not. Press `F6` to mark
that bite and force an immediate reel/recast cycle. Marks also dump a short frame series into the session folder so you
can inspect the lead-up and aftermath. Use the `Open Sessions` button to jump straight to the current session folder in
Finder.

![](docs/cursor_location.png)

Once the window is located, the software casts and reels automatically. Line the cast up so the fishing line and splash
area sit inside the calibrated tracking box. The left preview shows the full fishing ROI with the tracked box overlaid.
The default ROI is biased toward the lower-right portion of the Minecraft window because the cast target and rod tend to
stay there when the camera is fixed.

![](docs/in_action.png)

The image on the right shows only the tracked detection box. Dark line pixels stay black against a white background.
When those dark pixels drop sharply inside that box, the app treats that as a bite and reels.

The bite trigger now uses a rolling reference from the calibrated tracking box instead of one hardcoded pixel threshold.
If it still misses fish, recalibrate with `F9` after the line lands.
After a reel, AutoAngler waits briefly before casting again to avoid colliding with the item you just pulled in. You can
override that delay with `AUTOANGLER_RECAST_DELAY_MS`.

The debug panel shows the current ROI, tracking box, scored detection box, video filenames, last mark clip, last saved
capture, last profile file, last trace file, last capture error, and a live profiling line (`fps`, tick, capture,
detect, preview, record, top stage, RSS memory). While preview capture is active, AutoAngler writes a per-session
`...-profile.csv` with those stage timings. While fishing, it also emits periodic `PROFILE ...` log lines. While
recording is armed, AutoAngler writes a per-session trace CSV with line pixels, trigger threshold, weak-frame count,
and bite decisions so you can correlate missed bites against the captured frames. For denser PNG capture during
testing, set `AUTOANGLER_RECORD_INTERVAL_MS` before launch. To change how often profile summaries are logged, set
`AUTOANGLER_PROFILE_LOG_INTERVAL_S`.

To summarize a session profile, run
`uv run python -m autoangler.profile_session /path/to/session-profile.csv`.

To capture a sampling-profiler flame graph for a live run, use
`./scripts/profile_flamegraph.sh /path/to/output-flame.svg`.
If you omit the path, it writes to `~/.autoangler/flamegraph.svg`.

To inspect a frame offline with the current detector, run
`uv run python -m autoangler.analyze_image /path/to/frame.png`.
It writes a crop, processed mask, overlay, and JSON summary next to the image.

To replay a recorded session against a detector configuration and append a JSON-LD experiment result, run
`uv run python -m autoangler.experiment_harness /path/to/session.log --trace /path/to/session-trace.csv --box x1,y1,x2,y2`.
Results append to `~/.autoangler/experiment-log.jsonld` by default.

To append a capture-backend benchmark entry from a session profile, run
`uv run python -m autoangler.experiment_harness /path/to/session.log --profile /path/to/session-profile.csv --backend mss`.
Use `--backend pil` when logging a Pillow comparison run.

From within minecraft to release the cursor you must hit ESC. This also stops fishing. 

F10 will exit the software. 

## Tips

Place a backstop behind you with a hopper and chest. It doesn't take long to overflow your inventory.

![](docs/backstop.png)

Add overflow protection if you want to run it overnight. I've filled 9 chests before.

![](docs/overflow_protection.png)

An [auto-dropper](https://www.sportskeeda.com/minecraft/how-make-automatic-item-dropper-minecraft) that drops on cactus 
or lava serves as a time saving trash can. 

![](docs/auto-dropper_trash-can.png)

One of the treasures you can catch while fishing are enchanted rods. You want Lure III, Luck of the Sea III, and 
Mending. If you fish long enough, you'll catch a dozen of the OP rods.

If you are fishing inside to the outside, be sure to put a half-slab in front of you. This prevents you 
from inadvertently falling or getting knocked out of the opening and drowning.

If you are fishing inside, you want to make sure you're fishing in "open water" there shouldn't be any 
blocks within a 5x5 box centered around the bobber. If you want the rain bonus, then the rain must hit the 
bobber. You can find out more on the [Minecraft Wiki](https://minecraft.fandom.com/wiki/Fishing).

You'll end up catching a ton of enchanted books, bows, and rods. Even if you don't need them, keep them. Think of them 
as XP batteries. When you are ready to enchant something, you just strip off the XP in a grindstone. 

![](docs/fishing_inside.png)

## TODO

- Handle squid interference in the fishing ROI so wandering mobs do not look like bite activity.

## Credits

The detection method was based on this article: 
[Let’s Go Fishing! Writing a Minecraft 1.17 Auto-Fishing Bot in Python, OpenCV and PyAutoGUI](https://medium.com/geekculture/lets-go-fishing-writing-a-minecraft-1-17-auto-fishing-bot-in-python-opencv-and-pyautogui-6bfb5d539fcf) 
