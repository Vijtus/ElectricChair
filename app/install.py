from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"
MIN_VERSION = (3, 10)


def venv_python() -> Path:
    if os.name == "nt":
        return VENV / "Scripts" / "python.exe"
    return VENV / "bin" / "python"


def run(command: list[str]) -> None:
    subprocess.run(command, cwd=ROOT, check=True)


def check_python() -> None:
    if sys.version_info < MIN_VERSION:
        version = ".".join(str(part) for part in MIN_VERSION)
        raise SystemExit(f"Python {version}+ is required. Current: {sys.version}")


def ensure_venv() -> Path:
    python = venv_python()
    if python.exists():
        return python
    print("Creating .venv...")
    run([sys.executable, "-m", "venv", str(VENV)])
    if not python.exists():
        raise SystemExit("Could not create .venv. Install Python with venv support.")
    return python


def install_requirements(python: Path) -> None:
    if not REQUIREMENTS.exists():
        raise SystemExit("requirements.txt is missing.")
    print("Installing required packages...")
    run([str(python), "-m", "pip", "install", "--upgrade", "pip"])
    run([str(python), "-m", "pip", "install", "-r", str(REQUIREMENTS)])


def verify_launchers() -> list[str]:
    missing = []
    for name in (
        "Start_NCNI_Massage_Chair.bat",
        "Start_NCNI_Massage_Chair.command",
        "start_ncni_massage_chair.sh",
    ):
        if not (ROOT / name).exists():
            missing.append(name)
    return missing


def run_verification(python: Path) -> None:
    verifier = ROOT / "tools" / "verify_installation.py"
    if verifier.exists():
        run([str(python), str(verifier), "--dry-run"])


def main() -> None:
    check_python()
    python = ensure_venv()
    install_requirements(python)
    missing = verify_launchers()
    if missing:
        print("Warning: missing launcher files: " + ", ".join(missing))
    run_verification(python)
    print()
    print("Installation finished.")
    print("Start the panel with one of these:")
    print("  Windows: Start_NCNI_Massage_Chair.bat")
    print("  macOS:   Start_NCNI_Massage_Chair.command")
    print("  Linux:   ./start_ncni_massage_chair.sh")
    print("  Manual:  python3 app.py")


if __name__ == "__main__":
    main()
