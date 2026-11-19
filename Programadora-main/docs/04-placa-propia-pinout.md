# Placa programadora propia (STM32F103CBT6) — pinout y firmware

Tu esquemático **no es una Blue Pill genérica**: es un **STM32F103CBT6** (UC55) con interfaz SWD protegida por **SRV05-4** (UC56), pensada para programar destinos STM32 (F1/F4/H7/U5, etc.).

## Los 4 pines del conector (lado destino)

Según el plano (redes a la derecha de UC56):

| Señal en conector | Red interna | GPIO del F103 | Serie | Uso para F4 / H7 / U5 |
| --- | --- | --- | --- | --- |
| **SWDIO** | `PSWDIO` → `SWDIO` | **PB14** | R960 100 Ω | Obligatorio |
| **SWCLK** | `PCLK` → `SWCLK` | **PB13** | R956 100 Ω | Obligatorio |
| **RESET** | `PRESET` → `RESET` | **PB5** (vía R951 220 Ω) | R959 0 Ω | Muy recomendable |
| **SWIM** | `PSWIN` → `SWIM` | **PB8/PB9** | R958 100 Ω | Solo STM8; **no hace falta** para STM32 |

Además, siempre:

| Señal | Notas |
| --- | --- |
| **GND** | Común con el destino |
| **3V3** (alimentación destino) | Mejor que el destino tenga su propia 3V3; GND común |

### Cableado mínimo a un F4 / H7 / U5

```text
Programadora (tu placa)     STM32 destino (F4/H7/U5/…)
-----------------------     ---------------------------
SWDIO  ------------------- > SWDIO
SWCLK  ------------------- > SWCLK
RESET  ------------------- > NRST
GND    ------------------- > GND
(SWIM no conectar)
```

Black Magic, con targets `cortexm,stm`, habla SWD con esas familias (F4 y H7 dedicados; U5 entra por el soporte STM32L4/U5 del árbol BMP). **No** hace falta CubeProgrammer ni imitar ST-Link.

## Otros pines útiles del esquemático

| Función | GPIO | Red |
| --- | --- | --- |
| USB D− / D+ | PA11 / PA12 | `USB_DM` / `USB_DP` (+ R519 1k8 pull-up en D+) |
| LED | **PA9** | `Led_Blink` |
| Sense de tensión | PA0 | `Div_A0` (BMP lo usa como “Target voltage”) |
| SWD de la propia sonda | PA13 / PA14 | Para flashear el firmware de la programadora |

### Aviso sobre `PRESET` y NRST del F103

En el plano, la red `PRESET` también aparece ligada al **NRST (pin 7)** del F103. Verificá con multímetro:

- Si al pulsar reset del **destino** se reinicia la programadora / se cae el USB, hay cortocircuito entre reset destino y NRST del F103: hay que separar esas redes en hardware.
- Confirmá continuidad **R951 → pad del MCU**: la lectura del plano indica **PB5**; en muchos clones ST-Link el reset va a **PB6**. Si `monitor reset` no mueve el NRST del destino, medí y, si es PB6, se recompila cambiando `NRST_PIN_V1` a `GPIO6`.

## Diferencia vs build “Blue Pill genérica”

| Señal | Blue Pill (`firmware/bluepill-bmp`) | **Tu placa** (`firmware/placa-propia-bmp`) |
| --- | --- | --- |
| SWDIO | PB14 | **PB14** (igual) |
| SWCLK | PA5 | **PB13** |
| NRST | PB1 | **PB5** |
| LED | PC13 | **PA9** |

Si flasheás en tu PCB el bin de Blue Pill genérica, **SWCLK no coincide** (PA5 vs PB13): puede detectar mal o no programar.

## Firmware listo para tu placa

Archivo a grabar en el F103 de la programadora @ `0x08000000`:

`firmware/placa-propia-bmp/blackmagic_placa_propia_all.bin`

(ST-Link por PA13/PA14 de la programadora, o UART/DFU según tengas.)

Cambios de código respecto a BMP upstream: ver `patches/platform.h` y `patches/platform.c` (referencia) y el procedimiento general en [`03-cambiar-pines.md`](03-cambiar-pines.md).

### Cómo se recompila (resumen)

```bash
git clone https://codeberg.org/blackmagic-debug/blackmagic.git
cd blackmagic
# Aplicar los mismos defines:
#   TCK = PB13, TMS/SWDIO = PB14, NRST_PIN_V1 = PB5, LED = PA9
meson setup build --cross-file cross-file/bluepill.ini -Dtargets=cortexm,stm
meson compile -C build
meson compile -C build boot-bin
# Empaquetar all.bin (boot @0x08000000 + app @0x08002000)
```

## Prueba funcional

1. Flashear `blackmagic_placa_propia_all.bin` en UC55.  
2. USB a la PC → 2 COM.  
3. Cablear SWDIO/SWCLK/RESET/GND a un Nucleo F4 (o tu H7/U5).  
4. `python scripts/bmp_flash.py firmware.hex --port COMx`  
5. `monitor swdp_scan` debe listar el destino (p.ej. STM32F4 / H7 / …).
