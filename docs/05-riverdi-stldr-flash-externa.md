# Riverdi 5″ / 10″, `.stldr` y esta programadora

## De qué hablan las placas Riverdi

Los módulos **Riverdi STM32 Embedded Display** no guardan toda la app en la flash interna del MCU:

| Módulo (familia típica) | MCU | Memoria externa | Loader que pide Riverdi / TouchGFX |
| --- | --- | --- | --- |
| **~5″ U5** (p.ej. RVT50… / SM-RVT50…) | STM32U5 (p.ej. U5G9) | **OctoSPI / OSPI** (p.ej. MX25LM51245G) | p.ej. `MX25LM51245G_STM32U599J-DK.stldr` |
| **~7″ / 10″ / 12″ H7** | STM32H7 (p.ej. H747) | **QSPI** (Micron u otra) | p.ej. `QSPI_STM32H747I-Riverdi-MICRON_V2.stldr` o `STM32H_IPS_QSPI_Loader_CM7.stldr` |

En proyectos TouchGFX, imágenes/fuentes suelen mapearse a flash externa (dirección típica tipo **`0x90000000`**).  
Por eso Riverdi insiste en el **External Loader (`.stldr`)** al programar con **STM32CubeProgrammer / CubeIDE / TouchGFX + ST-Link**.

Referencias Riverdi:

- [Why you need the right external loader](https://riverdi.com/knowledge-base/why-you-need-the-right-external-loader-for-riverdi-stm32-modules)
- [STM32 getting started](https://riverdi.com/knowledge-base/stm32-getting-started)

## Qué hace el `.stldr` (y qué no)

El `.stldr` es un plugin de **CubeProgrammer**:

1. Cube + ST-Link paran el MCU por SWD.  
2. Suben el loader a RAM del destino.  
3. Ejecutan Init / Erase / Write / Read sobre la **QSPI/OSPI**.  
4. Así graban la parte del `.hex`/`.elf` que vive en externa.

**CubeProgrammer no carga `.stldr` sobre BMP** (BMP no habla protocolo ST-Link).  
La app PyQt de este repo intenta un camino alternativo: subir el `.stldr` a RAM del destino y ejecutar `Init`/`Write` vía GDB (experimental; ver `docs/06-app-pyqt.md`). Si falla, el fallback sigue siendo ST-Link + Cube + `.stldr`.

## Qué sí puede hacer tu programadora BMP

| Tarea | BMP (esta repo) | ST-Link + Cube + `.stldr` |
| --- | --- | --- |
| SWD (SWDIO/SWCLK/NRST) a la Riverdi | Sí | Sí |
| Flash **interna** del U5/H7 | Sí (familias STM32 en BMP) | Sí |
| Flash **externa** QSPI/OSPI (assets TouchGFX) | Experimental (app + `.stldr` en RAM) | **Sí** (oficial) |
| Debug GDB básico | Sí | Sí (CubeIDE) |

## Cómo trabajarlo en la práctica (recomendado)

Flujo **mixto**, que es lo que tiene sentido con Riverdi:

```text
┌─────────────────────┐     SWD      ┌──────────────────┐
│ Tu programadora BMP │ ───────────► │ Riverdi 5″/10″   │
│ (F103 + Black Magic)│              │ U5 / H7 + QSPI   │
└─────────────────────┘              └──────────────────┘
        │                                      ▲
        │ útil para: flash interna,            │
        │ pruebas, blink, apps sin assets      │
        │ en externa                           │
        │                                      │
        │         Para TouchGFX completo:      │
        │         ST-Link + CubeProgrammer     │
        └──────── + tu .stldr  ────────────────┘
```

1. **Desarrollo / apps solo en flash interna** → tu BMP + `bmp_flash.py`.  
2. **Proyecto TouchGFX Riverdi (código + gráficos en QSPI/OSPI)** →  
   - ST-Link (o Nucleo ST-Link)  
   - CubeIDE / TouchGFX / CubeProgrammer  
   - External loader = el `.stldr` correcto del módulo  
   - Copiar el `.stldr` a  
     `STM32CubeProgrammer\bin\ExternalLoader\`  
     y activarlo en  
     `Run → Debug Configurations → Debugger → External Loaders`.

Eso es exactamente lo que documenta Riverdi; tu BMP **no reemplaza** ese paso para la externa.

## Qué no hacer

- Intentar que CubeProgrammer use tu BMP como ST-Link + `.stldr` (no habla el protocolo ST-Link).  
- Esperar que `load` de GDB programe solo la región `0x90000000` como si fuera flash interna: sin algoritmo OSPI/QSPI en la sonda, falla o no escribe la externa.  
- Usar un `.stldr` de otra placa Riverdi / otro flash: el loader tiene que coincidir con **MCU + chip + pines OSPI/QSPI** de ese módulo.

## Si en el futuro quisieras externa sin Cube

Opciones reales (ninguna es “usar el `.stldr` tal cual en BMP”):

| Opción | Esfuerzo | Notas |
| --- | --- | --- |
| Seguir con ST-Link + `.stldr` para Riverdi | Bajo | Lo que Riverdi soporta |
| OpenOCD + driver flash del chip | Alto | Hay que armar `flash bank` para ese OSPI/QSPI |
| Bootloader en flash interna que programe QSPI | Alto | Tu app recibe el binario y escribe la externa |
| Reimplementar el algoritmo del loader en un host custom | Muy alto | El `.stldr` es formato Cube, no un driver BMP |

Para documentar el producto “programadora propia”:  
**SWD genérico OK; programación completa Riverdi TouchGFX = SWD + external loader en herramientas ST.**

## Resumen en una frase

En Riverdi 5″ (U5) y 10″ (H7) el `.stldr` sirve para la **flash QSPI/OSPI de gráficos**; con **esta** programadora programás/depurás por SWD la parte interna, y para la externa seguís el flujo oficial **ST-Link + Cube/TouchGFX + tu `.stldr`**.
