"""Launch a built package, require a successful JSON report, and enforce a timeout."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

package = Path(sys.argv[1]).resolve()
env = os.environ.copy()
if package.suffix == ".AppImage":
    package.chmod(package.stat().st_mode | 0o111)
    env["APPIMAGE_EXTRACT_AND_RUN"] = "1"
with tempfile.TemporaryDirectory(prefix="power-timer-smoke-") as directory:
    report = Path(directory) / "report.json"
    subprocess.run([str(package), "--smoke-test", str(report)], env=env, check=True, timeout=60)
    data = json.loads(report.read_text(encoding="utf-8"))
    if not data.get("ok"):
        raise RuntimeError(data)
    print(json.dumps(data, indent=2))
