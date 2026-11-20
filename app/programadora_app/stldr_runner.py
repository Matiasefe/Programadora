"""
Ejecutar un External Loader (.stldr) sobre el destino vía GDB + BMP.

El .stldr es un ELF con código en RAM. GDB `call` falla en remoto BMP, así que
se invocan Init/Write/Erase con LR→breakpoint + PC Thumb + `continue`.

Salida en vivo: GDB logging a archivo + heartbeat (si no, parece colgado).
"""

from __future__ import annotations

import subprocess
import tempfile
import time
from pathlib import Path
from typing import Callable

LogFn = Callable[[str], None]

STLDR_RUNNER_VERSION = 14
# NOR: borrar sector a sector del rango HEX (4 KiB típico MX25)
SECTOR_ERASE_STEP = 0x1000

# Tamaño de cada Write() al .stldr (scratch en RAM del destino).
CHUNK_SIZE_DEFAULT = 8192
CHUNK_SIZE_CHOICES = (4096, 8192, 16384)
RAM_MIN = 0x20000000
# Lotes chicos: con 64, Riverdi ~18 MB cortaba USB a mitad de sesión
# ("Remote connection closed"). 16 = más reconnects, más estable.
WRITE_BATCH = 16
WRITE_BATCH_RETRIES = 4
# Delay solo entre lotes (no entre cada Write): estabilidad USB sin frenar tanto.
WRITE_BATCH_PAUSE_S = 0.75
# SectorErase por sesión GDB (imágenes grandes: no meter 15k continues en un script)
SECTOR_ERASE_BATCH = 128
# Tope SWD medido en la sonda F103 (BMP clampa 8→6 MHz)
MAX_SWD_FREQ_HZ = 6_000_000
DEFAULT_SWD_FREQ_HZ = 2_000_000


def _clamp_chunk_size(n: int) -> int:
    n = int(n)
    if n in CHUNK_SIZE_CHOICES:
        return n
    # redondear al choice más cercano
    return min(CHUNK_SIZE_CHOICES, key=lambda c: abs(c - n))


def _fmt_bytes(n: int) -> str:
    if n >= 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    if n >= 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n} B"


def _mass_erase_timeout_s(ext_bytes: int) -> int:
    """Timeout MassErase vía .stldr/SWD.

    En Riverdi ~60 MB el chip erase puede superar 20 min; el límite fijo
    de 1200s mataba GDB mientras todavía borraba.
    """
    mb = max(1.0, ext_bytes / (1024 * 1024))
    # piso 45 min; ~2 min/MB de margen; techo 3 h
    return int(min(3 * 3600, max(45 * 60, mb * 120)))


def _sector_erase_timeout_s(nsec: int) -> int:
    # ~2–8 s/sector vía trampolín; piso 10 min; techo 3 h por sesión
    return int(min(3 * 3600, max(600, nsec * 8)))


def _posix(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/")


def _thumb(addr: int) -> int:
    return int(addr) | 1


def _align_up(addr: int, align: int) -> int:
    return (addr + align - 1) & ~(align - 1)


def _write_gdb_script(path: Path, lines: list[str]) -> None:
    text = "\n".join(lines) + "\n"
    with path.open("w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def _elf_info(stldr: Path) -> dict:
    from elftools.elf.elffile import ELFFile

    info: dict = {"segments": [], "symbols": {}, "entry": None}
    with stldr.open("rb") as f:
        elf = ELFFile(f)
        info["entry"] = elf.header["e_entry"]
        for seg in elf.iter_segments():
            if seg["p_type"] != "PT_LOAD" or seg["p_filesz"] == 0:
                continue
            info["segments"].append(
                {
                    "vaddr": int(seg["p_vaddr"]),
                    "filesz": int(seg["p_filesz"]),
                    "data": bytes(seg.data()),
                }
            )
        symtab = elf.get_section_by_name(".symtab")
        if symtab is not None:
            for sym in symtab.iter_symbols():
                name = sym.name
                if name in {
                    "Init",
                    "Write",
                    "Read",
                    "SectorErase",
                    "MassErase",
                    "CheckSum",
                    "StorageInfo",
                }:
                    info["symbols"][name] = int(sym["st_value"])
    return info


def _pick_ram_layout(
    ram_segs: list[dict], chunk_size: int = CHUNK_SIZE_DEFAULT
) -> tuple[int, int, int]:
    """scratch, trampoline (halfword), stack — por encima del loader."""
    chunk_size = _clamp_chunk_size(chunk_size)
    base = min(int(s["vaddr"]) for s in ram_segs)
    end = max(int(s["vaddr"]) + int(s["filesz"]) for s in ram_segs)
    end = _align_up(end, 16)

    scratch = _align_up(end + 0x100, 32)
    trampoline = _align_up(scratch + chunk_size + 0x40, 2)
    stack = _align_up(trampoline + 0x4000, 8)

    if 0x24000000 <= base < 0x25000000:
        stack = max(stack, 0x24080000)
    elif 0x20000000 <= base < 0x24000000:
        dtcm_top = 0x20020000
        if trampoline + 0x1000 < dtcm_top:
            stack = max(stack, trampoline + 0x4000)
            stack = min(_align_up(stack, 8), dtcm_top)
        else:
            stack = max(stack, 0x20080000)

    return scratch, trampoline, stack


def _append_call(
    lines: list[str],
    *,
    func: int,
    trampoline: int,
    stack: int,
    label: str,
    r0: int | None = None,
    r1: int | None = None,
    r2: int | None = None,
) -> None:
    """Invocar Thumb en RAM: breakpoint en trampolín + continue."""
    lines.append(f'echo >>> CALL {label} (esperando retorno)...')
    # Breakpoint de GDB en la dirección de retorno (más fiable que BKPT solo)
    lines.append("delete breakpoints")
    lines.append(f"tbreak *0x{trampoline:X}")
    if r0 is not None:
        lines.append(f"set $r0 = 0x{int(r0):X}")
    if r1 is not None:
        lines.append(f"set $r1 = 0x{int(r1):X}")
    if r2 is not None:
        lines.append(f"set $r2 = 0x{int(r2):X}")
    lines.append(f"set $sp = 0x{stack:X}")
    lines.append(f"set $lr = 0x{_thumb(trampoline):X}")
    lines.append("set $xpsr = 0x01000000")
    lines.append(f"set $pc = 0x{_thumb(func):X}")
    lines.append("continue")
    lines.append(f'printf "RET_{label} 0x%x\\n", $r0')


def _session_preamble(
    tmp: Path,
    port: str,
    restore_ram: list[str],
    log_name: str,
    remotetimeout: int = 600,
    swd_freq_hz: int = DEFAULT_SWD_FREQ_HZ,
) -> list[str]:
    # GDB reciente: "set logging redirect on" + "enabled on"
    # (NO "redirected" — falla en gnu-tools 14.x / CubeIDE 2.x)
    rt = max(600, int(remotetimeout))
    hz = max(100_000, min(int(swd_freq_hz), MAX_SWD_FREQ_HZ))
    return [
        "set confirm off",
        "set pagination off",
        f"set remotetimeout {rt}",
        f"set logging file {_posix(tmp / log_name)}",
        "set logging overwrite on",
        "set logging redirect on",
        "set logging enabled on",
        f"cd {_posix(tmp)}",
        f'echo >>> conectando {port}',
        f"target extended-remote {port}",
        f"monitor frequency {hz}",
        "monitor swdp_scan",
        "attach 1",
        "monitor halt",
        *restore_ram,
        'echo >>> loader en RAM OK',
    ]


def program_external(
    gdb: str,
    port: str,
    stldr: Path,
    external_hex: Path,
    log: LogFn,
    swd_freq_hz: int = DEFAULT_SWD_FREQ_HZ,
    chunk_size: int = CHUNK_SIZE_DEFAULT,
    batch_pause_s: float = WRITE_BATCH_PAUSE_S,
) -> bool:
    from intelhex import IntelHex

    stldr = stldr.resolve()
    external_hex = external_hex.resolve()
    swd_freq_hz = max(100_000, min(int(swd_freq_hz), MAX_SWD_FREQ_HZ))
    chunk_size = _clamp_chunk_size(chunk_size)
    batch_pause_s = max(0.0, float(batch_pause_s))

    log(
        f"STLDR_RUNNER_VERSION={STLDR_RUNNER_VERSION} "
        f"(SWD {swd_freq_hz} Hz, chunk {chunk_size} B, "
        f"pause lote {batch_pause_s:.2f}s)"
    )
    info = _elf_info(stldr)
    log(f"STLDR entry=0x{info['entry']:08X}" if info["entry"] else "STLDR sin entry")
    for name, addr in sorted(info["symbols"].items()):
        log(f"  símbolo {name} @ 0x{addr:08X}")

    if "Write" not in info["symbols"]:
        log("ERROR: el .stldr no exporta Write().")
        return False

    ram_segs = [s for s in info["segments"] if s["vaddr"] >= RAM_MIN]
    skipped = [s for s in info["segments"] if s["vaddr"] < RAM_MIN]
    for s in skipped:
        log(f"  omitido seg lma=0x{s['vaddr']:08X} size={s['filesz']} (no es RAM)")
    if not ram_segs:
        log("ERROR: no hay segmentos PT_LOAD en RAM.")
        return False

    scratch, trampoline, stack_addr = _pick_ram_layout(ram_segs, chunk_size)
    log(
        f"Layout RAM: scratch=0x{scratch:08X} (+{chunk_size} B) "
        f"trampoline=0x{trampoline:08X} sp=0x{stack_addr:08X}"
    )

    tmp = Path(tempfile.mkdtemp(prefix="stldr_"))
    log(f"Temp: {tmp}")

    restore_ram: list[str] = []
    for i, seg in enumerate(ram_segs):
        name = f"seg{i}.bin"
        (tmp / name).write_bytes(seg["data"])
        restore_ram.append(f"restore {name} binary 0x{seg['vaddr']:X}")
        log(f"  seg RAM {i}: {seg['filesz']} bytes → 0x{seg['vaddr']:08X} ({name})")

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
        f"(span {total} = {_fmt_bytes(total)})"
    )
    if total >= 16 * 1024 * 1024:
        log(
            "AVISO: imagen externa grande — Erase/Write pueden tardar "
            "decenas de minutos. No canceles mientras diga «GDB sigue»."
        )

    log("Generando imagen binaria…")
    blob = bytes(ih.tobinarray(start=min_a, size=total))

    chunks_dir = tmp / "chunks"
    chunks_dir.mkdir()
    chunk_files: list[tuple[int, str, int]] = []
    offset = 0
    idx = 0
    log(f"Partiendo en bloques de {chunk_size} B…")
    while offset < len(blob):
        piece = blob[offset : offset + chunk_size]
        rel = f"chunks/c{idx:05d}.bin"
        (tmp / rel).write_bytes(piece)
        chunk_files.append((min_a + offset, rel, len(piece)))
        idx += 1
        offset += chunk_size
        if idx == 1 or idx % 64 == 0 or offset >= len(blob):
            log(f"  preparados {idx} bloques ({min(offset, len(blob))}/{len(blob)})")

    log(f"Total Write: {len(chunk_files)}")

    init_addr = info["symbols"].get("Init", info["entry"])
    write_addr = info["symbols"]["Write"]
    mass_addr = info["symbols"].get("MassErase")
    sector_addr = info["symbols"].get("SectorErase")

    if init_addr is None:
        log("ERROR: no hay Init ni entry en el .stldr.")
        return False

    # --- Fase 1: solo Init (fail-fast si el trampolín no vuelve) ---
    log("=== Fase 1/4: Init (timeout 120s) ===")
    lines = _session_preamble(
        tmp, port, restore_ram, "gdb_init.log", swd_freq_hz=swd_freq_hz
    )
    _append_call(
        lines,
        func=int(init_addr),
        trampoline=trampoline,
        stack=stack_addr,
        label="Init",
    )
    lines.extend(["detach", "quit"])
    script = tmp / "phase_init.gdb"
    _write_gdb_script(script, lines)
    if not _run_gdb_live(
        gdb, script, cwd=tmp, log_name="gdb_init.log", log=log, timeout_s=120
    ):
        log(
            "ERROR: Init no volvió a tiempo. "
            "La sonda/trampolín no está ejecutando el .stldr (o HardFault)."
        )
        return False
    log("Init OK — seguimos")

    # --- Fase 2: Init + erase fiable del rango ---
    # Un solo SectorErase(min,max) a veces no borra todo el rango en estos
    # loaders → Write “OK” pero datos corruptos → pantalla negra.
    log("=== Fase 2/4: Erase ===")
    if mass_addr is not None:
        erase_timeout = _mass_erase_timeout_s(len(blob))
        log(
            f"MassErase() del chip OSPI/QSPI — timeout {erase_timeout}s "
            f"(~{erase_timeout // 60} min) para {_fmt_bytes(len(blob))}. "
            "No canceles; el heartbeat «GDB sigue» es normal."
        )
        lines = _session_preamble(
            tmp,
            port,
            restore_ram,
            "gdb_erase.log",
            remotetimeout=erase_timeout,
            swd_freq_hz=swd_freq_hz,
        )
        _append_call(
            lines,
            func=int(init_addr),
            trampoline=trampoline,
            stack=stack_addr,
            label="Init",
        )
        _append_call(
            lines,
            func=int(mass_addr),
            trampoline=trampoline,
            stack=stack_addr,
            label="MassErase",
        )
        lines.extend(["detach", "quit"])
        script = tmp / "phase_erase.gdb"
        _write_gdb_script(script, lines)
        if not _run_gdb_live(
            gdb,
            script,
            cwd=tmp,
            log_name="gdb_erase.log",
            log=log,
            timeout_s=erase_timeout,
        ):
            log("ERROR en fase Erase (MassErase)")
            return False
    elif sector_addr is not None:
        # Imágenes grandes: varios scripts GDB (evita un continue×15k)
        sectors: list[tuple[int, int]] = []
        a = min_a & ~(SECTOR_ERASE_STEP - 1)
        while a <= max_a:
            end_a = min(a + SECTOR_ERASE_STEP - 1, max_a)
            sectors.append((a, end_a))
            a += SECTOR_ERASE_STEP
        log(
            f"SectorErase ×{len(sectors)} (paso 0x{SECTOR_ERASE_STEP:X}) "
            f"0x{sectors[0][0]:X}..0x{max_a:X} en lotes de {SECTOR_ERASE_BATCH}"
        )
        n_sec_batches = (len(sectors) + SECTOR_ERASE_BATCH - 1) // SECTOR_ERASE_BATCH
        for sb in range(0, len(sectors), SECTOR_ERASE_BATCH):
            batch = sectors[sb : sb + SECTOR_ERASE_BATCH]
            batch_i = sb // SECTOR_ERASE_BATCH + 1
            erase_timeout = _sector_erase_timeout_s(len(batch))
            log_name = f"gdb_erase_{batch_i:03d}.log"
            log(
                f"--- Erase lote {batch_i}/{n_sec_batches}: "
                f"{len(batch)} sectores (timeout {erase_timeout}s) ---"
            )
            lines = _session_preamble(
                tmp,
                port,
                restore_ram,
                log_name,
                remotetimeout=erase_timeout,
                swd_freq_hz=swd_freq_hz,
            )
            _append_call(
                lines,
                func=int(init_addr),
                trampoline=trampoline,
                stack=stack_addr,
                label="Init",
            )
            for j, (sa, ea) in enumerate(batch):
                global_i = sb + j
                _append_call(
                    lines,
                    func=int(sector_addr),
                    trampoline=trampoline,
                    stack=stack_addr,
                    label=f"Sec{global_i}",
                    r0=sa,
                    r1=ea,
                )
                if global_i % 16 == 0:
                    lines.append(f"echo ERASE_SEC {global_i}/{len(sectors)}")
            lines.extend(["detach", "quit"])
            script = tmp / f"phase_erase_{batch_i:03d}.gdb"
            _write_gdb_script(script, lines)
            if not _run_gdb_live(
                gdb,
                script,
                cwd=tmp,
                log_name=log_name,
                log=log,
                timeout_s=erase_timeout,
            ):
                log(f"ERROR en fase Erase lote {batch_i}/{n_sec_batches}")
                return False
    else:
        log("AVISO: sin erase en el loader — se intenta Write directo")
    log("Erase OK — seguimos")

    # --- Fase 3: Writes por lotes ---
    n_batches = (len(chunk_files) + WRITE_BATCH - 1) // WRITE_BATCH
    log(
        f"=== Fase 3/4: Write ({len(chunk_files)} bloques, "
        f"lotes de {WRITE_BATCH}, ~{n_batches} sesiones GDB) ==="
    )
    for batch_start in range(0, len(chunk_files), WRITE_BATCH):
        batch = chunk_files[batch_start : batch_start + WRITE_BATCH]
        batch_i = batch_start // WRITE_BATCH + 1
        log(
            f"--- Lote {batch_i}/{n_batches}: "
            f"bloques {batch_start}..{batch_start + len(batch) - 1} ---"
        )
        write_timeout = max(180, len(batch) * 25)
        ok = False
        for attempt in range(1, WRITE_BATCH_RETRIES + 1):
            log_name = f"gdb_write_{batch_i:03d}_a{attempt}.log"
            if attempt > 1:
                pause = 1.5 * attempt
                log(
                    f"Reintento {attempt}/{WRITE_BATCH_RETRIES} del lote "
                    f"{batch_i} (pausa {pause:.1f}s; típico tras "
                    "Remote connection closed)…"
                )
                time.sleep(pause)
            lines = _session_preamble(
                tmp,
                port,
                restore_ram,
                log_name,
                remotetimeout=write_timeout,
                swd_freq_hz=swd_freq_hz,
            )
            _append_call(
                lines,
                func=int(init_addr),
                trampoline=trampoline,
                stack=stack_addr,
                label="Init",
            )
            for j, (waddr, rel, size) in enumerate(batch):
                global_i = batch_start + j
                lines.append(f"restore {rel} binary 0x{scratch:X}")
                _append_call(
                    lines,
                    func=int(write_addr),
                    trampoline=trampoline,
                    stack=stack_addr,
                    label=f"W{global_i}",
                    r0=waddr,
                    r1=size,
                    r2=scratch,
                )
                if global_i % 8 == 0:
                    lines.append(f"echo PROG {global_i}/{len(chunk_files)}")
            lines.extend(["detach", "quit"])
            script = tmp / f"phase_write_{batch_i:03d}_a{attempt}.gdb"
            _write_gdb_script(script, lines)
            ok = _run_gdb_live(
                gdb,
                script,
                cwd=tmp,
                log_name=log_name,
                log=log,
                timeout_s=write_timeout,
            )
            if ok:
                break
        if not ok:
            log(f"ERROR en lote Write {batch_i}/{n_batches} tras reintentos")
            log(
                "«Remote connection closed» suele ser USB/SWD inestable en "
                "sesiones largas. Probá SWD 1–2 MHz en la GUI, cable corto, "
                "otro puerto USB; la flash interna puede haber quedado OK."
            )
            return False
        if batch_i < n_batches and batch_pause_s > 0:
            time.sleep(batch_pause_s)

    # --- Fase 4: verificar primeras palabras + reset para arrancar la app ---
    log("=== Fase 4/4: Verificar 0x90000000 + reset ===")
    expect = blob[:16]
    exp_words = [
        int.from_bytes(expect[i : i + 4], "little") for i in range(0, 16, 4)
    ]
    log(
        "Esperado @0x90000000: "
        + " ".join(f"0x{w:08X}" for w in exp_words)
    )
    lines = _session_preamble(
        tmp, port, restore_ram, "gdb_verify.log", swd_freq_hz=swd_freq_hz
    )
    _append_call(
        lines,
        func=int(init_addr),
        trampoline=trampoline,
        stack=stack_addr,
        label="Init",
    )
    # Tras Init el loader suele dejar el OSPI en memory-mapped
    lines.append("x/4xw 0x90000000")
    lines.append("detach")
    lines.append("quit")
    script = tmp / "phase_verify.gdb"
    _write_gdb_script(script, lines)
    if not _run_gdb_live(
        gdb, script, cwd=tmp, log_name="gdb_verify.log", log=log, timeout_s=180
    ):
        log("AVISO: verify falló; la Write puede haber andado igual")
    else:
        log(
            "Compará el 'x/4xw 0x90000000' de arriba con los bytes esperados. "
            "Si ves ffffffff o valores distintos, la externa no quedó bien."
        )

    log("Programación externa OK (GDB).")
    return True


def _run_gdb_live(
    gdb: str,
    script: Path,
    cwd: Path,
    log_name: str,
    log: LogFn,
    timeout_s: int,
) -> bool:
    """Lanza GDB y muestra gdb_*.log en vivo + heartbeat cada 10s."""
    log_path = cwd / log_name
    if log_path.exists():
        try:
            log_path.unlink()
        except OSError:
            pass

    args = [gdb, "-nx", "--batch", "--quiet", "-x", _posix(script)]
    log(
        f"Ejecutando: {script.name} (timeout {timeout_s}s / ~{timeout_s // 60} min) "
        "— mirá mensajes >>> / RET_"
    )
    start = time.monotonic()
    try:
        proc = subprocess.Popen(
            args,
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        log(f"ERROR al lanzar GDB: {exc}")
        return False

    pos = 0
    last_hb = start
    # Heartbeat más espaciado en operaciones largas (MassErase 60 MB, etc.)
    hb_every = 30.0 if timeout_s >= 900 else 10.0
    combined: list[str] = []

    while True:
        rc = proc.poll()
        if log_path.is_file():
            try:
                data = log_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                data = ""
            if len(data) > pos:
                chunk = data[pos:]
                pos = len(data)
                for ln in chunk.splitlines():
                    if ln.strip():
                        log(ln)
                        combined.append(ln)
        now = time.monotonic()
        if now - last_hb >= hb_every and rc is None:
            elapsed = int(now - start)
            left = max(0, timeout_s - elapsed)
            log(
                f"... GDB sigue ({elapsed}s, quedan ~{left}s) — "
                "Erase/Write largo es normal; no canceles"
            )
            last_hb = now
        if rc is not None:
            # drenar stdout por si logging falló
            try:
                rest = proc.stdout.read() if proc.stdout else ""
            except Exception:  # noqa: BLE001
                rest = ""
            if rest:
                for ln in rest.splitlines():
                    if ln.strip():
                        log(ln)
                        combined.append(ln)
            break
        if now - start > timeout_s:
            log(
                f"ERROR: timeout {timeout_s}s — matando GDB. "
                "Si era MassErase de imagen grande, reintentá (v10 sube el límite)."
            )
            proc.kill()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            return False
        time.sleep(0.2)

    if proc.returncode != 0:
        log(f"GDB código {proc.returncode}")
        return False

    joined = "\n".join(combined)
    if "HardFault" in joined or "fatal signal" in joined.lower():
        log("ERROR: HardFault / señal fatal en GDB")
        return False
    # Init/Erase/Write deben haber imprimido al menos un RET_
    if "RET_" not in joined and ">>> CALL" in joined:
        log("ERROR: no hubo RET_ — el continue no volvió del loader")
        return False
    return True
