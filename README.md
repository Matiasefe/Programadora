# Programadora

Programadora SWD basada en **STM32F103** + firmware **Black Magic Probe**, con app **PyQt5** para grabar STM32 (F1…F7, H7, U5) y pantallas **Riverdi** (HEX + `.stldr` en QSPI/OSPI) **sin** STM32CubeProgrammer.

Repo: https://github.com/Matiasefe/Programadora

## Arranque rápido (Windows)

```bat
git clone https://github.com/Matiasefe/Programadora.git
cd Programadora
pip install -r requirements.txt
cd app
python run_programadora.py
```

## Firmwares de la sonda (no mezclar)

| Hardware | Carpeta | SWDIO | SWCLK | NRST | LED |
| --- | --- | --- | --- | --- | --- |
| Blue Pill genérica | `firmware/bluepill-bmp/` | PB14 | PA5 | PB1 | PC13 |
| PCB propia (UC55) | `firmware/placa-propia-bmp/` | PB14 | **PB13** | **PB5** | **PA9** |

Grabar `*_all.bin` en `0x08000000`.

## Uso por tipo de destino

| Destino | Archivos | Notas |
| --- | --- | --- |
| F1 / F4 / F7 (flash interna) | solo `.hex` o `.elf` | **Dejar `.stldr` vacío**; cablear **NRST** |
| Riverdi 5″ U5 / 10″ H7 | `.hex` + `.stldr` de esa placa | Interna + región `0x90000000` |

## Documentación

| Doc | Tema |
| --- | --- |
| `ESTADO_PROYECTO.md` | Estado actual / Riverdi OK |
| `docs/01-convertir-blue-pill.md` | Primer flasheo de la sonda |
| `docs/03-cambiar-pines.md` | Recompilar BMP con otros pines |
| `docs/04-placa-propia-pinout.md` | Pinout PCB propia |
| `docs/05-riverdi-stldr-flash-externa.md` | Riverdi y `.stldr` |
| `docs/06-app-pyqt.md` | App PyQt5 |

## Requisitos

- Python 3 + `pip install -r requirements.txt`
- `arm-none-eabi-gdb` (CubeIDE / GNU Arm)
