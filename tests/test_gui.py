"""GUI regression tests. Require Tk and a display; no real power commands run."""
import time
import os
import unittest
from unittest.mock import patch
from types import SimpleNamespace

import python_exp as gui

REQUIRE_GUI = os.environ.get("SHUTDOWN_REQUIRE_GUI") == "1"
if REQUIRE_GUI and gui.tk is None:
    raise RuntimeError("GUI tests require Tkinter, but it is unavailable.")


@unittest.skipIf(gui.tk is None, "Tkinter unavailable")
class GuiTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = gui.tk.Tk()
        except gui.tk.TclError as exc:
            if REQUIRE_GUI:
                raise
            self.skipTest(str(exc))
        self.root.withdraw()
        self.app = gui.PowerApp(self.root, dry_run=True)
        self.now = 0
        self.app.timer.clock = lambda: self.now
        self.command_patch = patch("python_exp.power_command", return_value=["fake-power"])
        self.command_patch.start()
        self.run_patch = patch("power_control.subprocess.run", side_effect=AssertionError("Real command forbidden"))
        self.run = self.run_patch.start()
        self.addCleanup(self.command_patch.stop)
        self.addCleanup(self.run_patch.stop)
        self.addCleanup(self.cleanup_root)

    def cleanup_root(self):
        try:
            if self.app.job:
                self.root.after_cancel(self.app.job)
            self.root.destroy()
        except gui.tk.TclError:
            pass

    def advance(self, seconds):
        self.now += seconds
        if self.app.job:
            self.root.after_cancel(self.app.job)
        self.app.tick()

    def finish_worker(self):
        deadline = time.monotonic() + 3
        while self.app.executing and time.monotonic() < deadline:
            self.root.update()
            time.sleep(0.01)
        self.assertFalse(self.app.executing)

    def test_duplicate_cancel_and_restart(self):
        self.app.start("shutdown")
        self.app.start("restart")
        self.assertEqual(self.app.timer.action, "shutdown")
        self.assertTrue(self.app.shutdown_button.instate(["disabled"]))
        self.app.cancel()
        self.assertFalse(self.app.timer.active)
        self.assertIsNone(self.app.job)
        self.assertFalse(self.app.shutdown_button.instate(["disabled"]))
        self.app.start("restart")
        self.assertEqual(self.app.timer.action, "restart")
        self.run.assert_not_called()

    def test_preset_and_clock_schedule(self):
        self.app.preset(15)
        self.assertEqual(self.app.delay.get(), "15")
        self.assertEqual(self.app.mode.get(), "Delay")
        self.app.mode.set("At time")
        self.app.at_time.set("22:30")
        self.app.start("restart")
        self.assertTrue(self.app.timer.active)
        self.assertIn("22:30:00", self.app.target.cget("text"))
        self.assertTrue(self.app.mode_box.instate(["disabled"]))

    def test_schedule_mode_shows_only_relevant_input(self):
        self.assertEqual(self.app.spin.winfo_manager(), "grid")
        self.assertEqual(self.app.time_entry.winfo_manager(), "")
        self.app.mode.set("At time")
        self.assertEqual(self.app.spin.winfo_manager(), "")
        self.assertEqual(self.app.time_entry.winfo_manager(), "grid")
        self.assertEqual(self.app.presets.winfo_manager(), "")
        self.app.preset(30)
        self.assertEqual(self.app.spin.winfo_manager(), "grid")
        self.assertEqual(self.app.presets.winfo_manager(), "grid")

    def test_details_toggle_preserves_log(self):
        self.assertEqual(self.app.details.winfo_manager(), "")
        self.app.log("Test activity")
        self.app.details_button.invoke()
        self.assertEqual(self.app.details.winfo_manager(), "grid")
        self.assertIn("Test activity", self.app.log_text.get("1.0", "end"))
        self.app.details_button.invoke()
        self.assertEqual(self.app.details.winfo_manager(), "")

    def test_timeline_hover_does_not_change_schedule(self):
        self.app.start("shutdown")
        deadline = self.app.timer.deadline
        self.app.timeline.configure(width=400)
        self.root.update_idletasks()
        self.app.inspect_timeline(SimpleNamespace(x=200))
        self.assertIsNotNone(self.app.inspected_progress)
        self.assertEqual(self.app.timer.deadline, deadline)
        self.assertEqual(self.app.timer.action, "shutdown")
        self.assertEqual(self.app.progress.get(), 0)
        self.app.leave_timeline()
        self.assertIsNone(self.app.inspected_progress)
        self.run.assert_not_called()

    def test_timeline_tracks_elapsed_and_resets_on_cancel(self):
        self.app.start("shutdown")
        self.advance(30)
        self.assertEqual(self.app.progress.get(), 50)
        self.assertEqual(self.app.time_label.cget("text"), "00:30")
        captions = [self.app.timeline.itemcget(item, "text")
                    for item in self.app.timeline.find_all()
                    if self.app.timeline.type(item) == "text"]
        self.assertIn("00:30  elapsed", captions)
        self.assertIn("50%", captions)
        self.app.cancel()
        self.assertEqual(self.app.progress.get(), 0)

    def test_long_countdown_uses_hours(self):
        self.app.delay.set("120")
        self.app.start("shutdown")
        self.assertEqual(self.app.time_label.cget("text"), "02:00:00")
        self.advance(1)
        self.assertEqual(self.app.time_label.cget("text"), "01:59:59")

    @patch("python_exp.messagebox.showerror")
    def test_invalid_input(self, error):
        self.app.delay.set("invalid")
        self.app.start("shutdown")
        error.assert_called_once()
        self.assertFalse(self.app.timer.active)

    def test_simulation_completes(self):
        self.app.start("shutdown")
        self.advance(60)
        self.assertTrue(self.app.cancel_button.instate(["disabled"]))
        self.finish_worker()
        self.assertEqual(self.app.target.cget("text"), "Simulation complete")
        self.run.assert_not_called()

    @patch("python_exp.messagebox.showerror")
    @patch("python_exp.execute_power", side_effect=RuntimeError("Access denied"))
    def test_failure_restores_controls(self, execute, error):
        self.app.start("restart")
        self.advance(60)
        self.finish_worker()
        self.assertEqual(self.app.target.cget("text"), "Command failed")
        self.assertFalse(self.app.shutdown_button.instate(["disabled"]))
        error.assert_called_once()

    @patch("python_exp.platform.system", return_value="Windows")
    @patch("python_exp.close_windows_apps")
    def test_cancel_in_app_closure_grace_period(self, close, system):
        self.app.close_apps.set(True)
        self.app.start("shutdown")
        self.advance(60)
        self.assertTrue(self.app.closing_phase)
        self.app.cancel()
        self.advance(3)
        self.assertFalse(self.app.executing)
        close.assert_not_called()  # Simulation must also skip app closure.
        self.run.assert_not_called()

    @patch("python_exp.platform.system", return_value="Windows")
    @patch("python_exp.close_windows_apps", side_effect=OSError("Cannot enumerate windows"))
    def test_app_closure_failure_cancels_power(self, close, system):
        self.app.dry_run = False
        self.app.close_apps.set(True)
        self.app.start("shutdown")
        self.advance(60)
        close.assert_called_once()
        self.assertFalse(self.app.timer.active)
        self.assertFalse(self.app.executing)
        self.assertFalse(self.app.shutdown_button.instate(["disabled"]))
        self.run.assert_not_called()

    @patch("python_exp.messagebox.askyesno", return_value=False)
    def test_decline_exit_preserves_countdown(self, ask):
        self.app.start("shutdown")
        self.app.on_close()
        self.assertTrue(self.app.timer.active)

    @patch("python_exp.messagebox.askyesno", return_value=True)
    def test_exit_cancels_countdown(self, ask):
        self.app.start("shutdown")
        self.app.on_close()
        self.assertFalse(self.app.timer.active)
        self.assertIsNone(self.app.job)
        self.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
