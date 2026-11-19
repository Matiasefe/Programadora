# Fase 1 — Convertir la Blue Pill en programadora

Objetivo: dejar la Blue Pill corriendo **Black Magic Probe**. Después de esto, la placa **ya no ejecuta tu app**: es solo la sonda.

## Material

- 1× Blue Pill STM32F103C8T6
- 1× adaptador **USB–serie 3,3 V** (CP2102, FT232, CH340, etc. — **no a 5 V en TX/RX**)
- Cables / protoboard
- PC con Linux o Windows
- Binarios de `firmware/bluepill-bmp/`

### Nota sobre el flash de 64 KB vs 128 KB

Muchas Blue Pill marcan C8 (64 KB) pero el silicio suele tener **128 KB**. Este firmware ocupa ~94 KB y **necesita esos 128 KB**. Si al verificar la escritura falla la mitad alta, esa placa no sirve para este build (probá otra Blue Pill).

### Pull-up USB (D+)

En muchas Blue Pill el pull-up de 1,5 kΩ de USB está mal (a 5 V). Lo ideal es pull-up de **1,5 kΩ de PA12 (D+) a 3,3 V**. Si al final no enumera por USB, revisá eso.

## Paso 1 — Cablear el bootloader de fábrica (USART1)

| USB–serie | Blue Pill |
| --- | --- |
| GND | GND |
| TX (3V3) | **PA10** (USART1_RX) |
| RX | **PA9** (USART1_TX) |
| 5V/3V3 | Alimentá la Blue Pill (USB de la placa o 5V pin, según tu dongle) |

Jumpers:

1. **BOOT0 = 1** (hacia 3V3 / posición “1”)
2. BOOT1 = 0 (normal)
3. Pulsá **RESET** (o desconectá/reconectá alimentación)

La F103 queda en el bootloader ROM por UART.

## Paso 2 — Instalar herramienta de flasheo

### Linux

```bash
sudo apt install stm32flash
# o usá STM32CubeProgrammer en modo UART
```

### Windows

Usá **STM32CubeProgrammer** → conexión **UART**, o `stm32flash` si lo tenés.

## Paso 3 — Borrar y grabar

Desde la raíz del repo (ajustá el puerto):

```bash
# Linux: a menudo /dev/ttyUSB0 o /dev/ttyACM0
./scripts/flash-uart.sh /dev/ttyUSB0
```

A mano, equivalente:

```bash
# Borrar (opcional pero recomendado la primera vez)
stm32flash -o /dev/ttyUSB0

# Grabar bootloader + firmware juntos en 0x08000000
stm32flash -w firmware/bluepill-bmp/blackmagic_bluepill_all.bin -v -g 0x0 /dev/ttyUSB0
```

Si preferís dos archivos:

```bash
stm32flash -w firmware/bluepill-bmp/blackmagic_bluepill_bootloader.bin -v /dev/ttyUSB0
stm32flash -w firmware/bluepill-bmp/blackmagic_bluepill_firmware.bin -v -S 0x08002000 /dev/ttyUSB0
```

Con **CubeProgrammer (UART)**:

1. Puerto del USB–serie, baud 115200 (o el que detecte).
2. Download del `blackmagic_bluepill_all.bin` en dirección `0x08000000`.
3. Verify.

## Paso 4 — Arrancar como programadora

1. **BOOT0 = 0**
2. Desconectá el USB–serie de PA9/PA10
3. Conectá el **USB micro de la Blue Pill** a la PC
4. Pulsá RESET

### Linux — qué deberías ver

Dos dispositivos CDC, por ejemplo:

- `/dev/ttyACM0` → **Black Magic GDB Server**
- `/dev/ttyACM1` → **Black Magic UART Port**

Instalá reglas udev (una vez):

```bash
sudo cp driver/99-blackmagic-plugdev.rules /etc/udev/rules.d/
sudo udevadm control --reload-rules
sudo udevadm trigger
# desconectá y reconectá la Blue Pill
```

A veces aparecen como `/dev/ttyBmpGdb` y `/dev/ttyBmpTarg`.

### Windows

Dos puertos COM nuevos. El de menor número suele ser el GDB server (confirmá en el Administrador de dispositivos / descripción “Black Magic GDB Server”).

Si no enumera:

- Revisá pull-up USB a 3,3 V
- Confirmá BOOT0=0
- Regrabá el `*_all.bin`
- Probá otro cable USB de datos

## Paso 5 — Probar que la sonda vive (sin destino todavía)

```bash
gdb-multiarch
# o: arm-none-eabi-gdb
```

Dentro de GDB:

```text
target extended-remote /dev/ttyAcm0
monitor version
```

(Sustituí el puerto por el de GDB en tu PC.)

Si responde con la versión de Black Magic, **la Blue Pill ya es programadora**.

## Paso 6 — Primera prueba con un STM32 destino

Cableá:

| Programadora | Destino |
| --- | --- |
| PB14 | SWDIO |
| PA5 | SWCLK |
| PB1 | NRST |
| GND | GND |

Alimentá el destino (mejor con su propia 3V3 + GND común).

En GDB:

```text
target extended-remote /dev/ttyACM0
monitor swdp_scan
```

Deberías ver algo como “Available Targets” con un STM32. Eso confirma SWD.

Cuando eso funcione, pasá a [`02-usar-como-programadora.md`](02-usar-como-programadora.md).

## Recuperar la Blue Pill más adelante

Si el firmware se corrompe:

1. BOOT0=1, RESET
2. Otra vez UART en PA9/PA10
3. Regrabar `blackmagic_bluepill_all.bin`

Con el bootloader BMD instalado también podés actualizar por **DFU USB** (sin UART) cuando la sonda arranca en DFU; para el día a día, UART + BOOT0 siempre funciona.
