"""Orquestación: HEX interno (+ STLDR externo) vía Black Magic + GDB."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Callable

from .gdb_find import find_gdb
from .hex_util import split_hex
from .probe import normalize_port
from . import stldr_runner

LogFn = Callable[[str], None]


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

    suffix = hex_path.suffix.lower()
    # .elf: solo flash interna vía `load` (no se puede partir 0x9000… sin HEX)
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
        log(
            "ERROR: .bin sin dirección base no está soportado. "
            "Usá .hex o .elf."
        )
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

    if stldr_path and not stldr_path.is_file():
        log(f"ERROR: no existe stldr {stldr_path}")
        return False

    if split.internal_path and split.internal_bytes:
        log("=== Flash interna (BMP / GDB load) ===")
        # Sin reset acá: si hay externa todavía no está lista
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
            stldr=stldr_path.resolve(),
            external_hex=split.external_path,
            log=log,
        )
        if not ok:
            return False
    elif stldr_path and not split.external_bytes:
        log(
            "AVISO: diste .stldr pero el HEX no tiene región 0x90000000; "
            "se ignora el loader."
        )

    if run_after:
        _run_after_programming(gdb, port, log)

    log("=== Listo ===")
    return True


def _run_after_programming(gdb: str, port: str, log: LogFn) -> None:
    """Reset + liberar el core (equiv. Cube 'Run after programming')."""
    log("=== Run after programming ===")
    cmds = [
        "set confirm off",
        "set pagination off",
        f"target extended-remote {port}",
        "monitor swdp_scan",
        "attach 1",
        "monitor reset",
        # Tras reset BMP deja el core en halt; limpiar C_HALT vía DHCSR
        # (evita `continue` que cuelga GDB en --batch)
        "set *(unsigned int *)0xE000EDF0 = 0xA05F0000",
        "detach",
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
    if proc.returncode != 0:
        log(f"AVISO: run after programming GDB código {proc.returncode}")
    else:
        log("Target en run (reset + detach).")


def _flash_internal(
    gdb: str,
    port: str,
    hex_path: Path,
    erase: bool,
    log: LogFn,
) -> bool:
    image = hex_path.as_posix()
    cmds = [
        "set confirm off",
        "set pagination off",
        f"target extended-remote {port}",
        "monitor swdp_scan",
        "attach 1",
    ]
    if erase:
        cmds.append("monitor erase_mass")
        cmds.append("x/1xw 0x08000000")
    cmds.append(f"load {image}")
    cmds.append("x/4xw 0x08000000")
    # Sin reset acá: lo hace _run_after_programming al final de todo
    cmds.append("detach")
    cmds.append("quit")

    args = [gdb, "-nx", "--batch", "--quiet"]
    for c in cmds:
        args.extend(["-ex", c])
    log("--- GDB (interna) ---")
    for c in cmds:
        log(f"  (gdb) {c}")
    try:
        proc = subprocess.run(
            args, check=False, capture_output=True, text=True, timeout=600
        )
    except subprocess.TimeoutExpired:
        log("ERROR: GDB timeout en flash interna (600s)")
        return False
    if proc.stdout:
        for line in proc.stdout.splitlines():
            log(line)
    if proc.stderr:
        for line in proc.stderr.splitlines():
            log(line)
    if proc.returncode != 0:
        log(f"ERROR: GDB código {proc.returncode}")
        return False
    blob = (proc.stdout or "") + (proc.stderr or "")
    if "Transfer rate:" not in blob and "Loading section" not in blob:
        log("ERROR: GDB no reportó carga de secciones (¿falló el attach/load?)")
        return False
    log("Flash interna OK.")
    return True
