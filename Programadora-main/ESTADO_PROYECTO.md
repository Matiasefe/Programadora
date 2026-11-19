# ESTADO_PROYECTO

## Resumen Ejecutivo

Programadora basada en **STM32F103** (Blue Pill genérica o PCB propia UC55) con firmware **Black Magic Probe (BMP)**. Sirve para grabar/depurar destinos STM32 por SWD (F1…F7, H7, U5). La app PyQt5 (`app/`) orquesta GDB + BMP; para Riverdi con assets en QSPI/OSPI ejecuta el `.stldr` en RAM del destino vía trampolín BKPT (sin CubeProgrammer).

## Avances Recientes

- Firmware BMP: `firmware/bluepill-bmp/` y `firmware/placa-propia-bmp/` (PB13/PB14/PB5).
- Flash interna U5 verificada en `app/Error.txt` (OK).
- STLDR runner v9 + fix logging GDB 14 (`redirect`).
- Programación Riverdi OK (era HEX/proyecto incorrecto).
- **Run after programming:** checkbox (default on) → `monitor reset` + liberar halt (DHCSR) + detach.

## Siguiente Paso / Tareas Pendientes

1. **Reprobar** Riverdi U5 con runner v7 — debe verse `STLDR_RUNNER_VERSION=7` y mensajes `>>> CALL` / `RET_Init` en vivos.
2. Si Fase 1 Init timeout 120s: trampolín/SWD no ejecuta el loader.
3. Validar Riverdi H7 (loader en `0x2400…`).
4. Confirmar en PCB si `PRESET` está aislado del NRST del F103 (`docs/04`).

## Decisiones Técnicas

| Tema | Decisión |
| --- | --- |
| Protocolo sonda | BMP (GDB extended-remote), no ST-Link |
| Externa QSPI/OSPI | `.stldr` en RAM + `tbreak` trampolín (runner v7) |
| Erase | Preferir `SectorErase(min,max)` del HEX; MassErase solo si no hay SectorErase |
| Stack en `0x2000…` | Tope ≤ `0x20020000` (seguro DTCM H7 y U5) |
| Stack en `0x2400…` | `0x24080000` (AXI H7) |
| Chunks Write | 4 KiB; lotes de 64 por sesión GDB |
| Deps | PyQt5, pyserial, pyelftools, intelhex |
| GDB | `arm-none-eabi-gdb` (CubeIDE / GNU Arm) |

### Firmwares (no mezclar)

| Hardware | Binario | SWDIO | SWCLK | NRST |
| --- | --- | --- | --- | --- |
| Blue Pill | `firmware/bluepill-bmp/*_all.bin` | PB14 | PA5 | PB1 |
| PCB propia | `firmware/placa-propia-bmp/*_all.bin` | PB14 | PB13 | PB5 |
