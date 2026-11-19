"""Ventana principal PyQt5."""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import QObject, QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QProgressBar,
    QVBoxLayout,
    QWidget,
)

from . import flasher
from .gdb_find import find_gdb
from .probe import list_ports, pick_gdb_port


# (Hz, etiqueta GUI). Default = default BMP (~3.3 MHz), estable en Write largo.
SWD_FREQ_CHOICES: list[tuple[int, str]] = [
    (1_000_000, "1 MHz — más estable / más lento"),
    (2_000_000, "2 MHz"),
    (3_272_727, "3.3 MHz — default BMP (recomendado)"),
    (4_000_000, "4 MHz"),
    (6_000_000, "6 MHz — máx. F103 (puede cortar en Riverdi grande)"),
]


class FlashWorker(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(bool)

    def __init__(
        self,
        hex_path: str,
        port: str,
        stldr_path: str | None,
        gdb_path: str | None,
        erase: bool,
        run_after: bool,
        swd_freq_hz: int,
    ):
        super().__init__()
        self.hex_path = hex_path
        self.port = port
        self.stldr_path = stldr_path
        self.gdb_path = gdb_path
        self.erase = erase
        self.run_after = run_after
        self.swd_freq_hz = swd_freq_hz
        self._abort = False

    def request_abort(self) -> None:
        self._abort = True

    def run(self) -> None:
        try:
            if self._abort:
                self.finished.emit(False)
                return
            ok = flasher.flash(
                hex_path=Path(self.hex_path),
                port=self.port,
                stldr_path=Path(self.stldr_path) if self.stldr_path else None,
                gdb_path=self.gdb_path or None,
                erase=self.erase,
                run_after=self.run_after,
                swd_freq_hz=self.swd_freq_hz,
                log=lambda m: self.log.emit(m),
            )
        except Exception as exc:  # noqa: BLE001
            self.log.emit(f"EXCEPTION: {exc}")
            ok = False
        self.finished.emit(ok)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Programadora — Black Magic / Riverdi")
        self.resize(820, 640)
        self._thread: QThread | None = None
        self._worker: FlashWorker | None = None

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        # --- Sonda ---
        probe_box = QGroupBox("Sonda Black Magic")
        pg = QGridLayout(probe_box)
        self.port_combo = QComboBox()
        self.port_combo.setMinimumWidth(280)
        btn_refresh = QPushButton("Detectar")
        btn_refresh.clicked.connect(self.refresh_ports)
        pg.addWidget(QLabel("Puerto GDB:"), 0, 0)
        pg.addWidget(self.port_combo, 0, 1)
        pg.addWidget(btn_refresh, 0, 2)
        self.probe_status = QLabel("—")
        pg.addWidget(self.probe_status, 1, 0, 1, 3)
        layout.addWidget(probe_box)

        # --- Archivos ---
        files_box = QGroupBox("Firmware")
        fg = QGridLayout(files_box)

        self.hex_edit = QLineEdit()
        btn_hex = QPushButton("…")
        btn_hex.clicked.connect(self.browse_hex)
        fg.addWidget(QLabel("Archivo .hex / .elf:"), 0, 0)
        fg.addWidget(self.hex_edit, 0, 1)
        fg.addWidget(btn_hex, 0, 2)

        self.stldr_edit = QLineEdit()
        btn_stldr = QPushButton("…")
        btn_stldr.clicked.connect(self.browse_stldr)
        fg.addWidget(QLabel(".stldr (Riverdi / QSPI):"), 1, 0)
        fg.addWidget(self.stldr_edit, 1, 1)
        fg.addWidget(btn_stldr, 1, 2)

        self.family = QComboBox()
        self.family.addItems(
            [
                "Auto (BMP detecta)",
                "STM32F1",
                "STM32F4",
                "STM32F7",
                "STM32H7 (Riverdi 7/10\")",
                "STM32U5 (Riverdi 5\")",
            ]
        )
        fg.addWidget(QLabel("Familia (informativo):"), 2, 0)
        fg.addWidget(self.family, 2, 1)

        self.swd_freq = QComboBox()
        for hz, label in SWD_FREQ_CHOICES:
            self.swd_freq.addItem(label, hz)
        # Default: 3.3 MHz (estable; 6 MHz cortó Write en Riverdi ~18 MB)
        idx_default = next(
            (i for i, (hz, _) in enumerate(SWD_FREQ_CHOICES) if hz == 3_272_727),
            2,
        )
        self.swd_freq.setCurrentIndex(idx_default)
        fg.addWidget(QLabel("Velocidad SWD:"), 3, 0)
        fg.addWidget(self.swd_freq, 3, 1)

        self.erase_cb = QCheckBox("Borrar flash interna (erase_mass) antes de grabar")
        self.erase_cb.setChecked(True)
        fg.addWidget(self.erase_cb, 4, 0, 1, 3)

        self.run_after_cb = QCheckBox("Run after programming (reset y arrancar la app)")
        self.run_after_cb.setChecked(True)
        fg.addWidget(self.run_after_cb, 5, 0, 1, 3)

        hint = QLabel(
            "F4/F1/F7: .hex/.elf y .stldr vacío + NRST cableado.\n"
            "Sin .stldr: solo flash interna (F1…H7/U5).\n"
            "Con .stldr: si el HEX tiene región 0x90000000, se programa la QSPI/OSPI "
            "ejecutando el loader en el destino (sin CubeProgrammer).\n"
            "Si falla con «Remote connection closed» en Write: bajá SWD a 2 o 3.3 MHz."
        )
        hint.setWordWrap(True)
        fg.addWidget(hint, 6, 0, 1, 3)
        layout.addWidget(files_box)

        # --- GDB ---
        gdb_box = QGroupBox("Toolchain")
        gg = QGridLayout(gdb_box)
        self.gdb_edit = QLineEdit()
        btn_gdb = QPushButton("…")
        btn_gdb.clicked.connect(self.browse_gdb)
        gg.addWidget(QLabel("arm-none-eabi-gdb:"), 0, 0)
        gg.addWidget(self.gdb_edit, 0, 1)
        gg.addWidget(btn_gdb, 0, 2)
        layout.addWidget(gdb_box)

        # --- Acciones ---
        row = QHBoxLayout()
        self.btn_flash = QPushButton("Programar")
        self.btn_flash.setMinimumHeight(36)
        self.btn_flash.clicked.connect(self.start_flash)
        row.addWidget(self.btn_flash)
        layout.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setVisible(False)
        layout.addWidget(self.progress)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QPlainTextEdit.NoWrap)
        layout.addWidget(self.log, stretch=1)

        gdb = find_gdb()
        if gdb:
            self.gdb_edit.setText(gdb)
            self.append_log(f"GDB detectado: {gdb}")
        else:
            self.append_log("GDB no encontrado automáticamente — seleccioná arm-none-eabi-gdb.exe")

        self.refresh_ports()

    def append_log(self, text: str) -> None:
        self.log.appendPlainText(text)

    def refresh_ports(self) -> None:
        self.port_combo.clear()
        ports = list_ports()
        bmps = [p for p in ports if p.is_bmp]
        if bmps:
            for p in bmps:
                tag = "GDB" if p.is_gdb else "BMP"
                self.port_combo.addItem(f"{p.device}  [{tag}]  {p.description}", p.device)
            gdb = pick_gdb_port(ports)
            if gdb:
                idx = self.port_combo.findData(gdb)
                if idx < 0:
                    # match device string
                    for i in range(self.port_combo.count()):
                        if self.port_combo.itemData(i) == gdb:
                            idx = i
                            break
                if idx >= 0:
                    self.port_combo.setCurrentIndex(idx)
            self.probe_status.setText(f"Sonda detectada: {len(bmps)} puerto(s) Black Magic")
            self.probe_status.setStyleSheet("color: green;")
        else:
            for p in ports:
                self.port_combo.addItem(f"{p.device}  {p.description}", p.device)
            self.probe_status.setText(
                "No se detectó Black Magic (VID 1D50). "
                "Elegí el COM a mano (en Windows: COM del GDB Server)."
            )
            self.probe_status.setStyleSheet("color: #a60;")

    def browse_hex(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Firmware",
            "",
            "Intel HEX / ELF (*.hex *.elf);;Todos (*.*)",
        )
        if path:
            self.hex_edit.setText(path)
            if path.lower().endswith(".elf") and self.stldr_edit.text().strip():
                self.append_log(
                    "AVISO: con .elf no se programa QSPI/OSPI; usá .hex + .stldr."
                )

    def browse_stldr(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "External Loader",
            "",
            "ST Loader (*.stldr);;ELF (*.elf);;Todos (*.*)",
        )
        if path:
            self.stldr_edit.setText(path)

    def browse_gdb(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "arm-none-eabi-gdb",
            "",
            "Executable (*.exe);;Todos (*.*)",
        )
        if path:
            self.gdb_edit.setText(path)

    def _flash_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start_flash(self) -> None:
        if self._flash_running():
            QMessageBox.warning(self, "Ocupado", "Ya hay una programación en curso.")
            return
        hex_path = self.hex_edit.text().strip()
        if not hex_path:
            QMessageBox.warning(self, "Falta HEX", "Seleccioná un archivo .hex / .elf")
            return
        port = self.port_combo.currentData() or self.port_combo.currentText().split()[0]
        if not port:
            QMessageBox.warning(self, "Sin puerto", "Detectá o elegí el puerto GDB de la sonda")
            return
        stldr = self.stldr_edit.text().strip() or None
        gdb = self.gdb_edit.text().strip() or None

        # Limpiar corrida anterior ya terminada
        self._cleanup_thread(wait_ms=100)

        self.btn_flash.setEnabled(False)
        self.progress.setVisible(True)
        swd_hz = int(self.swd_freq.currentData() or 3_272_727)
        self.append_log("")
        self.append_log(
            f"=== Programar | familia={self.family.currentText()} | "
            f"SWD={swd_hz} Hz ==="
        )

        thread = QThread(self)
        worker = FlashWorker(
            hex_path=hex_path,
            port=str(port),
            stldr_path=stldr,
            gdb_path=gdb,
            erase=self.erase_cb.isChecked(),
            run_after=self.run_after_cb.isChecked(),
            swd_freq_hz=swd_hz,
        )
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.log.connect(self.append_log)
        worker.finished.connect(self._on_finished)
        # quit del QThread cuando el worker termina (en el hilo receptor OK)
        worker.finished.connect(thread.quit)
        self._thread = thread
        self._worker = worker
        thread.start()

    def _cleanup_thread(self, wait_ms: int = 3000) -> None:
        thread = self._thread
        worker = self._worker
        self._thread = None
        self._worker = None
        if worker is not None:
            try:
                worker.log.disconnect(self.append_log)
            except TypeError:
                pass
            try:
                worker.finished.disconnect(self._on_finished)
            except TypeError:
                pass
            worker.deleteLater()
        if thread is not None:
            if thread.isRunning():
                thread.quit()
                if not thread.wait(wait_ms):
                    # último recurso: no destruir a la fuerza (evita el crash)
                    self.append_log(
                        "AVISO: el hilo de flasheo no terminó a tiempo; "
                        "esperá o cerrá GDB en el Administrador de tareas."
                    )
                    self._thread = thread
                    return
            thread.deleteLater()

    def _on_finished(self, ok: bool) -> None:
        self.progress.setVisible(False)
        self.btn_flash.setEnabled(True)

        thread = self._thread
        if thread is not None and thread.isRunning():
            thread.quit()
            thread.wait(5000)

        worker = self._worker
        self._worker = None
        self._thread = None
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()

        if ok:
            self.append_log("RESULTADO: OK")
            QMessageBox.information(self, "Programadora", "Programación finalizada.")
        else:
            self.append_log("RESULTADO: ERROR")
            QMessageBox.critical(
                self,
                "Programadora",
                "Falló la programación. Mirá el log.\n"
                "Si falló solo la parte STLDR, la flash interna puede haberse grabado igual.",
            )

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._flash_running():
            reply = QMessageBox.question(
                self,
                "Programación en curso",
                "Hay un flasheo en curso (GDB). ¿Salir igual?\n"
                "Si aceptás, esperá unos segundos a que termine el hilo.",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            if self._worker is not None:
                self._worker.request_abort()
            self._cleanup_thread(wait_ms=8000)
            if self._flash_running():
                QMessageBox.warning(
                    self,
                    "No se pudo detener",
                    "El hilo sigue activo (GDB bloqueado). "
                    "Cerrá arm-none-eabi-gdb.exe y volvé a intentar.",
                )
                event.ignore()
                return
        else:
            self._cleanup_thread(wait_ms=1000)
        event.accept()
