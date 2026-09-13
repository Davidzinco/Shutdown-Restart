import subprocess
import unittest
from datetime import datetime
from unittest.mock import patch

from power_control import Countdown, execute_power, power_command, scheduled_delay, validate_minutes


class ScheduleTests(unittest.TestCase):
    def test_today(self):
        seconds, target = scheduled_delay("22:30", datetime(2026, 9, 13, 22, 0))
        self.assertEqual(seconds, 1800)
        self.assertEqual(target, datetime(2026, 9, 13, 22, 30))

    def test_past_or_current_time_uses_tomorrow(self):
        for now in (datetime(2026, 12, 31, 22, 30), datetime(2026, 12, 31, 23, 0)):
            _, target = scheduled_delay("22:30", now)
            self.assertEqual(target, datetime(2027, 1, 1, 22, 30))

    def test_invalid_time(self):
        for value in ("", "25:00", "12:60", "noon"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                scheduled_delay(value)


class CountdownTests(unittest.TestCase):
    def setUp(self):
        self.now = 100
        self.timer = Countdown(lambda: self.now)

    def test_deadline_no_extra_second_and_execute_once(self):
        self.timer.start(60, "shutdown")
        self.now = 159.2
        self.assertEqual(self.timer.snapshot()[0], 1)
        self.assertIsNone(self.timer.take_due())
        self.now = 160
        self.assertEqual(self.timer.snapshot(), (0, 100))
        self.assertEqual(self.timer.take_due(), "shutdown")
        self.assertIsNone(self.timer.take_due())

    def test_delayed_poll_catches_up(self):
        self.timer.start(60, "restart")
        self.now = 180
        self.assertEqual(self.timer.take_due(), "restart")

    def test_duplicate_rejected(self):
        self.timer.start(60, "shutdown")
        with self.assertRaises(RuntimeError):
            self.timer.start(10, "restart")
        self.assertEqual(self.timer.action, "shutdown")

    def test_cancel_at_deadline_and_reschedule(self):
        self.timer.start(60, "shutdown")
        self.now = 160
        self.assertTrue(self.timer.cancel())
        self.assertIsNone(self.timer.take_due())
        self.assertFalse(self.timer.cancel())
        self.timer.start(3, "restart")
        self.now += 3
        self.assertEqual(self.timer.take_due(), "restart")

    def test_invalid_input(self):
        for value in ("", "abc", "0", "-1", "121", "1.5"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                validate_minutes(value)
        self.assertEqual(validate_minutes(" 120 "), 120)
        self.assertEqual(validate_minutes("1"), 1)


class CommandTests(unittest.TestCase):
    @patch("power_control.sys.frozen", True, create=True)
    @patch("power_control.sys.platform", "linux")
    @patch.dict("os.environ", {"LD_LIBRARY_PATH": "/bundle", "LD_LIBRARY_PATH_ORIG": "/host"})
    @patch("power_control.subprocess.run")
    def test_frozen_linux_restores_host_library_path(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        execute_power(["fake-command"])
        self.assertEqual(run.call_args.kwargs["env"]["LD_LIBRARY_PATH"], "/host")

    @patch("power_control.sys.frozen", True, create=True)
    @patch("power_control.sys.platform", "linux")
    @patch.dict("os.environ", {"LD_LIBRARY_PATH": "/bundle"}, clear=True)
    @patch("power_control.subprocess.run")
    def test_frozen_linux_removes_bundle_library_path(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        execute_power(["fake-command"])
        self.assertNotIn("LD_LIBRARY_PATH", run.call_args.kwargs["env"])

    @patch("power_control.shutil.which", side_effect=lambda name: "/commands/" + name)
    def test_platform_commands(self, _):
        self.assertEqual(power_command("shutdown", "Windows"), ["/commands/shutdown.exe", "/s", "/t", "0"])
        self.assertEqual(power_command("restart", "Windows"), ["/commands/shutdown.exe", "/r", "/t", "0"])
        self.assertEqual(power_command("shutdown", "Linux"), ["/commands/systemctl", "--no-ask-password", "poweroff"])
        self.assertEqual(power_command("restart", "Linux"), ["/commands/systemctl", "--no-ask-password", "reboot"])

    def test_invalid_platform_and_action(self):
        with self.assertRaises(RuntimeError):
            power_command("shutdown", "Darwin")
        with self.assertRaises(ValueError):
            power_command("invalid", "Linux")

    @patch("power_control.shutil.which", return_value=None)
    def test_missing_command(self, _):
        with self.assertRaises(RuntimeError):
            power_command("shutdown", "Linux")

    @patch("power_control.subprocess.run")
    def test_dry_run_never_executes(self, run):
        self.assertIn("Dry run", execute_power(["fake-command"], dry_run=True))
        run.assert_not_called()

    @patch("power_control.subprocess.run")
    def test_success(self, run):
        run.return_value = subprocess.CompletedProcess([], 0, "", "")
        self.assertIn("accepted", execute_power(["fake-command"]))
        self.assertNotIn("shell", run.call_args.kwargs)

    @patch("power_control.subprocess.run")
    def test_permission_failure(self, run):
        run.return_value = subprocess.CompletedProcess([], 1, "", "Access denied")
        with self.assertRaisesRegex(RuntimeError, "Access denied"):
            execute_power(["fake-command"])

    @patch("power_control.subprocess.run", side_effect=subprocess.TimeoutExpired("fake", 30))
    def test_timeout(self, _):
        with self.assertRaisesRegex(RuntimeError, "may already"):
            execute_power(["fake-command"])

    @patch("power_control.subprocess.run", side_effect=FileNotFoundError("gone"))
    def test_spawn_error(self, _):
        with self.assertRaisesRegex(RuntimeError, "Cannot run"):
            execute_power(["fake-command"])


if __name__ == "__main__":
    unittest.main()
