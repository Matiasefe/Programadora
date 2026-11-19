"""Entry point GUI."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    from PyQt5.QtWidgets import QApplication

    from .main_window import MainWindow

    app = QApplication(argv or sys.argv)
    app.setApplicationName("Programadora")
    win = MainWindow()
    win.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
