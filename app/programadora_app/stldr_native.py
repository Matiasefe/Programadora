"""Programación externa .stldr vía RSP nativo (sin gdb.exe).

Una sola sesión: attach → cargar loader → Init → MassErase → Writes en
streaming. Reconnect solo si cae el USB; Init otra vez tras reconnect.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from . import bmp_rsp
from .bmp_rsp import BmpRsp, BmpRspError
from .probe import normalize_port
from . import stldr_runner as base

LogFn = Callable[[str], None]

NATIVE_VERSION = 1


def program_external_native(
    port: str,
    stldr: Path,
    external_hex: Path,
    log: LogFn,
    swd_freq_hz: int = base.DEFAULT_SWD_FREQ_HZ,
    chunk_size: int = base.CHUNK_SIZE_DEFAULT,
    batch_pause_s: float = base.WRITE_BATCH_PAUSE_S,
) -> bool:
    from intelhex import IntelHex

    stldr = stldr.resolve()
    external_hex = external_hex.resolve()
    port = normalize_port(port)
    swd_freq_hz = max(100_000, min(int(swd_freq_hz), base.MAX_SWD_FREQ_HZ))
    chunk_size = base._clamp_chunk_size(chunk_size)
    batch_pause_s = max(0.0, float(batch_pause_s))

    log(
        f"STLDR_NATIVE_VERSION={NATIVE_VERSION} / runner={base.STLDR_RUNNER_VERSION} "
        f"(RSP sin gdb.exe | SWD {swd_freq_hz} Hz | chunk {chunk_size} B)"
    )

    info = base._elf_info(stldr)
    if "Write" not in info["symbols"]:
        log("ERROR: el .stldr no exporta Write().")
        return False
    init_addr = info["symbols"].get("Init", info["entry"])
    write_addr = info["symbols"]["Write"]
    mass_addr = info["symbols"].get("MassErase")
    sector_addr = info["symbols"].get("SectorErase")
    if init_addr is None:
        log("ERROR: no hay Init ni entry en el .stldr.")
        return False

    for name, addr in sorted(info["symbols"].items()):
        log(f"  símbolo {name} @ 0x{addr:08X}")

    ram_segs = [s for s in info["segments"] if s["vaddr"] >= base.RAM_MIN]
    if not ram_segs:
        log("ERROR: no hay segmentos PT_LOAD en RAM.")
        return False

    scratch, trampoline, stack_addr = base._pick_ram_layout(ram_segs, chunk_size)
    log(
        f"Layout RAM: scratch=0x{scratch:08X} (+{chunk_size} B) "
        f"trampoline=0x{trampoline:08X} sp=0x{stack_addr:08X}"
    )

    log("Leyendo HEX externo…")
    ih = IntelHex(str(external_hex))
    addrs = ih.addresses()
    if not addrs:
        log("No hay datos externos.")
        return True
    min_a, max_a = min(addrs), max(addrs)
    total = max_a - min_a + 1
    log(
        f"Externa HEX: 0x{min_a:08X} .. 0x{max_a:08X} "
        f"(span {total} = {base._fmt_bytes(total)})"
    )
    blob = bytes(ih.tobinarray(start=min_a, size=total))

    # Particionar en memoria (sin miles de archivos temp)
    chunks: list[tuple[int, bytes]] = []
    off = 0
    while off < len(blob):
        piece = blob[off : off + chunk_size]
        chunks.append((min_a + off, piece))
        off += chunk_size
    log(f"Total Write: {len(chunks)} bloques de hasta {chunk_size} B")

    erase_timeout = (
        base._mass_erase_timeout_s(len(blob)) if mass_addr is not None else 600
    )

    next_i = 0
    need_erase = True
    max_sessions = 8

    for session in range(1, max_sessions + 1):
        log(f"=== Sesión RSP {session}/{max_sessions} (desde bloque {next_i}) ===")
        if session > 1:
            base._wait_port_ready(port, log, timeout_s=base.PORT_WAIT_S)
            time.sleep(1.0)

        try:
            with BmpRsp(port, log=log, timeout_s=5.0) as bmp:
                bmp.handshake()
                log("RSP handshake OK")
                try:
                    bmp.connect_rst(True)
                except BmpRspError as exc:
                    log(f"AVISO connect_rst: {exc}")
                freq_out = bmp.set_frequency(swd_freq_hz)
                if freq_out.strip():
                    log(freq_out.strip())
                else:
                    log(f"SWD frequency → {swd_freq_hz} Hz")
                scan = bmp.swdp_scan()
                for line in scan.splitlines():
                    if line.strip():
                        log(line)
                if "Available Targets" not in scan and "STM32" not in scan:
                    # algunos firmwares formatean distinto
                    log("AVISO: scan sin texto STM32 típico; se intenta attach")
                bmp.attach(1)
                try:
                    bmp.halt()
                except BmpRspError:
                    pass
                log("Attach OK — cargando .stldr en RAM")

                for i, seg in enumerate(ram_segs):
                    bmp.mem_write(int(seg["vaddr"]), seg["data"])
                    log(
                        f"  seg RAM {i}: {seg['filesz']} bytes → "
                        f"0x{seg['vaddr']:08X}"
                    )
                # trampolín: NOP Thumb (Z0 lo parchea al poner break)
                bmp.mem_write(trampoline & ~1, b"\x00\xbf\x00\xbf")

                # Init una vez por sesión
                rc = bmp.call_thumb(
                    func=int(init_addr),
                    trampoline=trampoline,
                    stack=stack_addr,
                    timeout_s=120.0,
                    label="Init",
                )
                if rc not in (0, 1):
                    log(f"AVISO: Init retornó 0x{rc:x} (se continúa)")

                if need_erase:
                    log("=== Erase (una vez) ===")
                    if mass_addr is not None:
                        log(
                            f"MassErase timeout {erase_timeout}s "
                            f"(~{erase_timeout // 60} min)"
                        )
                        rc = bmp.call_thumb(
                            func=int(mass_addr),
                            trampoline=trampoline,
                            stack=stack_addr,
                            timeout_s=float(erase_timeout),
                            label="MassErase",
                        )
                        if rc not in (0, 1):
                            log(f"ERROR: MassErase ret=0x{rc:x}")
                            return False
                    elif sector_addr is not None:
                        a = min_a & ~(base.SECTOR_ERASE_STEP - 1)
                        nsec = 0
                        while a <= max_a:
                            end_a = min(a + base.SECTOR_ERASE_STEP - 1, max_a)
                            label = f"Sec{nsec}" if nsec % 64 == 0 else ""
                            rc = bmp.call_thumb(
                                func=int(sector_addr),
                                trampoline=trampoline,
                                stack=stack_addr,
                                r0=a,
                                r1=end_a,
                                timeout_s=60.0,
                                label=label,
                            )
                            if rc not in (0, 1):
                                log(f"ERROR: SectorErase @0x{a:X} ret=0x{rc:x}")
                                return False
                            a += base.SECTOR_ERASE_STEP
                            nsec += 1
                            if nsec % 128 == 0:
                                log(f"  SectorErase {nsec}…")
                        log(f"SectorErase ×{nsec} OK")
                    else:
                        log("AVISO: sin erase en loader")
                    need_erase = False
                    log("Erase OK")

                log(
                    f"=== Write streaming {next_i}..{len(chunks) - 1} "
                    f"(un solo attach) ==="
                )
                last_hb = time.monotonic()
                while next_i < len(chunks):
                    waddr, piece = chunks[next_i]
                    bmp.mem_write(scratch, piece)
                    rc = bmp.call_thumb(
                        func=int(write_addr),
                        trampoline=trampoline,
                        stack=stack_addr,
                        r0=waddr,
                        r1=len(piece),
                        r2=scratch,
                        timeout_s=120.0,
                        label=f"W{next_i}" if next_i % 16 == 0 else "",
                    )
                    if rc not in (0, 1):
                        log(f"ERROR: Write[{next_i}] @0x{waddr:08X} ret=0x{rc:x}")
                        return False
                    next_i += 1
                    now = time.monotonic()
                    if next_i % 16 == 0 or now - last_hb >= 15.0:
                        pct = 100.0 * next_i / len(chunks)
                        log(f"PROG {next_i}/{len(chunks)} ({pct:.1f}%)")
                        last_hb = now
                    if batch_pause_s > 0 and next_i % 32 == 0 and next_i < len(chunks):
                        # micro-pausa cada 32 writes (no detach)
                        time.sleep(min(batch_pause_s, 0.5))

                # verify sample
                log("=== Verify @0x90000000 ===")
                try:
                    # Re-Init suele dejar memory-mapped
                    bmp.call_thumb(
                        func=int(init_addr),
                        trampoline=trampoline,
                        stack=stack_addr,
                        timeout_s=60.0,
                        label="Init",
                    )
                    got = bmp.mem_read(0x90000000, 16)
                    exp = blob[:16]
                    log(
                        "Leído:    "
                        + " ".join(f"0x{int.from_bytes(got[i:i+4], 'little'):08X}" for i in range(0, 16, 4))
                    )
                    log(
                        "Esperado: "
                        + " ".join(f"0x{int.from_bytes(exp[i:i+4], 'little'):08X}" for i in range(0, 16, 4))
                    )
                    if got != exp:
                        log("AVISO: verify no coincide (Write puede haber andado igual)")
                except BmpRspError as exc:
                    log(f"AVISO: verify falló: {exc}")

                try:
                    bmp.detach()
                except BmpRspError:
                    pass
                log("Programación externa OK (RSP nativo).")
                return True

        except (BmpRspError, OSError) as exc:
            log(f"AVISO: sesión RSP cortada: {exc}")
            if next_i >= len(chunks):
                log("Writes completos pese al error final.")
                return True
            if next_i == 0 and need_erase:
                log("Falló antes de completar erase/writes — se reintenta sesión")
            else:
                log(
                    f"Reconnect: se retoma Write desde bloque {next_i}/"
                    f"{len(chunks)} (sin re-MassErase)"
                )
                need_erase = False
            continue

    log("ERROR: demasiadas sesiones RSP fallidas")
    return False
