import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import t430_monitor
from metrics import MetricStatus, _unavailable


class FakeMonitor:
    """Call selected Monitor methods without constructing Tk or requiring a display."""
    refresh = t430_monitor.Monitor.refresh
    apply_level = t430_monitor.Monitor.apply_level

    def __init__(self):
        self.refresh_job = 123
        self.refresh_calls = 0
        self.destroyed = False
        self.warnings = []
        self.errors = []
        self.notice = SimpleNamespace(configure=lambda **kwargs: None)
        self.fan_mode_observed = "unknown"
        self.closing_after_auto = False

    def after_cancel(self, _job):
        pass

    def winfo_exists(self):
        return True

    def after(self, delay, callback):
        self.refresh_calls += 1
        self.last_delay = delay
        self.last_callback = callback
        return 456

    def _metric_catalog(self, _snapshot):
        return {}

    def _refresh_history_options(self, _catalog):
        pass

    def _show_primary(self, _snapshot):
        raise RuntimeError("simulated presentation error")

    def _show_secondary(self, _snapshot):
        pass

    def draw_graph(self):
        pass

    def destroy(self):
        self.destroyed = True


class MonitorLogicTests(unittest.TestCase):
    def test_refresh_error_still_schedules_single_next_cycle(self):
        fake = FakeMonitor()
        with patch.object(t430_monitor, "collect_metrics", return_value=object()):
            t430_monitor.Monitor.refresh(fake)
        self.assertEqual(fake.refresh_calls, 1)
        self.assertEqual(fake.last_delay, t430_monitor.REFRESH_MS)
        self.assertEqual(fake.refresh_job, 456)

    def test_helper_absent_has_clear_warning_without_subprocess(self):
        fake = FakeMonitor()
        with patch.object(t430_monitor.os.path, "exists", return_value=False), \
             patch.object(t430_monitor.messagebox, "showwarning") as warning, \
             patch.object(t430_monitor.subprocess, "run") as run:
            self.assertFalse(t430_monitor.Monitor.apply_level(fake, "1"))
        warning.assert_called_once()
        run.assert_not_called()

    def test_pkexec_absent_and_cancelled_helper_report_failure(self):
        fake = FakeMonitor()
        with patch.object(t430_monitor.os.path, "exists", return_value=True), \
             patch.object(t430_monitor.subprocess, "run", side_effect=FileNotFoundError), \
             patch.object(t430_monitor.messagebox, "showerror") as error:
            self.assertFalse(t430_monitor.Monitor.apply_level(fake, "2"))
        self.assertIn("pkexec", error.call_args.args[0])

        with patch.object(t430_monitor.os.path, "exists", return_value=True), \
             patch.object(t430_monitor.subprocess, "run", return_value=SimpleNamespace(
                 returncode=126, stderr="", stdout="")), \
             patch.object(t430_monitor.messagebox, "showerror") as error:
            self.assertFalse(t430_monitor.Monitor.apply_level(fake, "2"))
        self.assertIn("cancelada", error.call_args.args[1])

    def test_helper_failure_is_reported_and_does_not_claim_state_changed(self):
        fake = FakeMonitor()
        with patch.object(t430_monitor.os.path, "exists", return_value=True), \
             patch.object(t430_monitor.subprocess, "run", return_value=SimpleNamespace(
                 returncode=3, stderr="fan_control=N", stdout="")), \
             patch.object(t430_monitor.messagebox, "showerror") as error:
            self.assertFalse(t430_monitor.Monitor.apply_level(fake, "auto"))
        self.assertIn("helper não aplicou", error.call_args.args[1])

    def test_success_requests_acpi_recheck_not_local_manual_state(self):
        fake = FakeMonitor()
        with patch.object(t430_monitor.os.path, "exists", return_value=True), \
             patch.object(t430_monitor.subprocess, "run", return_value=SimpleNamespace(
                 returncode=0, stderr="", stdout="")):
            self.assertTrue(t430_monitor.Monitor.apply_level(fake, "3"))
        self.assertEqual(fake.fan_mode_observed, "unknown")


if __name__ == "__main__":
    unittest.main()
