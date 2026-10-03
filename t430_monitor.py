#!/usr/bin/env python3
"""Compact local Tkinter dashboard for Linux ThinkPad T430."""
import os
import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from collections import deque

from metrics import MetricStatus, collect_metrics

REFRESH_MS = 2000
HELPER = "/usr/local/libexec/t430-fan-helper"
HISTORY_SIZE = 120

COLORS = {
    "canvas": "#FFFAF0", "surface": "#FAF5E8", "card": "#F5F0E0",
    "strong": "#EBE6D6", "ink": "#0A0A0A", "body": "#3A3A3A",
    "muted": "#6A6A6A", "soft": "#9A9A9A", "line": "#E5E0D4",
    "cpu": "#6C72FF", "cpu_soft": "#E8E6FF", "gpu": "#118676",
    "ram": "#FF4D8B", "ram_soft": "#FFE1EC", "storage": "#E8A72E",
    "network": "#15A985", "sensor": "#8064D9", "sensor_soft": "#EEE7FF",
    "warning": "#F59E0B", "error": "#EF4444", "success": "#22C55E",
}


class Monitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("T430 • Monitor")
        self.geometry("356x900+1200+24")
        self.minsize(320, 560)
        self.maxsize(390, 1200)
        self.configure(bg=COLORS["canvas"])
        self.fan_mode_observed = "desconhecido"
        self.closing_after_auto = False
        self.close_auto_checks = 0
        self.expanded = tk.BooleanVar(value=False)
        self.history = {}
        self.metric_choices = {}
        self.metric_options = {}
        self.refresh_job = None
        self._style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.refresh_job = self.after(250, self.refresh)

    def _style(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TFrame", background=COLORS["canvas"])
        style.configure("Card.TFrame", background=COLORS["surface"])
        style.configure("TLabel", background=COLORS["canvas"], foreground=COLORS["body"], font=("Sans", 10))
        style.configure("Card.TLabel", background=COLORS["surface"], foreground=COLORS["body"], font=("Sans", 10))
        style.configure("Title.TLabel", font=("Sans", 22, "bold"), foreground=COLORS["ink"])
        style.configure("Metric.TLabel", background=COLORS["surface"], foreground=COLORS["cpu"], font=("Sans", 22, "bold"))
        style.configure("Muted.TLabel", foreground=COLORS["muted"], font=("Sans", 9))
        style.configure("TButton", font=("Sans", 9), padding=5,
                        background=COLORS["card"], foreground=COLORS["ink"])
        style.map("TButton", background=[("active", COLORS["strong"])])
        style.configure("TCombobox", padding=3)

    def _build(self):
        outer = ttk.Frame(self, padding=14)
        outer.pack(fill="both", expand=True)
        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 10))
        title_box = ttk.Frame(header)
        title_box.pack(side="left", fill="x", expand=True)
        ttk.Label(title_box, text="SysMon", style="Title.TLabel").pack(anchor="w")
        ttk.Label(title_box, text="ThinkPad T430 · Linux", style="Muted.TLabel").pack(anchor="w")
        ttk.Button(header, text="⋮", width=3, command=self._toggle_details).pack(side="right", anchor="n")

        cpu = ttk.Frame(outer, style="Card.TFrame", padding=14)
        cpu.pack(fill="x", pady=(0, 9))
        cpu_head = ttk.Frame(cpu, style="Card.TFrame")
        cpu_head.pack(fill="x")
        ttk.Label(cpu_head, text="◉", background=COLORS["cpu_soft"], foreground=COLORS["cpu"],
                  font=("Sans", 18, "bold"), padding=(9, 4)).pack(side="left", padx=(0, 10))
        ttk.Label(cpu_head, text="CPU", style="Card.TLabel", font=("Sans", 15, "bold")).pack(side="left")
        self.usage_value = ttk.Label(cpu_head, text="—", style="Card.TLabel", foreground=COLORS["ink"],
                                     font=("Sans", 17, "bold"))
        self.usage_value.pack(side="right")
        self.temp_value = ttk.Label(cpu, text="— °C", style="Metric.TLabel")
        self.temp_value.pack(anchor="w", pady=(8, 0))
        self.temp_detail = ttk.Label(cpu, text="Temperatura principal", style="Muted.TLabel", wraplength=290)
        self.temp_detail.pack(anchor="w")
        self.frequency_value = ttk.Label(cpu, text="Frequência —", style="Card.TLabel",
                                         foreground=COLORS["ink"], font=("Sans", 12, "bold"))
        self.frequency_value.pack(anchor="w", pady=(6, 0))

        history_box = ttk.Frame(outer, style="Card.TFrame", padding=10)
        history_box.pack(fill="x", pady=(0, 9))
        history_header = ttk.Frame(history_box, style="Card.TFrame")
        history_header.pack(fill="x")
        ttk.Label(history_header, text="HISTÓRICO · 4 MIN", style="Card.TLabel",
                  font=("Sans", 10, "bold")).pack(side="left")
        self.history_choice = ttk.Combobox(history_header, state="readonly", width=15)
        self.history_choice.pack(side="right")
        self.history_choice.bind("<<ComboboxSelected>>", lambda _e: self._selection_changed())
        self.canvas = tk.Canvas(history_box, height=76, bg=COLORS["surface"], highlightthickness=0)
        self.canvas.pack(fill="x", expand=True, pady=(6, 0))
        self.canvas.bind("<Configure>", lambda _e: self.draw_graph())

        memory = ttk.Frame(outer, style="Card.TFrame", padding=12)
        memory.pack(fill="x", pady=(0, 9))
        ttk.Label(memory, text="▥  MEMÓRIA RAM", style="Card.TLabel",
                  font=("Sans", 10, "bold")).pack(anchor="w")
        self.memory_value = ttk.Label(memory, text="—", style="Card.TLabel",
                                      foreground=COLORS["ram"], font=("Sans", 19, "bold"))
        self.memory_value.pack(anchor="w", pady=(5, 0))
        self.memory_detail = ttk.Label(memory, text="Usada / total", style="Muted.TLabel")
        self.memory_detail.pack(anchor="w")

        fan = ttk.Frame(outer, style="Card.TFrame", padding=12)
        fan.pack(fill="x", pady=(0, 9))
        fan_head = ttk.Frame(fan, style="Card.TFrame")
        fan_head.pack(fill="x")
        ttk.Label(fan_head, text="✣  VENTOINHA", style="Card.TLabel",
                  font=("Sans", 10, "bold")).pack(side="left")
        self.fan_value = ttk.Label(fan_head, text="— RPM", style="Card.TLabel",
                                   foreground=COLORS["network"], font=("Sans", 14, "bold"))
        self.fan_value.pack(side="right")
        self.fan_detail = ttk.Label(fan, text="Modo desconhecido", style="Muted.TLabel")
        self.fan_detail.pack(anchor="w", pady=(4, 7))
        controls = ttk.Frame(fan, style="Card.TFrame")
        controls.pack(fill="x")
        self.mode = ttk.Combobox(controls, state="readonly", width=11,
                                 values=("Automático", "Nível 1", "Nível 2", "Nível 3",
                                         "Nível 4", "Nível 5", "Nível 6", "Nível 7"))
        self.mode.current(0)
        self.mode.pack(side="left", fill="x", expand=True, padx=(0, 5))
        ttk.Button(controls, text="Aplicar", command=self.set_fan).pack(side="left")
        self.secondary = ttk.Frame(outer)
        self.secondary.pack(fill="x")
        self.secondary.pack_forget()
        self.battery_value, self.battery_detail = self._small_card(self.secondary, "BATERIA")
        self.sensor_detail = ttk.Label(self.secondary, text="Sensores adicionais indisponíveis",
                                       style="Muted.TLabel", wraplength=300)
        self.sensor_detail.pack(fill="x", padx=2, pady=(6, 0))
        self.notice = ttk.Label(outer, text="", style="Muted.TLabel", wraplength=300)
        self.notice.pack(anchor="w", pady=(7, 0))

    def _small_card(self, parent, title):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=10)
        frame.pack(fill="x", pady=(0, 7))
        ttk.Label(frame, text=title, style="Card.TLabel").pack(anchor="w")
        value = ttk.Label(frame, text="—", style="Card.TLabel", foreground=COLORS["ink"],
                          font=("Sans", 13, "bold"))
        value.pack(anchor="w", pady=(3, 0))
        detail = ttk.Label(frame, text="", style="Muted.TLabel", wraplength=280)
        detail.pack(anchor="w")
        return value, detail

    def _card(self, parent, title):
        frame = ttk.Frame(parent, style="Card.TFrame", padding=8)
        frame.pack(side="left", fill="both", expand=True, padx=2)
        ttk.Label(frame, text=title, style="Card.TLabel", wraplength=170).pack(anchor="w")
        value = ttk.Label(frame, text="Indisponível", style="Metric.TLabel")
        value.pack(anchor="w", pady=(3, 0))
        detail = ttk.Label(frame, text="", style="Muted.TLabel", wraplength=190)
        detail.pack(anchor="w")
        return value, detail

    def _toggle_details(self):
        if self.expanded.get():
            self.secondary.pack_forget()
            self.expanded.set(False)
        else:
            self.secondary.pack(fill="x")
            self.expanded.set(True)

    def _metric_catalog(self, snapshot):
        catalog = {}
        for name, metric in snapshot.temperatures.items():
            if metric.status is MetricStatus.AVAILABLE:
                catalog[f"Temperatura • {name}"] = (metric, (0, 125), COLORS["sensor"])
        for label, metric, limits, color in (
            ("Uso da CPU", snapshot.cpu_usage, (0, 100), COLORS["cpu"]),
            ("Frequência da CPU", snapshot.cpu_frequency, None, COLORS["storage"]),
        ):
            if metric.status is MetricStatus.AVAILABLE:
                catalog[label] = (metric, limits, color)
        if snapshot.fan_speed.status is MetricStatus.AVAILABLE:
            catalog["Ventoinha • RPM"] = (snapshot.fan_speed, (0, 12000), COLORS["network"])
        return catalog

    def _refresh_history_options(self, catalog):
        previous = self.history_choice.get()
        options = list(catalog)
        self.metric_options = catalog
        self.history_choice.configure(values=options)
        if previous in options:
            self.history_choice.set(previous)
        elif options:
            self.history_choice.current(0)
        else:
            self.history_choice.set("")
        valid = set(options)
        self.history = {key: points for key, points in self.history.items() if key in valid}
        for key in options:
            self.history.setdefault(key, deque(maxlen=HISTORY_SIZE))

    def _selection_changed(self):
        self.draw_graph()

    def refresh(self):
        self.refresh_job = None
        try:
            snapshot = collect_metrics()
            catalog = self._metric_catalog(snapshot)
            self._refresh_history_options(catalog)
            for key, (metric, _limits, _color) in catalog.items():
                self.history[key].append(metric.value)
            self._show_primary(snapshot)
            self._show_secondary(snapshot)
            self.draw_graph()
            if self.closing_after_auto:
                if self.fan_mode_observed == "automático":
                    self.destroy()
                    return
                self.close_auto_checks += 1
                if self.fan_mode_observed == "desconhecido" or self.close_auto_checks >= 5:
                    self.closing_after_auto = False
                    messagebox.showwarning("Modo automático não confirmado",
                                           "A solicitação foi enviada, mas a leitura ACPI não confirmou o modo automático após algumas verificações. A janela permanecerá aberta.")
        except Exception as exc:
            # Keep the UI loop alive even if an unexpected presentation error occurs.
            self.notice.configure(text=f"Atualização parcial; erro ao apresentar dados: {exc}")
        finally:
            if self.winfo_exists():
                self.refresh_job = self.after(REFRESH_MS, self.refresh)

    def _show_primary(self, snapshot):
        available_temps = [(name, metric) for name, metric in snapshot.temperatures.items()
                           if metric.status is MetricStatus.AVAILABLE]
        cpu_metric = next((metric for name, metric in available_temps if name == "CPU"), None)
        chosen = cpu_metric or (max((metric for _, metric in available_temps),
                                    key=lambda item: item.value) if available_temps else None)
        if chosen is not None:
            value = chosen.value
            tone = COLORS["ink"] if value < 80 else (COLORS["warning"] if value < 90 else COLORS["error"])
            self.temp_value.configure(text=f"{value:.0f} °C", foreground=tone)
            self.temp_detail.configure(text=f"{chosen.label or chosen.sensor_name} • {chosen.source}")
        else:
            self.temp_value.configure(text="— °C", foreground=COLORS["muted"])
            invalid = any(m.status is MetricStatus.INVALID for m in snapshot.temperatures.values())
            self.temp_detail.configure(text="Leitura inválida" if invalid else "Sem sensor disponível")

        usage = snapshot.cpu_usage
        self.usage_value.configure(text=f"{usage.value:.0f}%" if usage.status is MetricStatus.AVAILABLE
                                    else "—")

        frequency = snapshot.cpu_frequency
        self.frequency_value.configure(text=f"Frequência  {frequency.value:.0f} MHz"
                                        if frequency.status is MetricStatus.AVAILABLE else "Frequência  —")

        speed = snapshot.fan_speed
        self.fan_value.configure(text=f"{speed.value} RPM" if speed.status is MetricStatus.AVAILABLE else "— RPM")
        mode = snapshot.fan_mode.value if snapshot.fan_mode.status is MetricStatus.AVAILABLE else "desconhecido"
        level = snapshot.fan_level.value if snapshot.fan_level.status is MetricStatus.AVAILABLE else "indisponível"
        status = snapshot.fan_status.value if snapshot.fan_status.status is MetricStatus.AVAILABLE else "indisponível"
        self.fan_detail.configure(text=f"Modo {mode} • nível {level} • estado {status}")
        self.fan_mode_observed = (mode if snapshot.fan_mode.status is MetricStatus.AVAILABLE
                                  else "desconhecido")

    def _show_secondary(self, snapshot):
        used, available = snapshot.memory_used, snapshot.memory_available
        if used.status is MetricStatus.AVAILABLE and available.status is MetricStatus.AVAILABLE:
            total = used.value + available.value
            pct = 100 * used.value / total if total else 0
            self.memory_value.configure(text=f"{pct:.0f}%")
            self.memory_detail.configure(text=f"{used.value:.0f} / {total:.0f} MiB em uso")
        else:
            self.memory_value.configure(text="—")
            self.memory_detail.configure(text="/proc/meminfo indisponível")

        rows = []
        for name, metrics in snapshot.batteries.items():
            charge, state, remaining = metrics["charge"], metrics["state"], metrics["time"]
            if charge.status is not MetricStatus.AVAILABLE and state.status is not MetricStatus.AVAILABLE:
                continue
            pieces = [name]
            pieces.append(f"{charge.value:.0f}%" if charge.status is MetricStatus.AVAILABLE
                          else "carga indisponível")
            if state.status is MetricStatus.AVAILABLE:
                pieces.append(str(state.value))
            if remaining.status is MetricStatus.AVAILABLE:
                pieces.append(f"~{remaining.value:.0f} min")
            rows.append(" • ".join(pieces))
        if rows:
            self.battery_value.configure(text="; ".join(rows))
            self.battery_detail.configure(text="/sys/class/power_supply")
        else:
            self.battery_value.configure(text="—")
            self.battery_detail.configure(text="Nenhuma bateria ou dados disponíveis")

        extras = []
        for name, metric in snapshot.temperatures.items():
            if name != "CPU":
                value = f"{metric.value:.0f} {metric.unit}" if metric.status is MetricStatus.AVAILABLE else "indisponível"
                extras.append(f"{name}: {value}")
        self.sensor_detail.configure(text="Sensores: " + (" • ".join(extras) if extras else "nenhum adicional disponível"))

    def draw_graph(self):
        canvas = self.canvas
        canvas.delete("all")
        width, height = max(canvas.winfo_width(), 40), max(canvas.winfo_height(), 40)
        name = self.history_choice.get()
        selected = self.metric_options.get(name)
        if selected is None:
            canvas.create_text(width / 2, height / 2, text="Nenhuma métrica disponível",
                               fill=COLORS["muted"])
            return
        metric, limits, color = selected
        points = list(self.history.get(name, ()))
        if not points:
            canvas.create_text(width / 2, height / 2, text="Coletando amostras…", fill=COLORS["muted"])
            return
        low, high = limits if limits else (min(points), max(points))
        if high <= low:
            margin = max(abs(high) * 0.05, 1.0)
            low, high = low - margin, high + margin
        left, right, top, bottom = 4, width - 4, 6, height - 7
        for fraction in (0, 1):
            value = high - fraction * (high - low)
            y = top + fraction * (bottom - top)
            canvas.create_line(left, y, right, y, fill=COLORS["line"], dash=(2, 5))
        if len(points) < 2:
            canvas.create_text(width / 2, (top + bottom) / 2, text="Coletando amostras…",
                               fill=COLORS["muted"])
            return
        coords = []
        span = max(right - left, 1)
        for index, value in enumerate(points):
            x = left + index * span / (HISTORY_SIZE - 1)
            y = bottom - (value - low) / (high - low) * (bottom - top)
            coords.extend((x, y))
        canvas.create_line(*coords, fill=color, width=2, smooth=True, splinesteps=12)

    def apply_level(self, level):
        if not os.path.exists(HELPER):
            messagebox.showwarning("Controle da ventoinha indisponível",
                                   "O helper restrito não está instalado. O monitoramento continua funcionando.")
            return False
        try:
            result = subprocess.run(["pkexec", HELPER, str(level)], text=True, capture_output=True, timeout=30)
        except FileNotFoundError:
            messagebox.showerror("pkexec indisponível",
                                 "Não foi possível iniciar a autenticação do sistema (pkexec não foi encontrado).")
            return False
        except subprocess.TimeoutExpired:
            messagebox.showerror("Autenticação expirou",
                                 "A solicitação demorou demais. Nenhuma confirmação de alteração foi recebida.")
            return False
        except OSError as exc:
            messagebox.showerror("Não foi possível iniciar o controle", str(exc))
            return False
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()
            if result.returncode == 126 or "cancel" in detail.lower() or "dismiss" in detail.lower():
                message = "A autenticação foi cancelada. A ventoinha não foi alterada por este comando."
            elif detail:
                message = f"O helper não aplicou o comando. {detail}"
            else:
                message = "O comando não foi aplicado. A autenticação pode ter sido cancelada ou o helper recusou a operação."
            messagebox.showerror("Comando da ventoinha não aplicado", message)
            return False
        self.notice.configure(text="Comando aceito; aguardando confirmação da leitura ACPI." if level == "auto"
                              else f"Nível {level} solicitado; aguardando confirmação da leitura ACPI.")
        if self.refresh_job is None and self.winfo_exists():
            self.refresh_job = self.after(100, self.refresh)
        return True

    def set_fan(self):
        selected = self.mode.get()
        level = "auto" if selected == "Automático" else selected.split()[-1]
        if level != "auto" and not messagebox.askyesno(
                "Usar nível manual?", "A rotação fixa substitui a curva automática do firmware. Observe a temperatura e selecione Automático ao terminar. Continuar?"):
            return
        self.apply_level(level)

    def set_auto(self):
        self.mode.current(0)
        self.apply_level("auto")

    def close(self):
        if self.refresh_job is not None:
            self.after_cancel(self.refresh_job)
            self.refresh_job = None
        if self.fan_mode_observed == "manual":
            if messagebox.askyesno("Restaurar controle automático?",
                                   "A leitura ACPI indica modo manual. Deseja solicitar retorno ao modo automático antes de fechar?"):
                if not self.apply_level("auto"):
                    return
                self.closing_after_auto = True
                self.close_auto_checks = 0
                return
        elif self.fan_mode_observed == "desconhecido":
            messagebox.showinfo("Estado da ventoinha desconhecido",
                                "Não foi possível confirmar o modo atual pela leitura ACPI; o aplicativo não pode afirmar que a ventoinha está em automático.")
        self.destroy()


if __name__ == "__main__":
    import sys
    if "--set-fan" in sys.argv:
        print("Este é o aplicativo visual; o helper privilegiado é instalado separadamente.")
    else:
        Monitor().mainloop()
