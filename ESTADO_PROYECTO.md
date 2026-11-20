# ESTADO_PROYECTO

## Resumen

Programadora **STM32F103** + **Black Magic Probe** + app PyQt5.  
Programa flash interna F1…H7/U5 y Riverdi con `.stldr` (QSPI/OSPI) **sin** CubeProgrammer.

## Logrado

- Riverdi (U5) programada OK (HEX correcto del proyecto + runner STLDR v9).
- Flash interna U5 verificada.
- Firmware Blue Pill y PCB propia (PB13/PB14/PB5) en `firmware/`.
- Repo reorganizado en la **raíz** (sin carpeta `Programadora-main/`).
- Flasher F4: `connect_rst`, erase en sesión aparte, verify post-load.
- Fix run-after: SP/PC **antes** de `monitor reset` (BMP desconecta al pulsar NRST).
- Fix falso AVISO erase (no confundir con “timeout to wait for device halts”).
- STLDR v10: timeout MassErase escalado (~60 MB ya no corta a 20 min); SectorErase por lotes.
- GUI: SWD (default 2 MHz), **Tamaño Write** 4/8/16 KiB (default 8), pausa entre lotes.
- STLDR **v16**: host RSP nativo (`bmp_rsp.py`) sin gdb.exe — 1 sesión, Init 1×, Write streaming; fallback GDB.

## Flasheo F4 (checklist si falla)

1. Campo **`.stldr` vacío** (solo Riverdi).
2. `.hex`/`.elf` del proyecto **F4** (Clean + Build, fecha actual).
3. Cables: **SWDIO, SWCLK, GND, NRST** + alimentación 3.3 V del F4.
4. Firmware de sonda acorde al hardware (Blue Pill ≠ PCB propia).
5. En el log: `Target detectado: STM32F4…` y `Post-load @0x08000000` ≠ `FFFFFFFF`.
6. Si `erase_mass` da *packet error*: desmarcar «Borrar flash» y reintentar; power-cycle del destino.

## Pendiente

- Validar Riverdi H7 (loader en AXI `0x2400…`).
- Confirmar en PCB si `PRESET` está aislado del NRST del F103.
- Confirmación del usuario con log F4 tras este flasher.
