# AutoAngler

AutoAngler observes a selected Minecraft game window to detect fishing activity.
Capture selection is separate from control of the game.

## Language

**Selected game window**:
The particular running Minecraft game window chosen for capture. Its title,
position, size, and visibility can change without making it a different window.
_Avoid_: Active window, foreground window

**Replacement game window**:
A new Minecraft game window that takes the place of a previously selected window.
A matching title or appearance does not make it the same window.

**Capture suspension**:
A temporary pause in observation while the selected game window is unavailable.
The selection remains, but observation resumes only when that same window can be
verified and captured again.
