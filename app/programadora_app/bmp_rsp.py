"""Cliente GDB Remote Serial Protocol (RSP) sobre el COM de Black Magic.

Evita lanzar arm-none-eabi-gdb.exe: habla en binario/hex con la sonda.
Usado para programar .stldr en una sola sesión (attach + Init + Writes).
"""

from __future__ import annotations

import struct
import time
from typing import Callable

LogFn = Callable[[str], None]


class BmpRspError(RuntimeError):
    pass


def _checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def _escape_binary(data: bytes) -> bytes:
    out = bytearray()
    for b in data:
        if b in (0x7D, 0x23, 0x24, 0x2A):  # } # $ *
            out.append(0x7D)
            out.append(b ^ 0x20)
        else:
            out.append(b)
    return bytes(out)


class BmpRsp:
    """Sesión RSP extended-remote contra Black Magic Probe."""

    def __init__(
        self,
        port: str,
        log: LogFn | None = None,
        timeout_s: float = 5.0,
    ):
        import serial

        self.log = log or (lambda _m: None)
        self._timeout_s = timeout_s
        dev = port
        if dev.startswith("\\\\.\\"):
            dev = dev[4:]
        self._ser = serial.Serial(
            port=dev,
            baudrate=115200,
            timeout=0.05,
            write_timeout=5.0,
        )
        # Vaciar basura de sesiones anteriores
        time.sleep(0.05)
        self._ser.reset_input_buffer()
        self._no_ack = False

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:  # noqa: BLE001
            pass

    def __enter__(self) -> BmpRsp:
        return self

    def __exit__(self, *args) -> None:
        self.close()

    # --- framing ---
    def _send_raw(self, packet: bytes) -> None:
        self._ser.write(packet)
        self._ser.flush()

    def _read_ack(self, timeout_s: float | None = None) -> None:
        if self._no_ack:
            return
        deadline = time.monotonic() + (timeout_s or self._timeout_s)
        while time.monotonic() < deadline:
            b = self._ser.read(1)
            if not b:
                continue
            if b == b"+":
                return
            if b == b"-":
                raise BmpRspError("NACK del stub BMP")
            # ignorar basura / notificaciones
        raise BmpRspError("Timeout esperando ACK RSP")

    def _recv_packet(self, timeout_s: float | None = None) -> bytes:
        deadline = time.monotonic() + (timeout_s or self._timeout_s)
        buf = bytearray()
        while time.monotonic() < deadline:
            chunk = self._ser.read(256)
            if chunk:
                buf.extend(chunk)
                # buscar $...#CC
                while True:
                    start = buf.find(b"$")
                    if start < 0:
                        buf.clear()
                        break
                    if start > 0:
                        del buf[:start]
                    hash_i = buf.find(b"#", 1)
                    if hash_i < 0 or len(buf) < hash_i + 3:
                        break
                    body = bytes(buf[1:hash_i])
                    csum_s = bytes(buf[hash_i + 1 : hash_i + 3])
                    del buf[: hash_i + 3]
                    try:
                        got = int(csum_s, 16)
                    except ValueError as exc:
                        raise BmpRspError(f"Checksum inválido: {csum_s!r}") from exc
                    if got != _checksum(body):
                        if not self._no_ack:
                            self._send_raw(b"-")
                        raise BmpRspError("Checksum RSP incorrecto")
                    if not self._no_ack:
                        self._send_raw(b"+")
                    return body
            else:
                time.sleep(0.005)
        raise BmpRspError("Timeout esperando paquete RSP")

    def cmd(self, payload: str | bytes, timeout_s: float | None = None) -> bytes:
        if isinstance(payload, str):
            body = payload.encode("ascii")
        else:
            body = payload
        pkt = b"$" + body + b"#%02x" % _checksum(body)
        last_err: Exception | None = None
        for _try in range(3):
            try:
                self._send_raw(pkt)
                self._read_ack(timeout_s=min(2.0, timeout_s or self._timeout_s))
                return self._recv_packet(timeout_s=timeout_s)
            except BmpRspError as exc:
                last_err = exc
                time.sleep(0.05)
        assert last_err is not None
        raise last_err

    def cmd_ok(self, payload: str, timeout_s: float | None = None) -> None:
        r = self.cmd(payload, timeout_s=timeout_s)
        if r != b"OK" and not r.startswith(b"OK"):
            # algunos stubs OK vacío en éxito de Z
            if r == b"":
                return
            raise BmpRspError(f"RSP '{payload[:40]}' → {r[:80]!r}")

    # --- high level ---
    def handshake(self) -> None:
        # Despertar stub
        self._send_raw(b"+")
        time.sleep(0.02)
        self._ser.reset_input_buffer()
        # qSupported
        try:
            self.cmd("qSupported:multiprocess+;swbreak+;hwbreak+;PacketSize=1024", timeout_s=3.0)
        except BmpRspError:
            self.cmd("qSupported", timeout_s=3.0)
        # extended mode
        r = self.cmd("!", timeout_s=3.0)
        if r not in (b"OK", b""):
            # algunos firmwares responden OK
            pass
        try:
            self.cmd_ok("QStartNoAckMode")
            self._no_ack = True
            # tras OK de noack, el siguiente + puede omitirse
        except BmpRspError:
            self._no_ack = False

    def monitor(self, command: str, timeout_s: float = 10.0) -> str:
        hx = command.encode("utf-8").hex()
        r = self.cmd(f"qRcmd,{hx}", timeout_s=timeout_s)
        if r == b"OK" or r == b"":
            return ""
        # respuesta hex-encoded text
        try:
            return bytes.fromhex(r.decode("ascii")).decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            return r.decode("latin-1", errors="replace")

    def swdp_scan(self) -> str:
        return self.monitor("swdp_scan", timeout_s=15.0)

    def set_frequency(self, hz: int) -> str:
        return self.monitor(f"frequency {int(hz)}", timeout_s=5.0)

    def connect_rst(self, enable: bool = True) -> str:
        return self.monitor(
            "connect_rst enable" if enable else "connect_rst disable",
            timeout_s=5.0,
        )

    def halt(self) -> str:
        return self.monitor("halt", timeout_s=5.0)

    def attach(self, index: int = 1) -> bytes:
        # vAttach;1 → stop reply
        r = self.cmd(f"vAttach;{index}", timeout_s=10.0)
        if r.startswith(b"E") or r == b"":
            raise BmpRspError(f"vAttach falló: {r!r}")
        return r

    def detach(self) -> None:
        try:
            self.cmd("D", timeout_s=3.0)
        except BmpRspError:
            pass

    def mem_write(self, addr: int, data: bytes, timeout_s: float = 10.0) -> None:
        """Escribe memoria en bloques (paquete X binario o M hex)."""
        # PacketSize típico ~1 KiB; dejar margen
        max_chunk = 512
        off = 0
        while off < len(data):
            piece = data[off : off + max_chunk]
            a = addr + off
            # Preferir X (binario)
            escaped = _escape_binary(piece)
            payload = b"X%x,%x:" % (a, len(piece)) + escaped
            try:
                r = self.cmd(payload, timeout_s=timeout_s)
                if r != b"OK":
                    raise BmpRspError(f"X write @0x{a:08X}: {r!r}")
            except BmpRspError:
                # fallback M hex
                hx = piece.hex()
                r = self.cmd(f"M{a:x},{len(piece):x}:{hx}", timeout_s=timeout_s)
                if r != b"OK":
                    raise BmpRspError(f"M write @0x{a:08X}: {r!r}")
            off += len(piece)

    def mem_read(self, addr: int, length: int, timeout_s: float = 10.0) -> bytes:
        out = bytearray()
        left = length
        a = addr
        while left > 0:
            n = min(left, 256)
            r = self.cmd(f"m{a:x},{n:x}", timeout_s=timeout_s)
            if r.startswith(b"E"):
                raise BmpRspError(f"m read @0x{a:08X}: {r!r}")
            out.extend(bytes.fromhex(r.decode("ascii")))
            a += n
            left -= n
        return bytes(out)

    def set_reg32(self, regno: int, value: int) -> None:
        le = struct.pack("<I", value & 0xFFFFFFFF).hex()
        r = self.cmd(f"P{regno:x}={le}", timeout_s=3.0)
        if r != b"OK":
            raise BmpRspError(f"P set reg {regno}: {r!r}")

    def get_reg32(self, regno: int) -> int:
        r = self.cmd(f"p{regno:x}", timeout_s=3.0)
        if r.startswith(b"E") or r == b"xx":
            raise BmpRspError(f"p get reg {regno}: {r!r}")
        raw = bytes.fromhex(r.decode("ascii"))
        if len(raw) < 4:
            raw = raw.ljust(4, b"\x00")
        return struct.unpack("<I", raw[:4])[0]

    def insert_sw_break(self, addr: int, kind: int = 2) -> None:
        r = self.cmd(f"Z0,{addr:x},{kind:x}", timeout_s=3.0)
        if r not in (b"OK", b""):
            raise BmpRspError(f"Z0 break @0x{addr:08X}: {r!r}")

    def remove_sw_break(self, addr: int, kind: int = 2) -> None:
        try:
            self.cmd(f"z0,{addr:x},{kind:x}", timeout_s=3.0)
        except BmpRspError:
            pass

    def continue_until_break(self, timeout_s: float) -> bytes:
        """Continue y espera stop reply (breakpoint / signal)."""
        # Enviar continue sin esperar stop en el mismo cmd helper:
        body = b"c"
        pkt = b"$" + body + b"#%02x" % _checksum(body)
        self._send_raw(pkt)
        if not self._no_ack:
            self._read_ack(timeout_s=2.0)
        # Stop reply puede tardar (MassErase, Write NOR)
        return self._recv_packet(timeout_s=timeout_s)

    def call_thumb(
        self,
        *,
        func: int,
        trampoline: int,
        stack: int,
        r0: int = 0,
        r1: int = 0,
        r2: int = 0,
        timeout_s: float = 120.0,
        label: str = "",
    ) -> int:
        """Invoca función Thumb; retorno vía breakpoint en trampoline (LR)."""
        if label:
            self.log(f">>> CALL {label} (RSP nativo)…")
        # breakpoint software en dirección de retorno
        self.insert_sw_break(trampoline & ~1, 2)
        # regs ARM: 0=r0 … 13=sp 14=lr 15=pc 16=xpsr
        self.set_reg32(0, r0)
        self.set_reg32(1, r1)
        self.set_reg32(2, r2)
        self.set_reg32(13, stack)
        self.set_reg32(14, trampoline | 1)
        self.set_reg32(16, 0x01000000)  # Thumb EPSR.T
        self.set_reg32(15, func | 1)
        stop = self.continue_until_break(timeout_s=timeout_s)
        if stop.startswith(b"W") or stop.startswith(b"X"):
            raise BmpRspError(f"Target salió: {stop!r}")
        if stop.startswith(b"E"):
            raise BmpRspError(f"Error en continue: {stop!r}")
        # leer r0
        ret = self.get_reg32(0)
        if label:
            self.log(f"RET_{label} 0x{ret:x}")
        return ret
