# App PyQt5 — Programadora

Aplicación de escritorio para detectar la sonda **Black Magic Probe** y programar:

- STM32 **F1 … F7 / H7 / U5** (flash **interna**) con `.hex` / `.elf`
- Pantallas **Riverdi** (flash **externa** QSPI/OSPI) con `.hex` + `.stldr`

**No usa** STM32CubeProgrammer.

## Requisitos en Windows

```bat
cd Programadora
pip install -r requirements.txt
```

También hace falta `arm-none-eabi-gdb` (viene con STM32CubeIDE / GNU Arm toolchain).

## Cómo ejecutar

```bat
cd Programadora\app
python run_programadora.py
```

O:

```bat
cd Programadora\app
python -m programadora_app
```

O doble clic en `app\run_programadora.bat`.

## Uso

1. Conectá la programadora por USB → **Detectar** (puerto GDB).
2. Elegí el `.hex` (o `.elf`) generado por CubeIDE / TouchGFX.
3. Si es Riverdi con assets en QSPI/OSPI, elegí el `.stldr` de **esa** pantalla.
4. Opcional: ruta a `arm-none-eabi-gdb.exe`.
5. **Programar**.

### Comportamiento

| Contenido del HEX | Acción |
| --- | --- |
| Solo flash interna (`0x0800…`) | `erase_mass` + `load` por GDB/BMP |
| También región `0x9000…` | Interna igual + externa ejecutando el `.stldr` en RAM del destino vía GDB |

## Estructura

```text
app/
  run_programadora.py
  run_programadora.bat
  programadora_app/
    main.py
    main_window.py
    probe.py
    gdb_find.py
    hex_util.py
    flasher.py
    stldr_runner.py
```

## Notas

- La familia del combo es **informativa**; BMP identifica el MCU por SWD.
- El flujo `.stldr` (runner v6) restaura el loader en RAM e invoca `Init` / `Write` / `MassErase` por trampolín BKPT (no usa `call` de GDB). Scratch/stack se calculan encima del segmento RAM del `.stldr`. Si un Riverdi concreto falla, revisá el log (`RET_Init`, HardFault) y que el `.stldr` sea el del módulo.
- Pinout de tu PCB: ver `docs/04-placa-propia-pinout.md`.
