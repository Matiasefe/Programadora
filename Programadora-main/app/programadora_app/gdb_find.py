"""Localizar arm-none-eabi-gdb."""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _windows_candidates() -> list[str]:
    found: list[str] = []
    roots: list[Path] = []
    for key in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        val = os.environ.get(key)
        if val:
            roots.append(Path(val))
    roots.append(Path.home())
    # Instalaciones típicas fuera de Program Files (p.ej. C:\ST\STM32CubeIDE_x.y)
    for extra in (Path("C:/ST"), Path("D:/ST"), Path("C:/STM32CubeIDE"), Path("D:/STM32CubeIDE")):
        if extra.is_dir():
            roots.append(extra)

    patterns = [
        "STM32CubeIDE*/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32*/tools/bin/arm-none-eabi-gdb.exe",
        "STM32CubeIDE*/STM32CubeIDE/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32*/tools/bin/arm-none-eabi-gdb.exe",
        "STMicroelectronics/STM32Cube/STM32CubeIDE*/plugins/com.st.stm32cube.ide.mcu.externaltools.gnu-tools-for-stm32*/tools/bin/arm-none-eabi-gdb.exe",
        "stm32cube/bundles/gnu-tools-for-stm32/*/bin/arm-none-eabi-gdb.exe",
        "Arm GNU Toolchain*/bin/arm-none-eabi-gdb.exe",
        "**/arm-none-eabi-gdb.exe",  # último recurso en roots acotados (C:\ST, etc.)
    ]
    # Evitar glob ** sobre Program Files / home (muy lento)
    deep_roots = {Path("C:/ST"), Path("D:/ST"), Path("C:/STM32CubeIDE"), Path("D:/STM32CubeIDE")}
    for root in roots:
        for pattern in patterns:
            if pattern.startswith("**/") and root.resolve() not in {p.resolve() for p in deep_roots if p.is_dir()}:
                continue
            try:
                for match in root.glob(pattern):
                    if match.is_file():
                        found.append(str(match))
            except OSError:
                continue
    found.sort(reverse=True)
    return found


def find_gdb(explicit: str | None = None) -> str | None:
    candidates: list[str] = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("BMP_GDB") or os.environ.get("ARM_GDB")
    if env:
        candidates.append(env)
    for name in ("arm-none-eabi-gdb", "gdb-multiarch", "gdb"):
        path = shutil.which(name)
        if path:
            candidates.append(path)
    if os.name == "nt":
        candidates.extend(_windows_candidates())
    seen: set[str] = set()
    for path in candidates:
        if not path or path in seen:
            continue
        seen.add(path)
        if Path(path).is_file():
            return path
        which = shutil.which(path)
        if which:
            return which
    return None
