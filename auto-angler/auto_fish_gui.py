from concurrent.futures import ThreadPoolExecutor
from time import monotonic, sleep, time

import PySimpleGUI as sg
import numpy as np
# TODO replace use of pyautogui w\ pynput. Needed the latter for keybinding.
import pyautogui
from pynput import keyboard

from cursor_camera import CursorCamera
from cursor_locator import CursorLocator
from image_viewer import ImageViewer

# The default pause sometimes cause the cast to also retrieve
pyautogui.PAUSE = 0.01

MINECRAFT_TICKS_PER_MC_DAY = 24000
MINECRAFT_TICKS_PER_HOUR = MINECRAFT_TICKS_PER_MC_DAY / 24
MINECRAFT_IRL_MINUTES_PER_MC_DAY = 20
MINECRAFT_IRL_MINUTES_PER_MC_HOUR = MINECRAFT_IRL_MINUTES_PER_MC_DAY / 24
MINECRAFT_IRL_SECONDS_PER_MC_HOUR = MINECRAFT_IRL_MINUTES_PER_MC_HOUR * 60


class AutoFishGUI:
    def __init__(self):
        sg.theme('DarkGray4')

        self._magnification: int = 10

        self._cursor_position: tuple[int, int] = None
        self._is_fishing = False
        self._exiting = False
        self._is_line_out = False
        # TODO used as the dumbest thing that could work, replace w\ something like a ZSET from redis
        self._executor: ThreadPoolExecutor = ThreadPoolExecutor(max_workers=10)

        self._loop_index: int = 0
        self._loop_durations = np.zeros(100)
        self._tick_interval: int = 0
        self._current_clock: int = 0
        self._start_clock: int = None

        self._image_viewer = ImageViewer()
        self._camera = CursorCamera(self._magnification)
        self._cursor_image = self._camera.blank()

        self._keyboard_listener = keyboard.Listener(on_press=self._on_key_press)
        self._keyboard_listener.start()

        self._threshold = self._magnification * 22

        self._button = sg.Button('Start Fishing', font='Any 16')
        self._status_text: sg.Text = sg.Text()

        self._window = sg.Window('MC AutoAngler',
                                 [
                                     self._image_viewer.layout_row(),
                                     [self._button, self._status_text]
                                 ],
                                 relative_location=(300, 0),
                                 keep_on_top=True, finalize=True)

    def run(self):
        while True:
            event, values = self._window.read(timeout=int(1000 / 30))
            start_time = monotonic()

            if event and event not in ["__TIMEOUT__"]:
                print("gui event " + event)

            if event == sg.WIN_CLOSED:
                break

            if event == 'Start Fishing':
                self._handle_fishing_button()

            if event == 'LocateCursor':
                self._locate_cursor()
                self._cast()

            if event == 'LineIsOut':
                if self._is_fishing:
                    self._is_line_out = True

            if self._cursor_position:
                self._update_image()

            if self._is_fish_on():
                self._reel()
                self._cast()

            if self._is_fishing:
                # TODO extract the clock and benchmark to a class
                now = time()
                if not self._start_clock:
                    self._current_clock = now
                    self._start_clock = now

                next_clock_position = self._current_clock + MINECRAFT_IRL_SECONDS_PER_MC_HOUR
                # print(next_clock_position, now)
                if now >= next_clock_position:
                    self._tick_interval = (self._tick_interval + 1) % 23
                    self._current_clock = next_clock_position

                duration = round(monotonic() - start_time, 3)

                self._loop_index = (self._loop_index + 1) % self._loop_durations.size
                self._loop_durations[self._loop_index] = duration

                status = f"{self._cursor_image.black_pixel_count} < {self._threshold} {int(now - self._start_clock)}s {self._tick_interval}h {duration}ms avg: {round(np.average(self._loop_durations), 3)}ms"
                self._status_text.update(value=status)

        self._exit()

    def _handle_fishing_button(self):
        if self._is_fishing:
            self._stop()
        else:
            self._start()

    def _start(self):
        print("gui start")
        self._is_fishing = True
        self._button.update(text="Stop Fishing")

        # give time to focus on minecraft
        self.trigger_event_in(event='LocateCursor', delay=5)

    def _stop(self):
        print("gui stop")
        self._is_fishing = False
        self._current_comp_image = None
        self._cursor_position = None
        self._is_line_out = False
        self._start_clock = None

        if not self._exiting:
            self._button.update(text="Start Fishing")

    def trigger_event_in(self, delay: int, event: str):
        def trigger():
            print(f"trigger {event} in {delay}")
            sleep(delay)
            self._window.write_event_value(event, None)

        self._executor.submit(trigger)

    def _locate_cursor(self):
        cursor = CursorLocator()
        self._cursor_position = None
        for _ in range(5):
            self._cursor_position = cursor.locate()

            if self._cursor_position:
                print(f"cursor found. position={self._cursor_position}")
                return

        print("Could not find minecraft cursor")

    def _cast(self):
        print('cast')
        self._use_rod()
        self.trigger_event_in(3, 'LineIsOut')

    def _reel(self):
        print('reel')
        self._use_rod()
        self._is_line_out = False

    def _use_rod(self):
        pyautogui.rightClick()

    def _on_key_press(self, key):
        if key == keyboard.Key.f12:
            print(f'{key} pressed')
            self._start()

        if key == keyboard.Key.esc:
            print(f'{key} pressed')
            self._stop()

        if key == keyboard.Key.f10:
            self._window.write_event_value(sg.WIN_CLOSED, None)

    def _update_image(self):
        try:
            self._cursor_image = self._camera.capture(self._cursor_position)
            self._image_viewer.update(self._cursor_image)
        except OSError as err:
            # FIXME better handling. Thrown when the capture fails.
            # It should be afe to skip a cycle and recover.
            print(err)

    def _is_fish_on(self):
        if not self._is_fishing or not self._is_line_out:
            return False

        return self._cursor_image.black_pixel_count <= self._threshold

    def _exit(self):
        self._exiting = True
        self._stop()
        self._keyboard_listener.stop()
        self._window.close()
