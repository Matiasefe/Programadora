# Personalizar pines SWD y generar un nuevo `.bin`

Documento de procedimiento: cómo cambiar los pines de salida de la programadora (Blue Pill + Black Magic Probe) y recompilar el firmware.

Esto **no** se hace en STM32CubeIDE. Se edita el código fuente de **Black Magic Debug** y se compila con **Meson** + `arm-none-eabi-gcc`.

---

## 1. Pinout actual (build de este repo)

| Señal (hacia el STM32 destino) | Pin MCU | Notas |
| --- | --- | --- |
| SWDIO | **PB14** | Dato SWD |
| SWCLK | **PA5** | Reloj SWD |
| NRST | **PB1** | Reset del destino (recomendado) |
| LED actividad | **PC13** | LED de la Blue Pill |
| USB D− / D+ | PA11 / PA12 | No tocar |
| UART auxiliar TX/RX | PA2 / PA3 | Opcional |

El conector SWD de 4 pines de la Blue Pill (**PA13/PA14**) es el debug de la **propia** sonda. Esta build **no** lo usa como salida al destino.

---

## 2. Requisitos en la PC de compilación

- Git  
- Python 3  
- Meson + Ninja  
- Toolchain: `arm-none-eabi-gcc`, `arm-none-eabi-objcopy`, etc.  
- (Linux) `libnewlib-arm-none-eabi`

Ejemplo Ubuntu/Debian:

```bash
sudo apt install git meson ninja-build gcc-arm-none-eabi binutils-arm-none-eabi libnewlib-arm-none-eabi
```

En Windows: WSL2 con lo mismo, o un entorno Linux. Compilar BMP nativo en CMD/PowerShell es más incómodo.

---

## 3. Obtener el código fuente

```bash
git clone https://codeberg.org/blackmagic-debug/blackmagic.git
cd blackmagic
```

La sonda Blue Pill usa la plataforma **`stlink`** con la opción de probe **`bluepill`** (`-DBLUEPILL=1`).

Archivos clave:

| Archivo | Qué define |
| --- | --- |
| `src/platforms/stlink/platform.h` | Puertos/pines SWDIO, SWCLK, TDI/TDO, NRST, LED, UART |
| `src/platforms/stlink/platform.c` | Con `BLUEPILL`: LED=PC13, NRST=`NRST_PIN_V1` (= PB1) |
| `cross-file/bluepill.ini` | Config Meson por defecto para Blue Pill |

---

## 4. Elegir pines nuevos (reglas)

Anotá tu PCB:

| Señal | Pin elegido |
| --- | --- |
| SWDIO | |
| SWCLK | |
| NRST | |
| LED (opcional) | |

**Evitar:**

| Pines | Motivo |
| --- | --- |
| PA11, PA12 | USB |
| PD0, PD1 | Cristal 8 MHz |
| PA13, PA14 | SWD de la propia Blue Pill (recuperación más difícil) |
| PA9, PA10 | Útiles para regrabar por UART (bootloader ROM) si algo falla |

Cualquier otro GPIO libre suele servir para bit-bang SWD.

---

## 5. Editar `platform.h`

Archivo: `src/platforms/stlink/platform.h`

### 5.1 SWDIO y SWCLK

En esta plataforma, SWDIO/SWCLK se definen vía TMS/TCK:

```c
#define TMS_PORT GPIOB
#define TCK_PORT GPIOA
#define TMS_PIN  GPIO14   /* SWDIO = PB14 */
#define TCK_PIN  GPIO5    /* SWCLK = PA5  */

#define SWDIO_PORT TMS_PORT
#define SWCLK_PORT TCK_PORT
#define SWDIO_PIN  TMS_PIN
#define SWCLK_PIN  TCK_PIN
```

**Ejemplo:** pasar a `PB9` = SWDIO y `PB8` = SWCLK:

```c
#define TMS_PORT GPIOB
#define TCK_PORT GPIOB
#define TMS_PIN  GPIO9
#define TCK_PIN  GPIO8
```

### 5.2 ¡Ojo! Macros `SWD_CR` / `SWD_CR_MULT`

Más abajo en el mismo archivo hay algo **atado al pin 14**:

```c
#define SWD_CR      GPIO_CRH(SWDIO_PORT)
#define SWD_CR_MULT (1U << ((14U - 8U) << 2U))
```

Eso controla el modo input/output de SWDIO en el F103 (`CRL` = pines 0–7, `CRH` = pines 8–15).

Si cambiás el **número** de pin de SWDIO, **tenés que actualizar estas macros**:

| Pin SWDIO | Registro | Fórmula `SWD_CR_MULT` |
| --- | --- | --- |
| 0–7 | `GPIO_CRL(SWDIO_PORT)` | `(1U << ((N) << 2U))` |
| 8–15 | `GPIO_CRH(SWDIO_PORT)` | `(1U << (((N) - 8U) << 2U))` |

Ejemplos:

```c
/* SWDIO = PB9 (pin 9 → CRH, N-8 = 1) */
#define SWD_CR      GPIO_CRH(SWDIO_PORT)
#define SWD_CR_MULT (1U << ((9U - 8U) << 2U))

/* SWDIO = PB0 (pin 0 → CRL) */
#define SWD_CR      GPIO_CRL(SWDIO_PORT)
#define SWD_CR_MULT (1U << ((0U) << 2U))
```

Si solo cambiás `TMS_PIN` y te olvidás de `SWD_CR`/`SWD_CR_MULT`, el `swdp_scan` suele fallar o ser inestable.

### 5.3 NRST

En `platform.h`:

```c
#define NRST_PORT   GPIOB
#define NRST_PIN_V1 GPIO1   /* usado en Blue Pill (ver platform.c) */
#define NRST_PIN_V2 GPIO0
```

Con `BLUEPILL`, `platform.c` hace `nrst_pin = NRST_PIN_V1`.

Para usar por ejemplo **PB0** como reset:

- opción simple: `#define NRST_PIN_V1 GPIO0`, o  
- editar en `platform.c` el bloque `#ifdef BLUEPILL`.

### 5.4 LED

Con `BLUEPILL`, el LED es **PC13** (GPIO13 en `GPIOC`), asignado en `platform.c` (`led_idle_run = GPIO13`).  
Si tu placa usa otro LED, cambiá puerto/pin ahí y el `LED_PORT` de `platform.h` si hace falta.

---

## 6. Compilar

Desde la raíz del clon `blackmagic`:

```bash
# Configurar (solo la primera vez, o tras borrar build/)
meson setup build --cross-file cross-file/bluepill.ini -Dtargets=cortexm,stm

# Si ya existía build/ y cambiaste opciones:
# meson setup build --reconfigure --cross-file cross-file/bluepill.ini -Dtargets=cortexm,stm

meson compile -C build
meson compile -C build boot-bin
```

Salida esperada:

- `build/blackmagic_bluepill_firmware.bin` → se carga en **`0x08002000`**
- `build/blackmagic_bluepill_bootloader.bin` → se carga en **`0x08000000`**

### Flash de la F103C8

Esta build usa ~90 KB+ y asume **128 KB** de flash (muchas Blue Pill C8 lo tienen aunque digan 64 KB). Si el verify falla en la mitad alta, esa placa no sirve para este firmware.

---

## 7. Generar el `*_all.bin` (un solo archivo)

Une bootloader (8 KB reservados) + firmware:

```bash
python3 - <<'PY'
from pathlib import Path
boot = Path('build/blackmagic_bluepill_bootloader.bin').read_bytes()
fw   = Path('build/blackmagic_bluepill_firmware.bin').read_bytes()
out  = bytearray(b'\xFF' * 0x2000)
out[:len(boot)] = boot
out.extend(fw)
Path('build/blackmagic_bluepill_all.bin').write_bytes(out)
print('bytes:', len(out))
PY
```

Grabás **`blackmagic_bluepill_all.bin`** en **`0x08000000`** (ST-Link o UART).

---

## 8. Flashear la Blue Pill programadora

### Con ST-Link (SWD de la propia Blue Pill: PA13/PA14)

- BOOT0 = 0  
- CubeProgrammer / OpenOCD / `st-flash`  
- Dirección `0x08000000`, archivo `blackmagic_bluepill_all.bin`

### Con UART (sin ST-Link)

- BOOT0 = 1, USB–serie 3,3 V en PA9/PA10  
- `stm32flash -w build/blackmagic_bluepill_all.bin -v -g 0x0 /dev/ttyUSB0`  
- Luego BOOT0 = 0

Al enchufar el USB de la Blue Pill deben aparecer **2 COM** (GDB + UART).

---

## 9. Verificar el pinout nuevo

1. Cableá el destino a **tus** pines nuevos (no a PB14/PA5 si ya los cambiaste).  
2. En GDB:

```text
target extended-remote \\.\COMx
monitor swdp_scan
```

3. Si aparece `STM32F1` (u otra familia), el SWD del pinout nuevo funciona.  
4. Programá un `.hex` de prueba con `scripts/bmp_flash.py`.

---

## 10. Documentar el cambio (checklist)

En el repo del producto (este u otro), actualizá:

- [ ] Tabla de pinout en `README.md`
- [ ] `firmware/.../SOURCE.txt` (commit upstream + pins)
- [ ] Este documento (sección “Pinout actual”)
- [ ] Esquema / PCB silk si aplica
- [ ] Binarios nuevos en `firmware/bluepill-bmp/`

Plantilla para `SOURCE.txt`:

```text
upstream=https://codeberg.org/blackmagic-debug/blackmagic
commit=<hash>
probe=bluepill
targets=cortexm,stm
pinout=SWDIO=PBx SWCLK=PAy NRST=PBz LED=PC13
built=<ISO-8601>
```

---

## 11. Resumen del flujo (para la memoria / informe)

```text
1. Clonar blackmagic (Codeberg)
2. Editar platform.h (TMS/TCK/NRST + SWD_CR/SWD_CR_MULT)
3. Si hace falta, editar platform.c (LED / NRST Blue Pill)
4. meson setup + meson compile (+ boot-bin)
5. Generar blackmagic_bluepill_all.bin
6. Flashear en 0x08000000
7. Probar monitor swdp_scan con el cableado nuevo
8. Actualizar documentación y binarios del repo
```

---

## 12. Referencias

- Proyecto: https://codeberg.org/blackmagic-debug/blackmagic  
- Hardware Blue Pill en docs BMP: https://black-magic.org/docs/intro/hardware/  
- Flasheo inicial de la sonda: [`01-convertir-blue-pill.md`](01-convertir-blue-pill.md)  
- Uso con `.hex` / script Python: [`02-usar-como-programadora.md`](02-usar-como-programadora.md)
