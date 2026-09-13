"""Shutdown / Restart GUI for Windows and systemd Linux."""
import argparse
from datetime import datetime, timedelta
import platform
import queue
import threading
import time
try:
    import tkinter as tk
    from tkinter import messagebox, ttk
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
        root.title("Shutdown / Restart" + (" — SIMULATION" if dry_run else ""))
        root.minsize(520, 440)
        root.configure(bg="#242424")
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure("TFrame", background="#242424")
        style.configure("TLabel", background="#242424", foreground="white")
        frame = ttk.Frame(root, padding=20)
        frame.pack(fill="both", expand=True)
        frame.columnconfigure(1, weight=1)
        frame.rowconfigure(6, weight=1)
        schedule = ttk.Frame(frame)
        schedule.grid(row=0, column=0, columnspan=2, sticky="ew")
        self.mode = tk.StringVar(value="Delay")
        self.mode_box = ttk.Combobox(schedule, textvariable=self.mode, values=("Delay", "At time"), state="readonly", width=10)
        self.mode_box.grid(row=0, column=0, padx=5)
        ttk.Label(schedule, text="Minutes:").grid(row=0, column=1)
        self.delay = tk.StringVar(value="1")
        self.spin = ttk.Spinbox(schedule, from_=1, to=120, textvariable=self.delay, width=5)
        self.spin.grid(row=0, column=2, padx=5)
        ttk.Label(schedule, text="HH:MM:").grid(row=0, column=3)
        self.at_time = tk.StringVar(value=(datetime.now() + timedelta(hours=1)).strftime("%H:%M"))
        self.time_entry = ttk.Entry(schedule, textvariable=self.at_time, width=7)
        self.time_entry.grid(row=0, column=4, padx=5)
        presets = ttk.Frame(schedule)
        presets.grid(row=1, column=0, columnspan=5, pady=(10, 0))
        self.preset_buttons = []
        for minutes in (5, 15, 30, 60):
            button = ttk.Button(presets, text="{} min".format(minutes), command=lambda m=minutes: self.preset(m))
            button.pack(side="left", padx=3)
            self.preset_buttons.append(button)
        self.close_apps = tk.BooleanVar(value=False)
        self.close_check = ttk.Checkbutton(frame, variable=self.close_apps,
                                          text="Request apps to close first (Windows only)")
        self.close_check.grid(row=1, column=0, columnspan=2, pady=12, sticky="w")
        if platform.system() != "Windows":
            self.close_check.state(["disabled"])
        buttons = ttk.Frame(frame)
        buttons.grid(row=2, column=0, columnspan=2, pady=10)
        self.shutdown_button = ttk.Button(buttons, text="Shutdown", command=lambda: self.start("shutdown"))
        self.restart_button = ttk.Button(buttons, text="Restart", command=lambda: self.start("restart"))
        self.cancel_button = ttk.Button(buttons, text="Cancel", command=self.cancel, state="disabled")
        for button in (self.shutdown_button, self.restart_button, self.cancel_button):
            button.pack(side="left", padx=5)
        self.progress = tk.DoubleVar(value=0)
        ttk.Progressbar(frame, variable=self.progress, maximum=100).grid(
            row=3, column=0, columnspan=2, sticky="ew", pady=10)
        self.time_label = ttk.Label(frame, text="00:00", font=("sans", 24))
        self.time_label.grid(row=4, column=0, columnspan=2)
        self.target = ttk.Label(frame, text="Ready")
        self.target.grid(row=5, column=0, columnspan=2, pady=10)
        self.log_text = tk.Text(frame, height=9, width=60, state="disabled", wrap="word",
                                bg="#171717", fg="white")
        self.log_text.grid(row=6, column=0, columnspan=2, sticky="nsew")
        self.log("Simulation: no apps will close and no power command will run." if dry_run
                 else "Ready. Save your work before scheduling a power action.")

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
        mins, secs = divmod(remaining, 60)
        self.time_label.configure(text="{:02d}:{:02d}".format(mins, secs))
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
