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


class Monitor(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("T430 • Monitor")
        self.geometry("760x660")
        self.minsize(420, 480)
        self.configure(bg="#101820")
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
        style.configure("TFrame", background="#101820")
        style.configure("Card.TFrame", background="#192631")
        style.configure("TLabel", background="#101820", foreground="#e8f0f5", font=("Sans", 10))
        style.configure("Card.TLabel", background="#192631", foreground="#e8f0f5", font=("Sans", 10))
        style.configure("Title.TLabel", font=("Sans", 18, "bold"), foreground="#f4f8fb")
        style.configure("Metric.TLabel", background="#192631", foreground="#56d6c2", font=("Sans", 21, "bold"))
        style.configure("Muted.TLabel", foreground="#9db0bd", font=("Sans", 9))
        style.configure("TButton", font=("Sans", 9), padding=5)
        style.configure("TCombobox", padding=3)

    def _build(self):
        outer = ttk.Frame(self, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="ThinkPad T430", style="Title.TLabel").pack(anchor="w")
        ttk.Label(outer, text="Monitoramento local • atualização a cada 2 s",
                  style="Muted.TLabel").pack(anchor="w", pady=(1, 9))

        primary = ttk.Frame(outer)
        primary.pack(fill="x")
        self.temp_value, self.temp_detail = self._card(primary, "TEMPERATURA PRINCIPAL")
        self.usage_value, self.usage_detail = self._card(primary, "USO TOTAL DA CPU")
        self.frequency_value, self.frequency_detail = self._card(primary, "FREQUÊNCIA ATUAL")

        fan = ttk.Frame(outer, style="Card.TFrame", padding=9)
        fan.pack(fill="x", pady=(7, 0))
        fan_left = ttk.Frame(fan, style="Card.TFrame")
        fan_left.pack(side="left", fill="x", expand=True)
        ttk.Label(fan_left, text="VENTOINHA", style="Card.TLabel").pack(anchor="w")
        self.fan_value = ttk.Label(fan_left, text="Indisponível", style="Metric.TLabel")
        self.fan_value.pack(anchor="w", pady=(2, 0))
        self.fan_detail = ttk.Label(fan_left, text="Modo desconhecido", style="Muted.TLabel")
        self.fan_detail.pack(anchor="w")

        controls = ttk.Frame(fan, style="Card.TFrame")
        controls.pack(side="right", anchor="e")
        self.mode = ttk.Combobox(controls, state="readonly", width=11,
                                 values=("Automático", "Nível 1", "Nível 2", "Nível 3",
                                         "Nível 4", "Nível 5", "Nível 6", "Nível 7"))
        self.mode.current(0)
        self.mode.pack(side="left", padx=(0, 4))
        ttk.Button(controls, text="Aplicar", command=self.set_fan).pack(side="left")
        ttk.Button(controls, text="Auto", command=self.set_auto).pack(side="left", padx=(4, 0))

        history_box = ttk.Frame(outer, style="Card.TFrame", padding=9)
        history_box.pack(fill="both", expand=True, pady=(7, 0))
        history_header = ttk.Frame(history_box, style="Card.TFrame")
        history_header.pack(fill="x")
        ttk.Label(history_header, text="HISTÓRICO CURTO", style="Card.TLabel").pack(side="left")
        self.history_choice = ttk.Combobox(history_header, state="readonly", width=24)
        self.history_choice.pack(side="right")
        self.history_choice.bind("<<ComboboxSelected>>", lambda _e: self._selection_changed())
        self.canvas = tk.Canvas(history_box, height=150, bg="#192631", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, pady=(5, 0))
        self.canvas.bind("<Configure>", lambda _e: self.draw_graph())

        secondary_head = ttk.Frame(outer)
        secondary_head.pack(fill="x", pady=(7, 0))
        self.expand_button = ttk.Button(secondary_head, text="＋ Detalhes (RAM, bateria e sensores)",
                                        command=self._toggle_details)
        self.expand_button.pack(anchor="w")
        self.secondary = ttk.Frame(outer)
        self.secondary.pack(fill="x")
        self.secondary.pack_forget()
        self.memory_value, self.memory_detail = self._card(self.secondary, "MEMÓRIA (USADA / DISPONÍVEL)")
        self.battery_value, self.battery_detail = self._card(self.secondary, "BATERIA")
        self.sensor_detail = ttk.Label(self.secondary, text="Sensores adicionais indisponíveis",
                                       style="Muted.TLabel", wraplength=550)
        self.sensor_detail.pack(fill="x", padx=4, pady=(4, 0))
        self.notice = ttk.Label(outer, text="", style="Muted.TLabel", wraplength=700)
        self.notice.pack(anchor="w", pady=(5, 0))

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
            self.expand_button.configure(text="＋ Detalhes (RAM, bateria e sensores)")
        else:
            self.secondary.pack(fill="x")
            self.expanded.set(True)
            self.expand_button.configure(text="− Ocultar detalhes")

    def _metric_catalog(self, snapshot):
        catalog = {}
        for name, metric in snapshot.temperatures.items():
            if metric.status is MetricStatus.AVAILABLE:
                catalog[f"Temperatura • {name}"] = (metric, (0, 125), "#56d6c2")
        for label, metric, limits, color in (
            ("Uso da CPU", snapshot.cpu_usage, (0, 100), "#72a7ff"),
            ("Frequência da CPU", snapshot.cpu_frequency, None, "#f2b84b"),
        ):
            if metric.status is MetricStatus.AVAILABLE:
                catalog[label] = (metric, limits, color)
        if snapshot.fan_speed.status is MetricStatus.AVAILABLE:
            catalog["Ventoinha • RPM"] = (snapshot.fan_speed, (0, 12000), "#e887c9")
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
            self.temp_value.configure(text=f"{value:.0f} °C",
                                      foreground="#56d6c2" if value < 80 else
                                      ("#f2b84b" if value < 90 else "#ff6868"))
            self.temp_detail.configure(text=f"{chosen.label or chosen.sensor_name} • {chosen.source}")
        else:
            self.temp_value.configure(text="Indisponível")
            invalid = any(m.status is MetricStatus.INVALID for m in snapshot.temperatures.values())
            self.temp_detail.configure(text="Leitura inválida" if invalid else "Sem sensor disponível")

        usage = snapshot.cpu_usage
        self.usage_value.configure(text=f"{usage.value:.0f} %" if usage.status is MetricStatus.AVAILABLE
                                    else "Indisponível")
        self.usage_detail.configure(text=usage.source if usage.status is MetricStatus.AVAILABLE
                                    else "Aguardando amostras" if usage.source == "/proc/stat"
                                    else "Fonte indisponível")

        frequency = snapshot.cpu_frequency
        self.frequency_value.configure(text=f"{frequency.value:.0f} MHz"
                                        if frequency.status is MetricStatus.AVAILABLE else "Indisponível")
        self.frequency_detail.configure(text=frequency.source if frequency.status is MetricStatus.AVAILABLE
                                        else "Fonte cpufreq indisponível")

        speed = snapshot.fan_speed
        self.fan_value.configure(text=f"{speed.value} RPM" if speed.status is MetricStatus.AVAILABLE
                                  else "Indisponível")
        mode = snapshot.fan_mode.value if snapshot.fan_mode.status is MetricStatus.AVAILABLE else "desconhecido"
        level = snapshot.fan_level.value if snapshot.fan_level.status is MetricStatus.AVAILABLE else "indisponível"
        status = snapshot.fan_status.value if snapshot.fan_status.status is MetricStatus.AVAILABLE else "indisponível"
        self.fan_detail.configure(text=f"Modo {mode} • nível {level} • estado {status}")
        self.fan_mode_observed = (mode if snapshot.fan_mode.status is MetricStatus.AVAILABLE
                                  else "desconhecido")

    def _show_secondary(self, snapshot):
        used, available = snapshot.memory_used, snapshot.memory_available
        if used.status is MetricStatus.AVAILABLE and available.status is MetricStatus.AVAILABLE:
            self.memory_value.configure(text=f"{used.value:.0f} / {available.value:.0f} MiB")
            self.memory_detail.configure(text="Usada / disponível • /proc/meminfo")
        else:
            self.memory_value.configure(text="Indisponível")
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
            self.battery_value.configure(text="Indisponível")
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
            canvas.create_text(width / 2, height / 2, text="Nenhuma métrica disponível para o histórico",
                               fill="#9db0bd")
            return
        metric, limits, color = selected
        points = list(self.history.get(name, ()))
        if not points:
            canvas.create_text(width / 2, height / 2, text="Coletando amostras…", fill="#9db0bd")
            return
        low, high = limits if limits else (min(points), max(points))
        if high <= low:
            margin = max(abs(high) * 0.05, 1.0)
            low, high = low - margin, high + margin
        left, right, top, bottom = 42, width - 12, 14, height - 24
        for fraction in (0, .25, .5, .75, 1):
            value = high - fraction * (high - low)
            y = top + fraction * (bottom - top)
            canvas.create_line(left, y, right, y, fill="#30434f")
            canvas.create_text(left - 5, y, text=f"{value:.0f}", anchor="e",
                               fill="#9db0bd", font=("Sans", 8))
        canvas.create_text(right, 6, text=f"{name} ({metric.unit})", anchor="ne",
                           fill="#9db0bd", font=("Sans", 8))
        if len(points) < 2:
            canvas.create_text(width / 2, (top + bottom) / 2, text="Coletando amostras…",
                               fill="#9db0bd")
            return
        coords = []
        span = max(right - left, 1)
        for index, value in enumerate(points):
            x = left + index * span / (HISTORY_SIZE - 1)
            y = bottom - (value - low) / (high - low) * (bottom - top)
            coords.extend((x, y))
        canvas.create_line(*coords, fill=color, width=2, smooth=True)

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
