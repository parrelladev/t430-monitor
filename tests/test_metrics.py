import unittest
from unittest.mock import patch

import metrics


class FakeFiles:
    def __init__(self, values):
        self.values = values

    def __call__(self, path):
        return self.values.get(path)


class MetricCollectionTests(unittest.TestCase):
    def setUp(self):
        metrics._previous_cpu_counters = None

    def test_missing_temperature_sources_are_unavailable(self):
        with patch.object(metrics.glob, "glob", return_value=[]), patch.object(
                metrics, "_read_text", FakeFiles({"/proc/acpi/ibm/thermal": None})):
            result = metrics._temperature_metrics()
        self.assertEqual(result["CPU"].status, metrics.MetricStatus.UNAVAILABLE)

    def test_temperature_channels_keep_labels_and_invalid_channels(self):
        paths = ["/sys/class/hwmon/hwmon0/temp1_input", "/sys/class/hwmon/hwmon0/temp2_input"]
        values = {
            "/sys/class/hwmon/hwmon0/name": "thinkpad",
            paths[0]: "54000", "/sys/class/hwmon/hwmon0/temp1_label": "CPU",
            paths[1]: "bad", "/sys/class/hwmon/hwmon0/temp2_label": "GPU",
        }
        with patch.object(metrics.glob, "glob", return_value=paths), patch.object(
                metrics, "_read_text", FakeFiles(values)):
            result = metrics._temperature_metrics()
        self.assertEqual(result["CPU"].value, 54.0)
        self.assertEqual(result["CPU"].label, "CPU")
        self.assertEqual(result["GPU"].status, metrics.MetricStatus.INVALID)

    def test_proc_thermal_does_not_guess_cpu_and_skips_invalid_tokens(self):
        with patch.object(metrics.glob, "glob", return_value=[]), patch.object(
                metrics, "_read_text", FakeFiles({"/proc/acpi/ibm/thermal": "temperatures: 51 bad 500"})):
            result = metrics._temperature_metrics()
        self.assertNotIn("CPU", result)
        self.assertEqual(result["thermal[0]"].value, 51.0)
        self.assertEqual(result["thermal[1]"].status, metrics.MetricStatus.INVALID)
        self.assertEqual(result["thermal[2]"].status, metrics.MetricStatus.INVALID)

    def test_fan_source_missing_and_malformed_are_isolated(self):
        with patch.object(metrics, "_read_text", return_value=None):
            speed, status, level, mode = metrics._fan_metrics()
        self.assertEqual(speed.status, metrics.MetricStatus.UNAVAILABLE)
        self.assertEqual(mode.status, metrics.MetricStatus.UNAVAILABLE)

        with patch.object(metrics, "_read_text", return_value="status: enabled\nspeed: fast\nlevel: 9"):
            speed, status, level, mode = metrics._fan_metrics()
        self.assertEqual(speed.status, metrics.MetricStatus.INVALID)
        self.assertEqual(mode.status, metrics.MetricStatus.INVALID)

    def test_fan_file_without_level_keeps_other_fields_and_unknown_mode(self):
        with patch.object(metrics, "_read_text", return_value="status: enabled\nspeed: 2400"):
            speed, status, level, mode = metrics._fan_metrics()
        self.assertEqual(speed.value, 2400)
        self.assertEqual(status.value, "enabled")
        self.assertEqual(level.status, metrics.MetricStatus.UNAVAILABLE)
        self.assertEqual(mode.status, metrics.MetricStatus.UNAVAILABLE)

    def test_fan_mode_recognizes_auto_manual_and_unknown(self):
        for text, expected in (("status: enabled\nlevel: auto", "automático"),
                               ("status: enabled\nlevel: 4", "manual"),
                               ("status: unknown\nlevel: auto", None)):
            with self.subTest(text=text), patch.object(metrics, "_read_text", return_value=text):
                mode = metrics._fan_metrics()[3]
                self.assertEqual(mode.value, expected)
                self.assertEqual(mode.status, metrics.MetricStatus.AVAILABLE if expected else
                                 metrics.MetricStatus.UNAVAILABLE)

    def test_first_cpu_sample_unavailable_then_delta_is_used(self):
        samples = iter(("cpu 10 0 20 70 0\n", "cpu 20 0 30 80 0\n"))
        with patch.object(metrics, "_read_text", side_effect=lambda _path: next(samples)):
            first = metrics._cpu_usage_metric()
            second = metrics._cpu_usage_metric()
        self.assertEqual(first.status, metrics.MetricStatus.UNAVAILABLE)
        self.assertEqual(second.status, metrics.MetricStatus.AVAILABLE)
        self.assertAlmostEqual(second.value, 66.6666667)

    def test_inaccessible_or_incomplete_cpu_source_is_unavailable(self):
        with patch.object(metrics, "_read_text", return_value=None):
            self.assertEqual(metrics._cpu_usage_metric().status, metrics.MetricStatus.UNAVAILABLE)
        with patch.object(metrics, "_read_text", return_value="cpu 1 2\n"):
            self.assertEqual(metrics._cpu_usage_metric().status, metrics.MetricStatus.UNAVAILABLE)

    def test_frequency_bad_sources_do_not_raise(self):
        with patch.object(metrics, "_read_text", return_value="garbage"):
            result = metrics._cpu_frequency_metric()
        self.assertEqual(result.status, metrics.MetricStatus.UNAVAILABLE)

    def test_memory_missing_or_malformed_is_unavailable(self):
        with patch.object(metrics, "_read_text", return_value=None):
            used, available = metrics._memory_metrics()
        self.assertEqual(used.status, metrics.MetricStatus.UNAVAILABLE)
        with patch.object(metrics, "_read_text", return_value="MemTotal: nope kB\n"):
            used, available = metrics._memory_metrics()
        self.assertEqual(available.status, metrics.MetricStatus.UNAVAILABLE)

    def test_memory_valid_values_are_calculated_independently_of_hardware(self):
        with patch.object(metrics, "_read_text", return_value=
                           "MemTotal: 2048 kB\nMemAvailable: 512 kB\n"):
            used, available = metrics._memory_metrics()
        self.assertEqual(used.value, 1.5)
        self.assertEqual(available.value, 0.5)
        self.assertEqual(used.unit, "MiB")

    def test_battery_absent_and_malformed_is_unavailable(self):
        with patch.object(metrics.glob, "glob", return_value=[]):
            result = metrics._battery_metrics()
        self.assertEqual(result["Bateria"]["charge"].status, metrics.MetricStatus.UNAVAILABLE)

        root = "/sys/class/power_supply/BAT0"
        values = {root + "/type": "Battery", root + "/status": "mystery",
                  root + "/capacity": "101"}
        with patch.object(metrics.glob, "glob", return_value=[root]), patch.object(
                metrics, "_read_text", FakeFiles(values)):
            result = metrics._battery_metrics()
        self.assertEqual(result["BAT0"]["charge"].status, metrics.MetricStatus.UNAVAILABLE)
        self.assertEqual(result["BAT0"]["state"].status, metrics.MetricStatus.UNAVAILABLE)

    def test_battery_valid_status_charge_and_time_estimate(self):
        root = "/sys/class/power_supply/BAT0"
        values = {root + "/type": "Battery", root + "/model_name": "Test battery",
                  root + "/status": "discharging", root + "/capacity": "75",
                  root + "/energy_now": "30000000", root + "/power_now": "15000000"}
        with patch.object(metrics.glob, "glob", return_value=[root]), patch.object(
                metrics, "_read_text", FakeFiles(values)):
            result = metrics._battery_metrics()["Test battery"]
        self.assertEqual(result["charge"].value, 75)
        self.assertEqual(result["state"].value, "descarregando")
        self.assertEqual(result["time"].value, 120)

    def test_per_metric_os_error_does_not_abort_snapshot(self):
        with patch.object(metrics, "_temperature_metrics", side_effect=OSError), \
             patch.object(metrics, "_fan_metrics", side_effect=OSError), \
             patch.object(metrics, "_cpu_usage_metric", side_effect=OSError), \
             patch.object(metrics, "_cpu_frequency_metric", side_effect=OSError), \
             patch.object(metrics, "_memory_metrics", side_effect=OSError), \
             patch.object(metrics, "_battery_metrics", side_effect=OSError):
            snapshot = metrics.collect_metrics()
        self.assertEqual(snapshot.temperatures["CPU"].status, metrics.MetricStatus.INVALID)
        self.assertEqual(snapshot.fan_speed.status, metrics.MetricStatus.INVALID)
        self.assertEqual(snapshot.cpu_usage.status, metrics.MetricStatus.UNAVAILABLE)
        self.assertEqual(snapshot.cpu_frequency.status, metrics.MetricStatus.UNAVAILABLE)
        self.assertEqual(snapshot.memory_used.status, metrics.MetricStatus.UNAVAILABLE)
        self.assertEqual(snapshot.batteries["Bateria"]["time"].status,
                         metrics.MetricStatus.UNAVAILABLE)

    def test_one_metric_exception_does_not_hide_other_metrics(self):
        with patch.object(metrics, "_temperature_metrics", side_effect=OSError("missing")), \
             patch.object(metrics, "_fan_metrics", return_value=(
                 metrics.Metric(900, "RPM", metrics.MetricStatus.AVAILABLE, "/fan"),
                 metrics._unavailable(), metrics._unavailable(), metrics._unavailable())), \
             patch.object(metrics, "_cpu_usage_metric", return_value=metrics._unavailable("%", "/proc/stat")), \
             patch.object(metrics, "_cpu_frequency_metric", side_effect=OSError("missing")), \
             patch.object(metrics, "_memory_metrics", return_value=(
                 metrics.Metric(1, "MiB", metrics.MetricStatus.AVAILABLE, "/proc/meminfo"),
                 metrics.Metric(2, "MiB", metrics.MetricStatus.AVAILABLE, "/proc/meminfo"))), \
             patch.object(metrics, "_battery_metrics", side_effect=OSError("missing")):
            snapshot = metrics.collect_metrics()
        self.assertEqual(snapshot.temperatures["CPU"].status, metrics.MetricStatus.INVALID)
        self.assertEqual(snapshot.fan_speed.value, 900)
        self.assertEqual(snapshot.memory_used.value, 1)
        self.assertEqual(snapshot.batteries["Bateria"]["charge"].status,
                         metrics.MetricStatus.UNAVAILABLE)


if __name__ == "__main__":
    unittest.main()
