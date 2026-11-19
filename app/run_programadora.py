#!/usr/bin/env python3
"""Lanzar desde la carpeta app/:  python run_programadora.py"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _check_deps() -> None:
    missing: list[str] = []
    for mod, pip_name in (
        ("PyQt5", "PyQt5"),
        ("serial", "pyserial"),
        ("elftools", "pyelftools"),
        ("intelhex", "intelhex"),
    ):
        try:
            __import__(mod)
        except ImportError:
            missing.append(pip_name)
    if missing:
        req = ROOT.parent / "requirements.txt"
        print("Faltan librerías de Python:", ", ".join(missing))
        print(f"Instalá con:\n  python -m pip install -r \"{req}\"")
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        _check_deps()
        from programadora_app.main import main

        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR al iniciar: {exc}")
        raise SystemExit(1) from exc
