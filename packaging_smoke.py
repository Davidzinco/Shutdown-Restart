"""Exercise the packaged GUI without ever submitting a system power action."""
import json
from pathlib import Path
import time


def run_smoke_test(root, app, report):
    result = {"ok": False, "checks": []}
    try:
        if not app.dry_run:
            raise RuntimeError("Smoke tests require simulation mode.")
        root.update()
        result["checks"].append("GUI initialized")
        app.preset(5)
        app.start("shutdown")
        if not app.timer.active:
            raise RuntimeError("Countdown did not start.")
        app.cancel()
        if app.timer.active:
            raise RuntimeError("Cancellation failed.")
        result["checks"].append("Countdown cancelled")
        for action in ("shutdown", "restart"):
            app.start(action)
            if not app.timer.active:
                raise RuntimeError("Simulation did not start.")
            app.timer.deadline = app.timer.clock() + 0.15
            deadline = time.monotonic() + 10
            while (app.timer.active or app.executing) and time.monotonic() < deadline:
                root.update()
                time.sleep(0.02)
            if app.timer.active or app.executing or app.target.cget("text") != "Simulation complete":
                raise RuntimeError("Simulation did not complete: " + action)
            result["checks"].append(action + " simulated")
        app.toggle_details()
        root.update()
        if "Dry run:" not in app.log_text.get("1.0", "end"):
            raise RuntimeError("Simulation log missing.")
        result["checks"].append("Activity log rendered")
        result["ok"] = True
    except Exception as exc:
        result["error"] = str(exc)
    finally:
        root.destroy()
        Path(report).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return 0 if result["ok"] else 1
