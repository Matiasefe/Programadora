# Usar la Blue Pill (Black Magic) para grabar el firmware de CubeIDE

Requisito: fase 1 hecha ([`01-convertir-blue-pill.md`](01-convertir-blue-pill.md)) y `monitor swdp_scan` detecta el destino.

## Dónde está el archivo de CubeIDE

Tras **Build** en CubeIDE:

- `Debug/<proyecto>.elf` ← **recomendado** (símbolos + direcciones)
- `Debug/<proyecto>.hex` ← útil como artefacto de producción  
  (Project → Properties → C/C++ Build → Settings → MCU Post build outputs → Intel Hex)

Con Black Magic lo natural es cargar el **`.elf`**.

## Grabar con GDB

```bash
gdb-multiarch /ruta/a/tu_proyecto.elf
```

Sesión típica:

```text
(gdb) target extended-remote /dev/ttyACM0
(gdb) monitor swdp_scan
(gdb) attach 1
(gdb) load
(gdb) compare-sections
(gdb) monitor reset
(gdb) quit
```

- `load` escribe la flash del **destino** (no de la Blue Pill).
- Si `swdp_scan` no ve nada: GND, alimentación, SWDIO/SWCLK/NRST, cables cortos.

### Windows

```text
target extended-remote \\.\COMx
```

(usar el COM del “Black Magic GDB Server”).

## Script mínimo (Linux)

```bash
#!/usr/bin/env bash
set -euo pipefail
ELF=${1:?usar: ./flash-target.sh archivo.elf}
PORT=${2:-/dev/ttyACM0}

gdb-multiarch -nx --batch \
  -ex "target extended-remote ${PORT}" \
  -ex "monitor swdp_scan" \
  -ex "attach 1" \
  -ex "load" \
  -ex "compare-sections" \
  -ex "monitor reset" \
  "$ELF"
```

## Relación con CubeIDE

| En CubeIDE | Con blue-link |
| --- | --- |
| Compilar / generar `.elf` `.hex` | Igual |
| Botón Run/Debug con ST-Link | No uses ST-Link; usá GDB como arriba |
| CubeProgrammer | No habla con esta sonda |

Podés seguir desarrollando en CubeIDE y solo cambiar el paso de “bajar el programa”.

## Depurar (opcional)

Después de `attach 1` y `load`:

```text
(gdb) break main
(gdb) continue
```

O configurá en CubeIDE un debug launch “GDB Hardware Debugging” apuntando al puerto de la BMP.

## Si el destino “desaparece” del SWD

- Conectá **NRST** (PB1 → NRST del destino).
- Reseteá el destino antes del scan.
- Revisá que el firmware del destino no deje los pines SWD en un estado imposible sin reset.
