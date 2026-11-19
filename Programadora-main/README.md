# blue-link

Convertir una **STM32F103C8T6 Blue Pill** en programadora/depuradora abierta con **Black Magic Probe**, para grabar el `.elf` / `.hex` que genera CubeIDE en otro STM32.

> STM32CubeProgrammer **no** va a reconocer esta sonda como ST-Link. Se usa **GDB** (y opcionalmente OpenOCD no es necesario con BMP).

## Plan del proyecto

1. **Ahora:** grabar Black Magic en la Blue Pill con el **pinout por defecto**.
2. **Después:** personalizar pines SWD y recompilar el `.bin` — guía en [`docs/03-cambiar-pines.md`](docs/03-cambiar-pines.md) (no es un proyecto CubeIDE; es Meson + fuentes Black Magic).
3. Luego: flujo diario (CubeIDE → `.hex`/`.elf` → `scripts/bmp_flash.py`).

## Firmwares (no mezclar placas)

| Hardware | Carpeta | SWDIO | SWCLK | NRST | LED |
| --- | --- | --- | --- | --- | --- |
| Blue Pill genérica | `firmware/bluepill-bmp/` | PB14 | PA5 | PB1 | PC13 |
| **Tu PCB F103CB (UC55)** | `firmware/placa-propia-bmp/` | PB14 | **PB13** | **PB5** | **PA9** |

Doc de tu esquemático (F4/H7/U5): [`docs/04-placa-propia-pinout.md`](docs/04-placa-propia-pinout.md).

### Conexión a F4 / H7 / U5 (placa propia)

```text
Programadora                 Destino STM32
------------                 -------------
SWDIO (PB14) --------------> SWDIO
SWCLK (PB13) --------------> SWCLK
RESET (PB5)  --------------> NRST
GND          --------------> GND
(SWIM no se usa)
```

Todo a **3,3 V**. Binario: `firmware/placa-propia-bmp/blackmagic_placa_propia_all.bin` @ `0x08000000`.

## Qué hay en este repo

| Ruta | Contenido |
| --- | --- |
| `firmware/bluepill-bmp/` | Binarios Blue Pill genérica |
| `firmware/placa-propia-bmp/` | Binarios para tu PCB (PB13/PB14/PB5) |
| `docs/01-convertir-blue-pill.md` | Primer flasheo |
| `docs/02-usar-como-programadora.md` | Cargar `.hex` / `.elf` |
| `docs/03-cambiar-pines.md` | Cómo recompilar con otros pines |
| `docs/04-placa-propia-pinout.md` | Pinout de tu esquemático |
| `docs/05-riverdi-stldr-flash-externa.md` | Riverdi 5″/10″, QSPI/OSPI y `.stldr` |
| `docs/06-app-pyqt.md` | App PyQt5 (detectar sonda + programar) |
| `app/` | GUI Programadora (PyQt5) |
| `scripts/bmp_flash.py` | Flasheo CLI por la programadora |
| `driver/` | Reglas udev (Linux) |

## Empezar

Seguí **[`docs/01-convertir-blue-pill.md`](docs/01-convertir-blue-pill.md)**.

Resumen:

1. USB–serie a PA9/PA10, BOOT0=1 (o ST-Link por SWD).
2. Grabar `blackmagic_bluepill_all.bin` en `0x08000000`.
3. BOOT0=0, conectar USB de la Blue Pill.
4. Deben aparecer dos puertos CDC (GDB + UART).
5. Cablear PB14/PA5/PB1/GND a un STM32 de prueba y hacer `monitor swdp_scan`.

## App PyQt5 (recomendado en Windows)

```bat
cd Programadora
pip install -r requirements.txt
cd app
python run_programadora.py
```

Detecta la sonda, elige `.hex` y opcionalmente `.stldr` (Riverdi). Guía: [`docs/06-app-pyqt.md`](docs/06-app-pyqt.md).

## CLI (sin GUI)

```bash
pip install -r requirements.txt
python scripts/bmp_flash.py ruta/al/firmware.hex --port COM30
```

Hace falta `arm-none-eabi-gdb` (CubeIDE / GNU Arm).

## Licencia del firmware

Black Magic Debug es software libre (GPL/BSD/MIT según componentes). Fuentes: [codeberg.org/blackmagic-debug/blackmagic](https://codeberg.org/blackmagic-debug/blackmagic). Ver `firmware/bluepill-bmp/SOURCE.txt` para el commit usado en estos binarios.
