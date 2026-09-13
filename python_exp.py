"""Shutdown / Restart GUI for Windows and systemd Linux."""
import argparse
from datetime import datetime, timedelta
import platform
import queue
import threading
import time
try:
    import tkinter as tk
    from tkinter import font as tkfont, messagebox, ttk
except ImportError:
    tk = None

from power_control import Countdown, close_windows_apps, execute_power, power_command, scheduled_delay, validate_minutes


class PowerApp:
    def __init__(self, root, dry_run=False):
        self.root = root
        self.dry_run = dry_run
        self.timer = Countdown()
        self.job = None
        self.executing = False
        self.closing_phase = False
        self.results = queue.Queue()
        self.command = None
        root.title("Power Timer" + (" — Simulation" if dry_run else ""))
        root.configure(bg="#181817")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        families = set(tkfont.families(root))
        font = next((name for name in ("Segoe UI", "Adwaita Sans", "DejaVu Sans") if name in families), "TkDefaultFont")
        timer_font = next((name for name in ("Cascadia Mono", "Adwaita Mono", "Consolas", "DejaVu Sans Mono") if name in families), "TkFixedFont")
        style = ttk.Style(root)
        style.theme_use("clam")
        bg, card, fg, muted, accent = "#181817", "#222220", "#eeeae3", "#aaa69e", "#a7443e"
        style.configure("TFrame", background=bg)
        style.configure("Card.TFrame", background=card)
        style.configure("TLabel", background=bg, foreground=fg, font=(font, 10))
        style.configure("Muted.TLabel", foreground=muted)
        style.configure("Card.TLabel", background=card, foreground=muted)
        style.configure("Timer.TLabel", background=card, foreground=fg, font=(timer_font, 46))
        style.configure("TButton", background="#30302d", foreground=fg, font=(font, 10), padding=(14, 10), borderwidth=0)
        style.map("TButton", background=[("disabled", "#242422"), ("pressed", "#45443f"), ("active", "#3d3c37")],
                  foreground=[("disabled", "#858178")])
        style.configure("Accent.TButton", background=accent, foreground="#fff4ed", font=(font, 10, "bold"))
        style.map("Accent.TButton", background=[("disabled", "#442c29"), ("pressed", "#8e3833"), ("active", "#b85149")],
                  foreground=[("disabled", "#b0938b")])
        style.configure("Quiet.TButton", background=bg, foreground=muted, padding=(8, 6))
        style.configure("TEntry", fieldbackground=card, foreground=fg, insertcolor=fg, padding=8)
        style.configure("TSpinbox", fieldbackground=card, foreground=fg, arrowcolor=muted, padding=8)
        style.configure("TCombobox", fieldbackground=card, background="#30302d", foreground=fg, arrowcolor=muted, padding=8)
        style.map("TCombobox", fieldbackground=[("readonly", card)], foreground=[("readonly", fg)])
        style.configure("TCheckbutton", background=bg, foreground=muted, font=(font, 9))
        style.map("TCheckbutton", background=[("active", bg)])
        style.configure("TEntry", bordercolor="#44423c", lightcolor=card, darkcolor=card)
        style.configure("TSpinbox", bordercolor="#44423c", lightcolor=card, darkcolor=card, background="#30302d")
        style.configure("TCombobox", bordercolor="#44423c", lightcolor=card, darkcolor=card)
        style.map("TEntry", bordercolor=[("focus", "#aaa08f")])
        style.map("TSpinbox", bordercolor=[("focus", "#aaa08f")])
        root.option_add("*TCombobox*Listbox.background", card)
        root.option_add("*TCombobox*Listbox.foreground", fg)
        root.option_add("*TCombobox*Listbox.selectBackground", "#3d3c37")

        frame = ttk.Frame(root, padding=28)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(0, weight=1)
        header = ttk.Frame(frame)
        header.grid(row=0, column=0, sticky="ew", pady=(0, 22))
        ttk.Label(header, text="Power Timer", font=(font, 20, "bold")).pack(anchor="w")
        ttk.Label(header, text="Shutdown & restart, on your schedule.", style="Muted.TLabel").pack(anchor="w", pady=(5, 0))
        if dry_run:
            ttk.Label(header, text="SIMULATION  /  No power actions", foreground=muted).pack(anchor="w", pady=(10, 0))

        timer_card = ttk.Frame(frame, style="Card.TFrame", padding=(20, 22))
        timer_card.grid(row=1, column=0, sticky="ew")
        timer_card.columnconfigure(0, weight=1)
        ttk.Label(timer_card, text="TIME REMAINING", style="Card.TLabel", font=(font, 9)).grid(row=0, column=0)
        self.time_label = ttk.Label(timer_card, text="00:00", style="Timer.TLabel")
        self.time_label.grid(row=1, column=0, pady=(6, 4))
        self.target = ttk.Label(timer_card, text="Choose when to finish", style="Card.TLabel", anchor="center")
        self.target.grid(row=2, column=0, sticky="ew")
        self.progress = tk.DoubleVar(value=0)
        self.timeline = tk.Canvas(timer_card, height=66, width=1, background=card,
                                  highlightthickness=0, borderwidth=0)
        self.timeline.grid(row=3, column=0, sticky="ew", pady=(22, 0))
        self.timeline_font = (font, 9)
        self.inspected_progress = None
        self.timeline.bind("<Configure>", self.draw_timeline)
        self.timeline.bind("<Motion>", self.inspect_timeline)
        self.timeline.bind("<Leave>", self.leave_timeline)
        self.progress.trace_add("write", self.draw_timeline)

        schedule = ttk.Frame(frame)
        schedule.grid(row=2, column=0, sticky="ew", pady=(24, 0))
        schedule.columnconfigure(0, weight=1)
        schedule.columnconfigure(1, weight=1)
        ttk.Label(schedule, text="Schedule", style="Muted.TLabel").grid(row=0, column=0, sticky="w", pady=(0, 8))
        self.input_label = ttk.Label(schedule, text="Minutes", style="Muted.TLabel")
        self.input_label.grid(row=0, column=1, sticky="w", padx=(14, 0), pady=(0, 8))
        self.mode = tk.StringVar(value="Delay")
        self.mode_box = ttk.Combobox(schedule, textvariable=self.mode, values=("Delay", "At time"), state="readonly", width=12)
        self.mode_box.grid(row=1, column=0, sticky="ew")
        self.delay = tk.StringVar(value="1")
        self.spin = ttk.Spinbox(schedule, from_=1, to=120, textvariable=self.delay, width=10, font=(font, 11))
        self.spin.grid(row=1, column=1, sticky="ew", padx=(14, 0))
        self.at_time = tk.StringVar(value=(datetime.now() + timedelta(hours=1)).strftime("%H:%M"))
        self.time_entry = ttk.Entry(schedule, textvariable=self.at_time, width=10, font=(font, 11))
        self.time_entry.grid(row=1, column=1, sticky="ew", padx=(14, 0))
        self.presets = ttk.Frame(schedule)
        self.presets.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(12, 0))
        self.preset_buttons = []
        for column, minutes in enumerate((5, 15, 30, 60)):
            self.presets.columnconfigure(column, weight=1)
            button = ttk.Button(self.presets, text="{} min".format(minutes), command=lambda m=minutes: self.preset(m))
            button.grid(row=0, column=column, sticky="ew", padx=(0 if column == 0 else 6, 0))
            self.preset_buttons.append(button)
        self.mode.trace_add("write", self.update_mode)
        self.update_mode()

        self.close_apps = tk.BooleanVar(value=False)
        self.close_check = ttk.Checkbutton(frame, variable=self.close_apps, text="Request apps to close before finishing")
        if platform.system() == "Windows":
            self.close_check.grid(row=3, column=0, pady=(16, 0), sticky="w")
        else:
            self.close_check.state(["disabled"])
        buttons = ttk.Frame(frame)
        buttons.grid(row=4, column=0, sticky="ew", pady=(24, 0))
        buttons.columnconfigure((0, 1), weight=1)
        self.shutdown_button = ttk.Button(buttons, text="Shut down", style="Accent.TButton", command=lambda: self.start("shutdown"))
        self.restart_button = ttk.Button(buttons, text="Restart", command=lambda: self.start("restart"))
        self.shutdown_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.restart_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))
        self.cancel_button = ttk.Button(buttons, text="Cancel timer", command=self.cancel, state="disabled", style="Quiet.TButton")
        self.cancel_button.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))

        footer = ttk.Frame(frame)
        footer.grid(row=5, column=0, sticky="ew", pady=(12, 0))
        ttk.Label(footer, text="Keep the app open while waiting.", style="Muted.TLabel", font=(font, 9)).pack(side="left")
        self.details_button = ttk.Button(footer, text="Show details", style="Quiet.TButton", command=self.toggle_details)
        self.details_button.pack(side="right")
        self.details = ttk.Frame(frame)
        self.details.grid(row=6, column=0, sticky="nsew", pady=(12, 0))
        self.details.columnconfigure(0, weight=1)
        self.details.rowconfigure(0, weight=1)
        frame.rowconfigure(6, weight=1)
        self.log_text = tk.Text(self.details, height=6, width=44, state="disabled", wrap="word",
                                bg=card, fg=muted, relief="flat", padx=12, pady=10, font=(font, 9))
        self.log_text.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(self.details, command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.details.grid_remove()
        self.log("Simulation: no apps will close and no power command will run." if dry_run
                 else "Ready. Save your work before scheduling a power action.")
        root.update_idletasks()
        root.minsize(root.winfo_reqwidth(), root.winfo_reqheight())

    @staticmethod
    def format_duration(seconds):
        minutes, seconds = divmod(max(0, int(seconds)), 60)
        if minutes >= 60:
            hours, minutes = divmod(minutes, 60)
            return "{:02d}:{:02d}:{:02d}".format(hours, minutes, seconds)
        return "{:02d}:{:02d}".format(minutes, seconds)

    def inspect_timeline(self, event):
        width = max(1, self.timeline.winfo_width() - 12)
        self.inspected_progress = min(100, max(0, (event.x - 6) / width * 100))
        self.draw_timeline()

    def leave_timeline(self, _=None):
        self.inspected_progress = None
        self.draw_timeline()

    def draw_timeline(self, *_):
        canvas = self.timeline
        canvas.delete("all")
        width = max(24, canvas.winfo_width())
        left, right = 6, width - 6
        progress = min(100, max(0, self.progress.get()))
        duration = self.timer.duration
        # A measured scale: filled ticks track elapsed time, a red needle marks now.
        for index in range(61):
            x = left + (right - left) * index / 60
            major = index % 5 == 0
            filled = progress > 0 and index / 60 * 100 <= progress
            canvas.create_line(x, 12 if major else 18, x, 32,
                               fill="#b6ad9d" if filled else "#48463f",
                               width=2, capstyle="round")
        position = left + (right - left) * progress / 100
        canvas.create_polygon(position - 4, 2, position + 4, 2, position, 7,
                              fill="#bd655b", outline="")
        canvas.create_line(position, 11, position, 34, fill="#bd655b", width=2)
        if self.inspected_progress is not None and duration and (self.timer.active or progress):
            fraction = self.inspected_progress / 100
            x = left + (right - left) * fraction
            canvas.create_line(x, 10, x, 35, fill="#e0d9cc", dash=(2, 2))
            caption = "AT {}  /  elapsed".format(self.format_duration(duration * fraction))
        elif duration and (self.timer.active or progress):
            caption = "{}  elapsed".format(self.format_duration(duration * progress / 100))
        else:
            caption = "Waiting to start"
        canvas.create_text(0, 55, text=caption, anchor="w", fill="#aaa69e", font=self.timeline_font)
        canvas.create_text(width, 55, text="{:.0f}%".format(progress), anchor="e",
                           fill="#d0c9bd", font=self.timeline_font)

    def update_mode(self, *_):
        at_time = self.mode.get() == "At time"
        self.input_label.configure(text="Time · 24-hour" if at_time else "Minutes")
        if at_time:
            self.spin.grid_remove()
            self.time_entry.grid()
            self.presets.grid_remove()
        else:
            self.time_entry.grid_remove()
            self.spin.grid()
            self.presets.grid()

    def toggle_details(self):
        if self.details.winfo_manager():
            self.details.grid_remove()
            self.details_button.configure(text="Show details")
        else:
            self.details.grid()
            self.details_button.configure(text="Hide details")

    def log(self, message):
        self.log_text.configure(state="normal")
        self.log_text.insert(tk.END, time.strftime("%H:%M:%S  ") + message + "\n")
        self.log_text.configure(state="disabled")
        self.log_text.see(tk.END)

    def set_busy(self, busy):
        for widget in (self.shutdown_button, self.restart_button, self.spin, self.time_entry, *self.preset_buttons):
            widget.configure(state="disabled" if busy else "normal")
        self.mode_box.configure(state="disabled" if busy else "readonly")
        self.cancel_button.configure(state="normal" if busy and not self.executing else "disabled")
        if platform.system() == "Windows":
            self.close_check.configure(state="disabled" if busy else "normal")

    def preset(self, minutes):
        self.mode.set("Delay")
        self.delay.set(str(minutes))

    def start(self, action):
        if self.timer.active or self.executing:
            return
        try:
            if self.mode.get() == "At time":
                seconds, target = scheduled_delay(self.at_time.get())
            else:
                seconds = validate_minutes(self.delay.get()) * 60
                target = datetime.now() + timedelta(seconds=seconds)
            command = power_command(action)
        except (ValueError, RuntimeError) as exc:
            messagebox.showerror("Cannot schedule", str(exc), parent=self.root)
            return
        self.command = command
        self.closing_phase = False
        self.timer.start(seconds, action)
        self.set_busy(True)
        self.target.configure(text="{} at {}".format(action.capitalize(), target.strftime("%Y-%m-%d %H:%M:%S")))
        self.log("{} scheduled for {}.".format(action.capitalize(), target.strftime("%Y-%m-%d %H:%M:%S")))
        self.tick()

    def tick(self):
        self.job = None
        if not self.timer.active:
            return
        remaining, progress = self.timer.snapshot()
        self.progress.set(progress)
        self.time_label.configure(text=self.format_duration(remaining))
        action = self.timer.take_due()
        if action is None:
            self.job = self.root.after(100, self.tick)
            return
        if self.close_apps.get() and not self.closing_phase and platform.system() == "Windows":
            try:
                if not self.dry_run:
                    close_windows_apps()
                self.log("Close requests sent; Cancel cannot reopen apps. Power action in 3 seconds."
                         if not self.dry_run else "Simulation: app closure skipped; waiting 3 seconds.")
            except Exception as exc:
                self.log("App closure failed; power action cancelled: " + str(exc))
                self.set_busy(False)
                self.target.configure(text="Cancelled")
                return
            self.closing_phase = True
            self.timer.start(3, action)
            self.job = self.root.after(100, self.tick)
            return
        self.executing = True
        self.set_busy(True)
        self.target.configure(text="Submitting power command…")
        self.log("Submitting command; cancellation is no longer available.")
        threading.Thread(target=self.run_command, daemon=True).start()
        self.job = self.root.after(100, self.poll_result)

    def run_command(self):
        # Only the queue is touched from this worker; all Tk calls stay on the UI thread.
        try:
            self.results.put((True, execute_power(self.command, self.dry_run)))
        except Exception as exc:
            self.results.put((False, str(exc)))

    def poll_result(self):
        self.job = None
        try:
            success, message = self.results.get_nowait()
        except queue.Empty:
            self.job = self.root.after(100, self.poll_result)
            return
        self.executing = False
        self.set_busy(False)
        self.target.configure(text="Simulation complete" if success and self.dry_run else
                              "Command accepted" if success else "Command failed")
        self.log(message)
        self.root.bell()
        if not success:
            messagebox.showerror("Power action failed", message, parent=self.root)

    def cancel(self):
        if self.executing or not self.timer.cancel():
            return
        if self.job is not None:
            self.root.after_cancel(self.job)
            self.job = None
        self.closing_phase = False
        self.progress.set(0)
        self.time_label.configure(text="00:00")
        self.target.configure(text="Cancelled")
        self.set_busy(False)
        self.log("Local countdown cancelled. No power command was submitted.")
        self.root.bell()

    def on_close(self):
        if self.executing:
            messagebox.showinfo("Command in progress", "Wait for the command result before closing.", parent=self.root)
            return
        if self.timer.active:
            if not messagebox.askyesno("Cancel and exit?", "Cancel the scheduled action and close?", parent=self.root):
                return
            self.cancel()
        self.root.destroy()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Simulate without closing apps or changing power state")
    args = parser.parse_args()
    if tk is None:
        parser.error("Tkinter is unavailable. Install Tk (Arch/CachyOS: sudo pacman -S tk; Ubuntu/Debian: sudo apt install python3-tk).")
    if platform.system() not in ("Windows", "Linux"):
        parser.error("Only Windows and Linux are supported.")
    root = tk.Tk()
    PowerApp(root, dry_run=args.dry_run)
    root.mainloop()


if __name__ == "__main__":
    main()
