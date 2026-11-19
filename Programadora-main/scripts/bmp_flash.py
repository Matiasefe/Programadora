#!/usr/bin/env python3
"""
Graba un archivo Intel HEX (.hex) en un STM32 destino usando una
Blue Pill convertida en Black Magic Probe (puerto GDB por USB-CDC).

Ejemplos (Windows):
  python scripts/bmp_flash.py firmware.hex
  python scripts/bmp_flash.py firmware.hex --port COM30
  python scripts/bmp_flash.py firmware.hex --list-ports

Requisitos:
  - Python 3.9+
  - pyserial  (pip install -r requirements.txt)
  - arm-none-eabi-gdb  (o gdb-multiarch) en el PATH
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Black Magic Probe USB IDs (openmoko)
BMP_VID = 0x1D50
BMP_PIDS = {0x6017, 0x6018, 0x6019}


def eprint(*args: object) -> None:
    print(*args, file=sys.stderr)


def _windows_cubeide_gdbs() -> list[str]:
    """Busca arm-none-eabi-gdb.exe dentro de instalaciones típicas de STM32CubeIDE."""
    found: list[str] = []
    roots: list[Path] = []
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        val = os.environ.get(key)
        if val:
            roots.append(Path(val))
    roots.append(Path.home())

    patterns = [
        "STM32CubeIDE*/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32*/tools/bin/arm-none-eabi-gdb.exe",
        "STMicroelectronics/STM32Cube/STM32CubeIDE*/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32*/tools/bin/arm-none-eabi-gdb.exe",
        "stm32cube/bundles/gnu-tools-for-stm32/*/bin/arm-none-eabi-gdb.exe",
        "Arm GNU Toolchain*/bin/arm-none-eabi-gdb.exe",
        "GNU Arm Embedded Toolchain*/bin/arm-none-eabi-gdb.exe",
    ]

    for root in roots:
        for pattern in patterns:
            try:
                for match in root.glob(pattern):
                    if match.is_file():
                        found.append(str(match))
            except OSError:
                continue
    # Más recientes primero (nombre de carpeta suele ordenar por versión)
    found.sort(reverse=True)
    return found


def find_gdb() -> str:
    env = os.environ.get("BMP_GDB") or os.environ.get("ARM_GDB")
    candidates: list[str] = []
    if env:
        candidates.append(env)

    for name in ("arm-none-eabi-gdb", "gdb-multiarch", "gdb"):
        path = shutil.which(name)
        if path:
            candidates.append(path)

    if os.name == "nt":
        candidates.extend(_windows_cubeide_gdbs())

    seen: set[str] = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if Path(path).is_file() or shutil.which(path):
            return path if Path(path).is_file() else (shutil.which(path) or path)

    eprint(
        "No encontré arm-none-eabi-gdb.\n\n"
        "Opciones:\n"
        "  1) Si tenés STM32CubeIDE, buscá arm-none-eabi-gdb.exe y definí:\n"
        "       set BMP_GDB=C:\\ruta\\completa\\arm-none-eabi-gdb.exe\n"
        "  2) Instalá Arm GNU Toolchain y agregá su carpeta bin al PATH.\n"
        "  3) En PowerShell, para buscarlo:\n"
        "       Get-ChildItem -Path 'C:\\' -Filter arm-none-eabi-gdb.exe -Recurse -ErrorAction SilentlyContinue\n"
    )
    sys.exit(2)


def list_serial_ports() -> list:
    try:
        from serial.tools import list_ports
    except ImportError:
        eprint("Falta pyserial. Ejecutá: pip install pyserial")
        sys.exit(2)
    return list(list_ports.comports())


def print_ports(ports: list) -> None:
    if not ports:
        print("No hay puertos serie.")
        return
    print(f"{'Puerto':<12} {'VID:PID':<12} Descripción")
    print("-" * 60)
    for p in ports:
        vidpid = f"{p.vid:04X}:{p.pid:04X}" if p.vid is not None else "-"
        desc = p.description or ""
        iface = getattr(p, "interface", None) or ""
        extra = f" | {iface}" if iface else ""
        print(f"{p.device:<12} {vidpid:<12} {desc}{extra}")


def bmp_ports(ports: list) -> list:
    """Puertos que parecen Black Magic Probe."""
    found = []
    for p in ports:
        desc = (p.description or "").lower()
        iface = (getattr(p, "interface", None) or "").lower()
        hay_bmp = (
            (p.vid == BMP_VID and p.pid in BMP_PIDS)
            or "black magic" in desc
            or "black magic" in iface
            or "bmp" == desc.strip()
        )
        if hay_bmp:
            found.append(p)
    return found


def pick_gdb_port(ports: list, explicit: str | None) -> str:
    if explicit:
        return normalize_port(explicit)

    bmps = bmp_ports(ports)
    if not bmps:
        # En Windows a veces solo dice "USB Serial Device" sin VID visible
        # según el driver; pedimos --port.
        eprint(
            "No pude detectar automáticamente la Black Magic Probe.\n"
            "Usá:  python scripts/bmp_flash.py archivo.hex --port COM30\n"
            "Listar: python scripts/bmp_flash.py --list-ports"
        )
        print_ports(ports)
        sys.exit(2)

    # Preferir interfaz/descripcion GDB
    for p in bmps:
        blob = f"{p.description} {getattr(p, 'interface', '')}".lower()
        if "gdb" in blob:
            return normalize_port(p.device)

    # Si hay exactamente 2 CDC, el primero suele ser GDB
    bmps_sorted = sorted(bmps, key=lambda p: p.device)
    chosen = bmps_sorted[0]
    if len(bmps_sorted) > 1:
        eprint(
            f"Varios puertos BMP: {[p.device for p in bmps_sorted]}. "
            f"Uso {chosen.device} (GDB). Si falla, probá --port con el otro."
        )
    return normalize_port(chosen.device)


def normalize_port(port: str) -> str:
    """GDB en Windows conviene con \\\\.\\COMx (sobre todo COM10+)."""
    p = port.strip()
    if os.name == "nt":
        if p.startswith("\\\\.\\"):
            p = p[4:]
        up = p.upper()
        if up.startswith("COM") and up[3:].isdigit():
            return "\\\\.\\" + up
    return p


def file_info(path: Path) -> None:
    import hashlib

    data = path.read_bytes()
    digest = hashlib.sha256(data).hexdigest()[:16]
    mtime = path.stat().st_mtime
    from datetime import datetime

    when = datetime.fromtimestamp(mtime).isoformat(sep=" ", timespec="seconds")
    print(f"Archivo: {path}")
    print(f"Tamaño:  {len(data)} bytes")
    print(f"Fecha:   {when}")
    print(f"SHA256:  {digest}…")


def run_gdb(gdb: str, cmds: list[str]) -> subprocess.CompletedProcess:
    gdb_args = [gdb, "-nx", "--batch", "--quiet"]
    for c in cmds:
        gdb_args.extend(["-ex", c])
    print("--- GDB ---")
    for c in cmds:
        print(f"  (gdb) {c}")
    print("------------")
    return subprocess.run(gdb_args, check=False, text=True, capture_output=False)


def flash_hex(
    gdb: str,
    port: str,
    hex_path: Path,
    reset: bool,
    verify: bool,
    erase: bool,
) -> int:
    hex_path = hex_path.resolve()
    if not hex_path.is_file():
        eprint(f"No existe el archivo: {hex_path}")
        return 1
    if hex_path.suffix.lower() not in {".hex", ".ihex", ".elf", ".bin"}:
        eprint(f"Aviso: extensión {hex_path.suffix} (se esperaba .hex/.elf/.bin)")

    print(f"GDB:    {gdb}")
    print(f"Puerto: {port}")
    file_info(hex_path)

    # Ruta con forward slashes: GDB en Windows la acepta mejor
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
        # Tras borrar, la flash en 0x08000000 debería leer 0xffffffff
        cmds.append("x/1xw 0x08000000")
    cmds.append(f"load {image}")
    # Vector table / primeras palabras: deben dejar de ser 0xffffffff
    cmds.append("x/4xw 0x08000000")
    if verify and hex_path.suffix.lower() in {".elf"}:
        cmds.append("compare-sections")
    if reset:
        cmds.append("monitor reset")
    cmds.append("detach")
    cmds.append("quit")

    proc = run_gdb(gdb, cmds)
    if proc.returncode != 0:
        eprint(
            f"GDB salió con código {proc.returncode}.\n"
            "Revisá: cable SWD (PB14/PA5/PB1/GND), alimentación del destino a 3.3V, "
            "NRST conectado, y que --port sea el COM del GDB Server."
        )
        return proc.returncode

    print(
        "GDB terminó (código 0).\n"
        "Mirá arriba el 'x/1xw' post-erase (debe ser ffffffff) y el 'x/4xw' "
        "post-load (NO debe ser todo ffffffff). Si el LED sigue igual tras "
        "erase_mass, no estás mirando el MCU que la sonda está borrando."
    )
    return 0


def dump_flash(gdb: str, port: str) -> int:
    cmds = [
        "set confirm off",
        "set pagination off",
        f"target extended-remote {port}",
        "monitor swdp_scan",
        "attach 1",
        "x/8xw 0x08000000",
        "detach",
        "quit",
    ]
    print(f"GDB:    {gdb}")
    print(f"Puerto: {port}")
    return run_gdb(gdb, cmds).returncode


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Programa un .hex/.elf en un STM32 vía Black Magic Probe (Blue Pill)."
    )
    p.add_argument(
        "firmware",
        nargs="?",
        help="Ruta al archivo .hex (también acepta .elf / .bin)",
    )
    p.add_argument(
        "--port",
        "-p",
        help="Puerto GDB de la sonda (ej. COM30 o /dev/ttyACM0)",
    )
    p.add_argument(
        "--gdb",
        help="Ruta a arm-none-eabi-gdb.exe (si no está en el PATH)",
    )
    p.add_argument(
        "--list-ports",
        action="store_true",
        help="Lista puertos serie y sale",
    )
    p.add_argument(
        "--dump",
        action="store_true",
        help="Solo lee las primeras palabras de flash del destino (diagnóstico)",
    )
    p.add_argument(
        "--no-reset",
        action="store_true",
        help="No resetear el destino al terminar",
    )
    p.add_argument(
        "--no-erase",
        action="store_true",
        help="No hacer erase_mass antes del load (por defecto SÍ borra)",
    )
    p.add_argument(
        "--verify",
        action="store_true",
        help="compare-sections (solo útil con .elf)",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    ports = list_serial_ports()

    if args.list_ports:
        print_ports(ports)
        bmps = bmp_ports(ports)
        if bmps:
            print("\nPosibles Black Magic:")
            for p in bmps:
                print(f"  {p.device}  {p.description}")
        return 0

    if args.gdb:
        os.environ["BMP_GDB"] = args.gdb
    gdb = find_gdb()
    port = pick_gdb_port(ports, args.port)

    if args.dump:
        return dump_flash(gdb, port)

    if not args.firmware:
        eprint("Falta el archivo .hex. Ejemplo: python scripts/bmp_flash.py app.hex --port COM30")
        return 2

    return flash_hex(
        gdb=gdb,
        port=port,
        hex_path=Path(args.firmware),
        reset=not args.no_reset,
        verify=args.verify,
        erase=not args.no_erase,
    )


if __name__ == "__main__":
    sys.exit(main())
