from __future__ import annotations

import unittest

from app import MediaDownloaderApp, can_remove_job, can_scroll_region, restore_window, wheel_units
from media_downloader.jobs import JobState


class AppHelpersTest(unittest.TestCase):
    def test_all_inactive_jobs_can_be_removed(self) -> None:
        self.assertTrue(can_remove_job(JobState.READY))
        self.assertTrue(can_remove_job(JobState.COMPLETED))
        self.assertTrue(can_remove_job(JobState.FAILED))
        self.assertFalse(can_remove_job(JobState.DOWNLOADING))

    def test_mouse_wheel_delta_is_normalized_and_zero_is_ignored(self) -> None:
        self.assertEqual(wheel_units(120), -1)
        self.assertEqual(wheel_units(240), -2)
        self.assertEqual(wheel_units(-120), 1)
        self.assertEqual(wheel_units(0), 0)

    def test_scroll_region_must_overflow_viewport(self) -> None:
        self.assertFalse(can_scroll_region(None, 200))
        self.assertFalse(can_scroll_region((0, 0, 100, 200), 200))
        self.assertTrue(can_scroll_region((0, 0, 100, 201), 200))

    def test_restore_window_runs_visibility_and_focus_actions(self) -> None:
        calls: list[str] = []

        class Window:
            def deiconify(self):
                calls.append("deiconify")

            def lift(self):
                calls.append("lift")

            def focus_force(self):
                calls.append("focus_force")

            def after_idle(self, callback):
                calls.append("after_idle")
                callback()

        restore_window(Window())
        self.assertEqual(calls, ["deiconify", "lift", "after_idle", "focus_force"])

    def test_empty_output_setting_is_logged_without_tk_callback_crash(self) -> None:
        logs: list[str] = []

        class Value:
            def get(self):
                return ""

        class AppLike:
            output_var = Value()
            _output_dir = MediaDownloaderApp._output_dir

            def _append_log(self, text: str) -> None:
                logs.append(text)

        MediaDownloaderApp._persist_output_dir(AppLike())
        self.assertEqual(len(logs), 1)
        self.assertIn("не удалось сохранить папку", logs[0])


if __name__ == "__main__":
    unittest.main()
