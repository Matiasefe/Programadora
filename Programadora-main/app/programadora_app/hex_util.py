"""Separar Intel HEX en flash interna vs externa (QSPI/OSPI)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Regiones típicas STM32 / Riverdi
INTERNAL_MAX = 0x0FFFFFFF  # hasta antes de regiones memoria mapeada alta
EXTERNAL_BASE = 0x90000000  # QSPI/OSPI memory-mapped típico ST


@dataclass
class HexSplit:
    internal_path: Path | None
    external_path: Path | None
    internal_bytes: int
    external_bytes: int
    external_base: int | None


def split_hex(hex_path: Path, work_dir: Path) -> HexSplit:
    from intelhex import IntelHex

    suffix = hex_path.suffix.lower()
    if suffix not in {".hex", ".ihex", ".mcs"}:
        raise ValueError(
            f"split_hex espera Intel HEX (.hex); recibió '{hex_path.suffix}'"
        )

    ih = IntelHex(str(hex_path))
    internal = IntelHex()
    external = IntelHex()
    ext_base = None
    for addr in ih.addresses():
        val = ih[addr]
        if addr >= EXTERNAL_BASE:
            external[addr] = val
            if ext_base is None or addr < ext_base:
                ext_base = addr
        elif 0x08000000 <= addr <= INTERNAL_MAX:
            internal[addr] = val
        elif 0x08000000 <= addr < EXTERNAL_BASE:
            # otras regiones (ej. flash banco2, etc.) → interna MCU
            internal[addr] = val
        else:
            # RAM u otros: ignorar para flasheo
            pass

    work_dir.mkdir(parents=True, exist_ok=True)
    internal_path = None
    external_path = None
    internal_bytes = 0
    external_bytes = 0

    if internal.addresses():
        internal_path = work_dir / "internal.hex"
        internal.write_hex_file(str(internal_path))
        segs = internal.segments()
        internal_bytes = sum(e - s for s, e in segs)
    if external.addresses():
        external_path = work_dir / "external.hex"
        external.write_hex_file(str(external_path))
        segs = external.segments()
        external_bytes = sum(e - s for s, e in segs)

    return HexSplit(
        internal_path=internal_path,
        external_path=external_path,
        internal_bytes=internal_bytes,
        external_bytes=external_bytes,
        external_base=ext_base,
    )
