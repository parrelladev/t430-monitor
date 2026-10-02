"""Leitura isolada das métricas de temperatura e ventoinha do T430."""
from dataclasses import dataclass
from enum import Enum
import glob
import os
import re


class MetricStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    INVALID = "invalid"


@dataclass(frozen=True)
class Metric:
    value: object
    unit: str
    status: MetricStatus
    source: str
    sensor_name: str = ""
    label: str = ""


@dataclass(frozen=True)
class MetricsSnapshot:
    temperatures: dict
    fan_speed: Metric
    fan_status: Metric
    fan_level: Metric
    fan_mode: Metric
    cpu_usage: Metric
    cpu_frequency: Metric
    memory_used: Metric
    memory_available: Metric
    batteries: dict


_previous_cpu_counters = None


def _unavailable(unit="", source=""):
    return Metric(None, unit, MetricStatus.UNAVAILABLE, source)


def _invalid(unit="", source="", sensor_name="", label=""):
    return Metric(None, unit, MetricStatus.INVALID, source, sensor_name, label)


def _read_text(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    except (OSError, UnicodeError):
        return None


def _temperature_metrics():
    results = {}
    invalid_metrics = {}
    try:
        paths = sorted(glob.glob("/sys/class/hwmon/hwmon*/temp*_input"))
    except OSError:
        paths = []

    for path in paths:
        source = path
        base = os.path.dirname(path)
        sensor_name = _read_text(os.path.join(base, "name")) or "sensor"
        label_path = path[:-6] + "_label"
        label = _read_text(label_path) or ""
        display_name = label or sensor_name
        try:
            raw = _read_text(path)
            milli_celsius = int(raw) if raw is not None else None
            celsius = milli_celsius / 1000 if milli_celsius is not None else None
        except (ValueError, TypeError, OverflowError):
            invalid_metrics[display_name] = _invalid("°C", source, sensor_name, label)
            continue

        key = "CPU" if sensor_name == "coretemp" else display_name
        if celsius is None or not 0 < celsius <= 125:
            invalid_metrics[key] = _invalid("°C", source, sensor_name, label)
            continue

        metric = Metric(celsius, "°C", MetricStatus.AVAILABLE, source, sensor_name, label)
        previous = results.get(key)
        # coretemp exposes package and per-core entries; keep the hottest reading.
        if previous is None or celsius > previous.value:
            results[key] = metric

    # The ACPI thermal list gives indexed channels, not component identities.
    # Never rename its first channel "CPU" unless a labeled source established that.
    if not results:
        source = "/proc/acpi/ibm/thermal"
        thermal = _read_text(source)
        if thermal is not None:
            line = next((line for line in thermal.splitlines()
                         if line.startswith("temperatures:")), None)
            if line is not None:
                payload = line.split(":", 1)[1].strip()
                tokens = payload.split()
                for index, token in enumerate(tokens):
                    name = f"thermal[{index}]"
                    try:
                        value = int(token)
                    except (ValueError, TypeError):
                        invalid_metrics[name] = _invalid("°C", source, "ibm_thermal", name)
                        continue
                    if 0 < value <= 125:
                        results[name] = Metric(float(value), "°C", MetricStatus.AVAILABLE,
                                               source, "ibm_thermal", name)
                    else:
                        invalid_metrics[name] = _invalid("°C", source, "ibm_thermal", name)

    results.update({key: metric for key, metric in invalid_metrics.items() if key not in results})
    if not results:
        results["CPU"] = _unavailable("°C", "/sys/class/hwmon and /proc/acpi/ibm/thermal")
    return results


def _fan_metrics():
    source = "/proc/acpi/ibm/fan"
    text = _read_text(source)
    if text is None:
        missing = _unavailable("", source)
        return _unavailable("RPM", source), missing, missing, _unavailable("", source)
    found = {}
    for key in ("status", "speed", "level"):
        match = re.search(rf"^{key}:\s*(.*?)\s*$", text, re.M | re.I)
        if match:
            found[key] = match.group(1).strip()

    speed = found.get("speed")
    if speed is None:
        speed_metric = _unavailable("RPM", source)
    elif re.fullmatch(r"\d+", speed):
        rpm = int(speed)
        speed_metric = (Metric(rpm, "RPM", MetricStatus.AVAILABLE, source, "thinkpad_acpi", "speed")
                        if 0 <= rpm <= 30000 else _invalid("RPM", source, "thinkpad_acpi", "speed"))
    else:
        speed_metric = _invalid("RPM", source, "thinkpad_acpi", "speed")

    def text_metric(key):
        value = found.get(key)
        if value is None:
            return _unavailable("", source)
        if not value or value.lower() in ("unknown", "invalid"):
            return _invalid("", source, "thinkpad_acpi", key)
        return Metric(value, "", MetricStatus.AVAILABLE, source, "thinkpad_acpi", key)

    level_metric = text_metric("level")
    status_metric = text_metric("status")
    raw_level = str(level_metric.value).strip().lower() if level_metric.status is MetricStatus.AVAILABLE else ""
    raw_status = str(status_metric.value).strip().lower() if status_metric.status is MetricStatus.AVAILABLE else ""
    if level_metric.status is not MetricStatus.AVAILABLE:
        mode = level_metric
    elif raw_level == "auto":
        # The ACPI driver normally reports status=enabled in automatic mode.
        if raw_status in ("enabled", "on"):
            mode = Metric("automático", "", MetricStatus.AVAILABLE, source, "thinkpad_acpi", "level/status")
        else:
            mode = _unavailable("", source)
    elif raw_level == "disengaged":
        mode = Metric("manual", "", MetricStatus.AVAILABLE, source, "thinkpad_acpi", "level/status")
    elif re.fullmatch(r"\d+", raw_level):
        number = int(raw_level)
        if 1 <= number <= 7 and raw_status in ("enabled", "on"):
            mode = Metric("manual", "", MetricStatus.AVAILABLE, source, "thinkpad_acpi", "level/status")
        elif 1 <= number <= 7:
            mode = _unavailable("", source)
        else:
            mode = _invalid("", source, "thinkpad_acpi", "level")
    else:
        mode = _unavailable("", source)
    return speed_metric, status_metric, level_metric, mode


def _cpu_usage_metric():
    global _previous_cpu_counters
    source = "/proc/stat"
    text = _read_text(source)
    if text is None:
        _previous_cpu_counters = None
        return _unavailable("%", source)
    line = next((line for line in text.splitlines() if line.startswith("cpu ")), None)
    if line is None:
        _previous_cpu_counters = None
        return _unavailable("%", source)
    try:
        fields = line.split()[1:]
        if len(fields) < 4:
            _previous_cpu_counters = None
            return _unavailable("%", source)
        counters = [int(value) for value in fields]
        if any(value < 0 for value in counters):
            _previous_cpu_counters = None
            return _unavailable("%", source)
    except (ValueError, TypeError, OverflowError):
        _previous_cpu_counters = None
        return _unavailable("%", source)

    previous = _previous_cpu_counters
    _previous_cpu_counters = counters
    if previous is None or len(previous) != len(counters):
        return _unavailable("%", source)
    deltas = [current - old for current, old in zip(counters, previous)]
    if any(delta < 0 for delta in deltas):
        return _unavailable("%", source)
    total = sum(deltas)
    if total <= 0:
        return _unavailable("%", source)
    idle = deltas[3] + (deltas[4] if len(deltas) > 4 else 0)
    usage = 100.0 * (total - idle) / total
    if not 0 <= usage <= 100:
        return _unavailable("%", source)
    return Metric(usage, "%", MetricStatus.AVAILABLE, source, "cpu", "total")


def _cpu_frequency_metric():
    pattern = "/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq"
    paths = [pattern, "/sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_cur_freq"]
    saw_invalid = False
    for source in paths:
        raw = _read_text(source)
        if raw is None:
            continue
        try:
            khz = int(raw)
        except (ValueError, TypeError, OverflowError):
            saw_invalid = True
            continue
        if khz <= 0 or khz > 10_000_000:
            saw_invalid = True
            continue
        return Metric(khz / 1000.0, "MHz", MetricStatus.AVAILABLE,
                      source, "cpu0", os.path.basename(source))
    if saw_invalid:
        return _unavailable("MHz", ", ".join(paths))
    return _unavailable("MHz", ", ".join(paths))


def _memory_metrics():
    source = "/proc/meminfo"
    text = _read_text(source)
    if text is None:
        unavailable = _unavailable("MiB", source)
        return unavailable, unavailable
    entries = {}
    try:
        for line in text.splitlines():
            match = re.fullmatch(r"([A-Za-z_()]+):\s+(\d+)\s+kB", line.strip())
            if match:
                entries[match.group(1)] = int(match.group(2))
        total = entries.get("MemTotal")
        available = entries.get("MemAvailable")
        if total is None or available is None or total <= 0 or not 0 <= available <= total:
            unavailable = _unavailable("MiB", source)
            return unavailable, unavailable
        used = total - available
        return (Metric(used / 1024.0, "MiB", MetricStatus.AVAILABLE, source, "memory", "used"),
                Metric(available / 1024.0, "MiB", MetricStatus.AVAILABLE, source,
                       "memory", "available"))
    except (ValueError, TypeError, OverflowError):
        unavailable = _unavailable("MiB", source)
        return unavailable, unavailable


def _battery_metrics():
    root = "/sys/class/power_supply"
    result = {}
    try:
        devices = sorted(glob.glob(os.path.join(root, "*")))
    except OSError:
        devices = []
    battery_devices = []
    for device in devices:
        kind = _read_text(os.path.join(device, "type"))
        if kind and kind.strip().lower() == "battery":
            battery_devices.append(device)
    if not battery_devices:
        return {"Bateria": {"charge": _unavailable("%", root),
                            "state": _unavailable("", root),
                            "time": _unavailable("min", root)}}

    for device in battery_devices:
        name = _read_text(os.path.join(device, "model_name")) or os.path.basename(device)
        source = device
        status_text = _read_text(os.path.join(device, "status"))
        status_map = {"charging": "carregando", "discharging": "descarregando",
                      "full": "carregada", "not charging": "conectada"}
        if status_text:
            normalized_status = status_map.get(status_text.lower())
            state = (Metric(normalized_status, "", MetricStatus.AVAILABLE, source,
                            "battery", "status") if normalized_status else
                     _unavailable("", os.path.join(device, "status")))
        else:
            state = _unavailable("", os.path.join(device, "status"))

        capacity_text = _read_text(os.path.join(device, "capacity"))
        if capacity_text is not None:
            try:
                capacity = int(capacity_text)
                charge = (Metric(capacity, "%", MetricStatus.AVAILABLE, source, "battery", "capacity")
                          if 0 <= capacity <= 100 else _unavailable("%", os.path.join(device, "capacity")))
            except (ValueError, TypeError, OverflowError):
                charge = _unavailable("%", os.path.join(device, "capacity"))
        else:
            charge_now = _read_numeric_attribute(device, "charge_now")
            charge_full = _read_numeric_attribute(device, "charge_full")
            if charge_now is None or charge_full is None or charge_full <= 0 or charge_now < 0 or charge_now > charge_full:
                energy_now = _read_numeric_attribute(device, "energy_now")
                energy_full = _read_numeric_attribute(device, "energy_full")
                charge_now, charge_full = energy_now, energy_full
            if charge_now is not None and charge_full and charge_full > 0 and 0 <= charge_now <= charge_full:
                charge = Metric(100.0 * charge_now / charge_full, "%", MetricStatus.AVAILABLE,
                                source, "battery", "charge_now/charge_full")
            else:
                charge = _unavailable("%", source)

        remaining = _battery_time_metric(device, status_text)
        result[name] = {"charge": charge, "state": state, "time": remaining}
    return result


def _read_numeric_attribute(device, name):
    raw = _read_text(os.path.join(device, name))
    if raw is None:
        return None
    try:
        return int(raw)
    except (ValueError, TypeError, OverflowError):
        return None


def _battery_time_metric(device, status):
    source = device
    if status not in ("charging", "discharging"):
        return _unavailable("min", source)
    now_name, rate_name = (("energy_now", "power_now") if status == "discharging"
                           else ("energy_full", "power_now"))
    energy = _read_numeric_attribute(device, now_name)
    power = _read_numeric_attribute(device, rate_name)
    if energy is None or power is None or energy < 0 or power <= 0:
        return _unavailable("min", source)
    # Both Linux power_supply attributes use microwatt-hours / microwatts.
    minutes = 60.0 * energy / power
    if not 0 <= minutes <= 7 * 24 * 60:
        return _unavailable("min", source)
    return Metric(minutes, "min", MetricStatus.AVAILABLE, source, "battery", "estimated_time")


def collect_metrics():
    """Return a best-effort snapshot, containing failures per metric."""
    try:
        temperatures = _temperature_metrics()
    except Exception:
        temperatures = {"CPU": _invalid("°C", "/sys/class/hwmon and /proc/acpi/ibm/thermal")}
    try:
        fan_speed, fan_status, fan_level, fan_mode = _fan_metrics()
    except Exception:
        source = "/proc/acpi/ibm/fan"
        fan_speed = _invalid("RPM", source)
        fan_status = _invalid("", source)
        fan_level = _invalid("", source)
        fan_mode = _invalid("", source)
    try:
        cpu_usage = _cpu_usage_metric()
    except Exception:
        cpu_usage = _unavailable("%", "/proc/stat")
    try:
        cpu_frequency = _cpu_frequency_metric()
    except Exception:
        cpu_frequency = _unavailable("MHz", "/sys/devices/system/cpu/cpu0/cpufreq")
    try:
        memory_used, memory_available = _memory_metrics()
    except Exception:
        memory_used = _unavailable("MiB", "/proc/meminfo")
        memory_available = _unavailable("MiB", "/proc/meminfo")
    try:
        batteries = _battery_metrics()
    except Exception:
        root = "/sys/class/power_supply"
        batteries = {"Bateria": {"charge": _unavailable("%", root),
                                  "state": _unavailable("", root),
                                  "time": _unavailable("min", root)}}
    return MetricsSnapshot(temperatures, fan_speed, fan_status, fan_level, fan_mode,
                           cpu_usage, cpu_frequency, memory_used, memory_available, batteries)
