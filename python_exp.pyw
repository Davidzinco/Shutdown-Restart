# shutdown_gui.py
# Windows-only Shutdown / Restart / Abort GUI
#
#  • Fixed race-conditions with a threading.Event
#  • Added progress bar + human-readable countdown
#  • Dark theme & emoji icons (no external images)
#  • Sound beep on completion / cancellation
#  • Menu bar with “About”
#
#  Tested on Python 3.8+

import os
import time
import threading
import tkinter as tk
from tkinter import ttk, messagebox

# ----------------------------------------------------------
# Globals
# ----------------------------------------------------------
COUNTDOWN_EVT = threading.Event()   # True = please stop
CURRENT_THREAD = None               # we only store for info

# ----------------------------------------------------------
# Low-level helpers
# ----------------------------------------------------------
def _beep():
    # Simple console beep (works on Windows)
    import winsound
    winsound.Beep(750, 300)

def _graceful_close_apps():
    """
    Enumerates all visible windows and sends a WM_CLOSE message to each,
    excluding system windows and the application itself.
    """
    import ctypes
    user32 = ctypes.windll.user32
    WM_CLOSE = 0x0010
    
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_int, ctypes.c_int)
    
    my_hwnd = None
    try:
        my_hwnd = root.winfo_id()
    except Exception:
        pass

    # List of common system-level/shell window titles to ignore
    ignored_titles = {
        "Program Manager", "Start", "Windows Input Experience", 
        "MessageCenterUI", "Settings", "Search", "Cortana"
    }

    def callback(hwnd, lParam):
        if my_hwnd and hwnd == my_hwnd:
            return True
            
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buffer = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buffer, length + 1)
                title = buffer.value
                
                # Check if this title should be ignored or if it's our app
                if title in ignored_titles or "Shutdown / Restart GUI" in title:
                    return True
                    
                # Post the close message gracefully
                user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)
        return True

    user32.EnumWindows(EnumWindowsProc(callback), 0)

# ----------------------------------------------------------
# System commands
# ----------------------------------------------------------
def _shutdown(delay_sec: int):
    os.system(f"shutdown /s /t {delay_sec}")

def _restart(delay_sec: int):
    os.system(f"shutdown /r /t {delay_sec}")

def _abort():
    os.system("shutdown /a")

# ----------------------------------------------------------
# Countdown engine
# ----------------------------------------------------------
def start_countdown(seconds: int, action: str):
    """
    seconds : total time in seconds
    action  : 'shutdown' | 'restart'
    """
    global CURRENT_THREAD
    COUNTDOWN_EVT.clear()
    CURRENT_THREAD = threading.current_thread()

    for remaining in range(seconds, -1, -1):
        if COUNTDOWN_EVT.is_set():                # cancelled?
            _abort()
            _beep()
            update_log("🛑 Action cancelled by user.")
            return

        mins, secs = divmod(remaining, 60)
        progress_var.set((seconds - remaining) / seconds * 100)
        time_label.config(text=f"{mins:02d}:{secs:02d}")
        root.update_idletasks()
        time.sleep(1)

    progress_var.set(100)
    update_log("🧹 Closing active applications gracefully...")
    root.update_idletasks()
    
    _graceful_close_apps()
    
    # Wait 3 seconds to let apps close/save
    for i in range(3, 0, -1):
        update_log(f"⏳ Waiting {i} second(s) for apps to close...")
        root.update_idletasks()
        time.sleep(1)
        
    update_log("✅ Performing system action…")
    root.update_idletasks()
    
    if action == "shutdown":
        _shutdown(1)     # give OS 1 extra second
    elif action == "restart":
        _restart(1)

# ----------------------------------------------------------
# GUI callbacks
# ----------------------------------------------------------
def on_shutdown():
    delay = delay_var.get()
    update_log(f"🖥️  Shutdown scheduled in {delay} minute(s).")
    threading.Thread(
        target=start_countdown,
        args=(delay * 60, "shutdown"),
        daemon=True
    ).start()

def on_restart():
    delay = delay_var.get()
    update_log(f"🔄 Restart scheduled in {delay} minute(s).")
    threading.Thread(
        target=start_countdown,
        args=(delay * 60, "restart"),
        daemon=True
    ).start()

def on_cancel():
    COUNTDOWN_EVT.set()
    update_log("⏹️  Cancellation requested…")
    _abort()

def update_log(msg):
    log_text.configure(state="normal")
    log_text.insert(tk.END, f"{time.strftime('%H:%M:%S')}  {msg}\n")
    log_text.configure(state="disabled")
    log_text.see(tk.END)

def show_about():
    messagebox.showinfo(
        "About",
        "Shutdown / Restart GUI\n"
        "Created by David."
    )

# ----------------------------------------------------------
# GUI setup
# ----------------------------------------------------------
root = tk.Tk()
root.title("Shutdown / Restart GUI")
root.geometry("420x360")
root.resizable(False, False)

# Dark theme colors
COL_BG   = "#2e2e2e"
COL_FG   = "#ffffff"
COL_BTN  = "#3c3c3c"
COL_ACT  = "#0078d4"

s = ttk.Style()
s.theme_use("clam")
s.configure("TFrame",           background=COL_BG)
s.configure("TLabel",           background=COL_BG, foreground=COL_FG)
s.configure("TButton",          background=COL_BTN, foreground=COL_FG,
            borderwidth=1, focuscolor=COL_ACT)
s.configure("Horizontal.TProgressbar",
            background=COL_ACT, troughcolor=COL_BTN,
            borderwidth=0, lightcolor=COL_ACT)

root.configure(bg=COL_BG)

# ----------------------------------------------------------
# Menu bar
# ----------------------------------------------------------
menubar = tk.Menu(root, bg=COL_BTN, fg=COL_FG, activebackground=COL_ACT)
help_menu = tk.Menu(menubar, tearoff=0, bg=COL_BTN, fg=COL_FG)
help_menu.add_command(label="About", command=show_about)
menubar.add_cascade(label="Help", menu=help_menu)
root.config(menu=menubar)

# ----------------------------------------------------------
# Widgets
# ----------------------------------------------------------
mainframe = ttk.Frame(root, padding=15)
mainframe.pack(fill="both", expand=True)

# Delay spinbox
delay_var = tk.IntVar(value=1)
delay_spin = ttk.Spinbox(mainframe, from_=1, to=120, textvariable=delay_var,
                         width=4, font=("Segoe UI", 12))
delay_spin.grid(row=0, column=1, pady=5, sticky="w")
ttk.Label(mainframe, text="Delay (minutes):", font=("Segoe UI", 12)).grid(
    row=0, column=0, sticky="e", padx=(0, 10))

# Buttons
btn_frame = ttk.Frame(mainframe)
btn_frame.grid(row=1, column=0, columnspan=2, pady=10)
ttk.Button(btn_frame, text="🖥️  Shutdown", command=on_shutdown, width=12).pack(side="left", padx=5)
ttk.Button(btn_frame, text="🔄 Restart",   command=on_restart,  width=12).pack(side="left", padx=5)
ttk.Button(btn_frame, text="⏹️  Cancel",    command=on_cancel,   width=12).pack(side="left", padx=5)

# Progress bar
progress_var = tk.DoubleVar()
progress = ttk.Progressbar(mainframe, variable=progress_var, maximum=100)
progress.grid(row=2, column=0, columnspan=2, sticky="ew", pady=10)

# Time left label
time_label = ttk.Label(mainframe, text="00:00", font=("Segoe UI", 18, "bold"))
time_label.grid(row=3, column=0, columnspan=2)

# Log text
log_text = tk.Text(mainframe, height=8, width=50, state="disabled",
                   bg="#1e1e1e", fg=COL_FG, insertbackground=COL_FG,
                   font=("Consolas", 9))
log_text.grid(row=4, column=0, columnspan=2, pady=(10, 0))

update_log("Ready – choose an action above!")

# ----------------------------------------------------------
# Run
# ----------------------------------------------------------
root.mainloop()