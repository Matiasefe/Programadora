"""Detección de la sonda Black Magic Probe."""

from __future__ import annotations

from dataclasses import dataclass

BMP_VID = 0x1D50
BMP_PIDS = {0x6017, 0x6018, 0x6019}


@dataclass
class SerialPortInfo:
    device: str
    description: str
    vid: int | None
    pid: int | None
    interface: str
    is_bmp: bool
    is_gdb: bool


def list_ports() -> list[SerialPortInfo]:
    from serial.tools import list_ports

    out: list[SerialPortInfo] = []
    for p in list_ports.comports():
        desc = p.description or ""
        iface = getattr(p, "interface", None) or ""
        blob = f"{desc} {iface}".lower()
        is_bmp = (
            (p.vid == BMP_VID and (p.pid in BMP_PIDS if p.pid is not None else False))
            or "black magic" in blob
        )
        is_gdb = is_bmp and ("gdb" in blob or "gdb server" in blob)
        out.append(
            SerialPortInfo(
                device=p.device,
                description=desc,
                vid=p.vid,
                pid=p.pid,
                interface=iface,
                is_bmp=is_bmp,
                is_gdb=is_gdb,
            )
        )
    return out


def pick_gdb_port(ports: list[SerialPortInfo] | None = None) -> str | None:
    ports = ports if ports is not None else list_ports()
    bmps = [p for p in ports if p.is_bmp]
    for p in bmps:
        if p.is_gdb:
            return p.device
    if len(bmps) >= 1:
        # En Windows suele ser el COM de número más bajo el GDB
        return sorted(bmps, key=lambda x: x.device)[0].device
    return None


def normalize_port(port: str) -> str:
    import os

    p = port.strip()
    if os.name == "nt":
        if p.startswith("\\\\.\\"):
            p = p[4:]
        up = p.upper()
        if up.startswith("COM") and up[3:].isdigit():
            return "\\\\.\\" + up
    return p
