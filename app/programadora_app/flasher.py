"""Orquestación: HEX interno (+ STLDR externo) vía Black Magic + GDB."""

from __future__ import annotations

import re
import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .gdb_find import find_gdb
from .hex_util import split_hex
from .probe import normalize_port
from . import stldr_runner

LogFn = Callable[[str], None]

# Tope medido en la sonda F103 (pedí 8 MHz y BMP clampa a 6 MHz).
BMP_SWD_FREQ_HZ = 6_000_000


def _swd_freq_cmds() -> list[str]:
    return [f"monitor frequency {BMP_SWD_FREQ_HZ}"]


def flash(
    hex_path: Path,
    port: str,
    stldr_path: Path | None = None,
    gdb_path: str | None = None,
    erase: bool = True,
    run_after: bool = True,
    log: LogFn | None = None,
) -> bool:
    log = log or print
    hex_path = hex_path.resolve()
    if not hex_path.is_file():
        log(f"ERROR: no existe {hex_path}")
        return False

    gdb = find_gdb(gdb_path)
    if not gdb:
        log("ERROR: no se encontró arm-none-eabi-gdb (instalá GNU tools / CubeIDE).")
        return False
    log(f"GDB: {gdb}")

    port = normalize_port(port)
    log(f"Puerto: {port}")
    log(f"SWD: {BMP_SWD_FREQ_HZ} Hz (monitor frequency en cada sesión GDB)")

    suffix = hex_path.suffix.lower()
    if suffix == ".elf":
        if stldr_path:
            log(
                "ERROR: la flash externa (QSPI/OSPI) requiere un .hex con región "
                "0x90000000. Exportá Intel HEX desde CubeIDE/TouchGFX."
            )
            return False
        log("=== Flash interna desde ELF (BMP / GDB load) ===")
        ok = _flash_internal(gdb, port, hex_path, erase=erase, log=log)
        if ok and run_after:
            _run_after_programming(gdb, port, log)
        if ok:
            log("=== Listo ===")
        return ok

    if suffix == ".bin":
        log("ERROR: .bin sin dirección base no está soportado. Usá .hex o .elf.")
        return False

    work = Path(tempfile.mkdtemp(prefix="prog_"))
    try:
        split = split_hex(hex_path, work)
    except Exception as exc:  # noqa: BLE001
        log(f"ERROR leyendo HEX: {exc}")
        return False

    log(f"HEX interno: {split.internal_bytes} bytes")
    log(
        f"HEX externo: {split.external_bytes} bytes"
        + (
            f" (base 0x{split.external_base:08X})"
            if split.external_base is not None
            else ""
        )
    )

    if split.external_bytes and not stldr_path:
        log(
            "ERROR: el HEX tiene datos en flash externa (0x9….) "
            "y no indicaste .stldr (Riverdi / QSPI / OSPI)."
        )
        return False

    if stldr_path and not Path(stldr_path).is_file():
        log(f"ERROR: no existe stldr {stldr_path}")
        return False

    if not split.internal_bytes and not split.external_bytes:
        log(
            "ERROR: el HEX no tiene datos en 0x08000000 (interna) ni en "
            "0x90000000 (externa). ¿Archivo incorrecto o vacío?"
        )
        return False

    if split.internal_path and split.internal_bytes:
        log("=== Flash interna (BMP / GDB load) ===")
        ok = _flash_internal(gdb, port, split.internal_path, erase=erase, log=log)
        if not ok:
            return False
    else:
        log("Sin datos de flash interna en el HEX.")

    if split.external_path and split.external_bytes and stldr_path:
        log(
            f"=== Flash externa (STLDR v{stldr_runner.STLDR_RUNNER_VERSION} vía GDB) ==="
        )
        ok = stldr_runner.program_external(
            gdb=gdb,
            port=port,
            stldr=Path(stldr_path).resolve(),
            external_hex=split.external_path,
            log=log,
        )
        if not ok:
            return False
    elif stldr_path and not split.external_bytes:
        log(
            "AVISO: diste .stldr pero el HEX no tiene región 0x90000000; "
            "se ignora el loader (normal en F1/F4/F7 sin QSPI)."
        )

    if run_after:
        _run_after_programming(gdb, port, log)

    log("=== Listo ===")
    return True


def _connect_under_reset_cmds() -> list[str]:
    """Solo connect_rst (BMD). connect_srst ya no existe y ensucia el log."""
    return ["monitor connect_rst enable"]


def _run_after_programming(gdb: str, port: str, log: LogFn) -> None:
    """Arrancar el MCU tras programar.

    En BMP, ``monitor reset`` pulsa NRST y **desconecta** el target: no se puede
    escribir SP/PC después. Secuencia correcta:
    1) attach + cargar SP/PC desde vectores + quitar C_HALT
    2) detach
    3) desactivar connect-under-reset y pulsar NRST para boot limpio
    """
    log("=== Run after programming ===")
    cmds = [
        "set confirm off",
        "set pagination off",
        "set mem inaccessible-by-default off",
        f"target extended-remote {port}",
        *_swd_freq_cmds(),
        "monitor connect_rst disable",
        "monitor swdp_scan",
        "attach 1",
        "monitor halt",
        "set $sp = *(unsigned int*)0x08000000",
        "set $pc = *(unsigned int*)0x08000004",
        # DHCSR: DBGKEY | C_DEBUGEN  (C_HALT=0 → correr)
        "set *(unsigned int*)0xE000EDF0 = 0xA05F0001",
        "detach",
        # Pulso NRST sin attach: el firmware arranca solo desde flash
        "monitor reset",
        "quit",
    ]
    args = [gdb, "-nx", "--batch", "--quiet"]
    for c in cmds:
        args.extend(["-ex", c])
    for c in cmds:
        log(f"  (gdb) {c}")
    try:
        proc = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=60
        )
    except subprocess.TimeoutExpired:
        log("AVISO: timeout en run after programming")
        return
    out = (proc.stdout or "") + (proc.stderr or "")
    for line in out.splitlines():
        if line.strip():
            log(line)
    mem_fail = "cannot access memory" in out.lower()
    if proc.returncode != 0 or mem_fail:
        log(
            "AVISO: no se pudo preparar SP/PC; se intentó reset por NRST. "
            "Si el MCU no arranca, desconectá USB SWD un momento o power-cycle."
        )
    else:
        log("MCU liberado: SP/PC desde vectores + pulso NRST (debe correr solo).")


def _flash_internal(
    gdb: str,
    port: str,
    hex_path: Path,
    erase: bool,
    log: LogFn,
) -> bool:
    image = hex_path.as_posix()

    # Sesión 1 (opcional): erase_mass. En F4 a veces tira "packet error" / cuelga
    # el canal GDB; por eso va aparte y, si falla, seguimos con load (el load
    # ya borra sectores).
    if erase:
        log("--- GDB (erase_mass, sesión aparte) ---")
        erase_cmds = [
            "set confirm off",
            "set pagination off",
            "set mem inaccessible-by-default off",
            f"target extended-remote {port}",
            *_swd_freq_cmds(),
            *_connect_under_reset_cmds(),
            "monitor swdp_scan",
            "attach 1",
            "monitor halt",
            "monitor erase_mass",
            "detach",
            "quit",
        ]
        erase_ok, erase_blob = _run_gdb(
            gdb, erase_cmds, log, timeout_s=180, label="erase"
        )
        if _erase_succeeded(erase_blob):
            log("erase_mass OK.")
        elif not erase_ok or _erase_looks_broken(erase_blob):
            log(
                "AVISO: erase_mass falló o dejó el canal GDB inestable "
                "(conocido en F4). Se reintenta attach + load (borra por sector)."
            )
        else:
            log("erase_mass OK.")

    # Sesión 2: load + verificación de vectores
    cmds = [
        "set confirm off",
        "set pagination off",
        "set mem inaccessible-by-default off",
        f"target extended-remote {port}",
        *_swd_freq_cmds(),
        *_connect_under_reset_cmds(),
        "monitor swdp_scan",
        "attach 1",
        "monitor halt",
        f"load {image}",
        "x/4xw 0x08000000",
        "detach",
        "quit",
    ]
    log("--- GDB (load interna) ---")
    ok, blob = _run_gdb(gdb, cmds, log, timeout_s=600, label="load")
    if not ok:
        _hint_f4(blob, log)
        return False

    if "Transfer rate:" not in blob and "Loading section" not in blob:
        log("ERROR: GDB no reportó carga de secciones (¿falló attach/load?)")
        _hint_f4(blob, log)
        return False

    dumps = list(
        re.finditer(
            r"0x0*8000000:\s+(0x[0-9a-fA-F]+)\s+(0x[0-9a-fA-F]+)",
            blob,
        )
    )
    if dumps:
        sp_s, rv_s = dumps[-1].group(1), dumps[-1].group(2)
        sp_v = int(sp_s, 16)
        rv_v = int(rv_s, 16)
        log(f"Post-load @0x08000000: SP={sp_s} Reset={rv_s}")
        if sp_v == 0xFFFFFFFF and rv_v == 0xFFFFFFFF:
            log(
                "ERROR: flash en 0x08000000 sigue borrada (FFFFFFFF). "
                "El load no grabó. Típico F4: NRST mal, SWD flojo, o chip distinto."
            )
            _hint_f4(blob, log)
            return False
        reset_addr = rv_v & ~1
        if reset_addr < 0x08000000 or reset_addr > 0x08200000:
            log(
                f"AVISO: reset vector {rv_s} no parece código en flash 0x0800…. "
                "Revisá que el .hex sea del MCU correcto (F4)."
            )
    else:
        log("AVISO: no se pudo leer vectores en 0x08000000 tras el load.")

    m = re.search(r"(\d+)\s+(STM32\S+[^\n]*)", blob)
    if m:
        log(f"Target detectado: {m.group(2).strip()}")
    elif "Available Targets" in blob and "No. Att" in blob:
        # scan sin match de nombre: aún así listamos ayuda si no hay STM32
        if "STM32" not in blob:
            log("ERROR: swdp_scan no listó un STM32. Revisá cableado/alimentación.")
            _hint_f4(blob, log)
            return False

    log("Flash interna OK.")
    return True


def _run_gdb(
    gdb: str,
    cmds: list[str],
    log: LogFn,
    timeout_s: int,
    label: str,
) -> tuple[bool, str]:
    args = [gdb, "-nx", "--batch", "--quiet"]
    for c in cmds:
        args.extend(["-ex", c])
    for c in cmds:
        log(f"  (gdb) {c}")
    try:
        proc = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=timeout_s
        )
    except subprocess.TimeoutExpired:
        log(f"ERROR: GDB timeout en {label} ({timeout_s}s)")
        return False, ""

    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for line in blob.splitlines():
        if line.strip():
            log(line)

    if proc.returncode != 0:
        log(f"ERROR: GDB código {proc.returncode} ({label})")
        return False, blob
    return True, blob


def _erase_succeeded(blob: str) -> bool:
    """True si BMP reportó borrado completo (ignora ruido de 'timeout' del halt)."""
    low = (blob or "").lower()
    if "erasing device flash" in low and "done" in low:
        return True
    if "erase complete" in low:
        return True
    return False


def _erase_looks_broken(blob: str) -> bool:
    low = blob.lower()
    if not blob:
        return True
    if _erase_succeeded(blob):
        return False
    if "packet error" in low:
        return True
    # No matchear "timeout to wait for device halts: 2000" (mensaje informativo BMP)
    if "timed out" in low or "request timed out" in low:
        return True
    if "failed" in low and "erase" in low:
        return True
    if "no target" in low:
        return True
    return False


def _hint_f4(blob: str, log: LogFn) -> None:
    low = (blob or "").lower()
    log("--- Ayuda F4 / flash interna ---")
    log("1) Cableá SWDIO / SWCLK / GND y NRST (en F4 el reset suele ser necesario).")
    log("2) Alimentá el F4 a 3.3 V con fuente propia + GND común.")
    log("3) Dejá el campo .stldr vacío (solo Riverdi lo necesita).")
    log("4) HEX/ELF del proyecto F4 tras Clean+Build (fecha de hoy).")
    log("5) Sonda: Blue Pill=PA5/PB14/PB1; PCB propia=PB13/PB14/PB5.")
    log("6) Si erase_mass cuelga: desmarcá «Borrar flash» y reintentá (load borra sectores).")
    if "no target" in low or ("fail" in low and "scan" in low):
        log("→ swdp_scan no ve el chip: cableado o alimentación.")
    if "timeout" in low:
        log("→ timeout: NRST / reset manual al conectar.")
    if "erase" in low and "fail" in low:
        log("→ erase falló: RDP o voltaje bajo.")
    if "packet error" in low:
        log("→ packet error en erase_mass: típico F4; power-cycle del destino y load.")
