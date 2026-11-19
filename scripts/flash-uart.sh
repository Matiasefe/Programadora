#!/usr/bin/env bash
# Graba Black Magic (bootloader + firmware) en una Blue Pill vía bootloader ROM UART.
# Uso: ./scripts/flash-uart.sh /dev/ttyUSB0
set -euo pipefail

PORT=${1:-}
if [[ -z "${PORT}" ]]; then
  echo "Uso: $0 <puerto-serie>   ej: $0 /dev/ttyUSB0" >&2
  exit 1
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
BIN="${ROOT}/firmware/bluepill-bmp/blackmagic_bluepill_all.bin"

if [[ ! -f "${BIN}" ]]; then
  echo "No encuentro ${BIN}" >&2
  exit 1
fi

if ! command -v stm32flash >/dev/null 2>&1; then
  echo "Instalá stm32flash (apt install stm32flash) o usá CubeProgrammer en modo UART." >&2
  exit 1
fi

echo "=== Blue Pill: BOOT0 debe estar en 1 y acabás de resetear ==="
echo "Puerto: ${PORT}"
echo "Imagen: ${BIN}"
echo

echo "-> Borrando flash..."
stm32flash -o "${PORT}"

echo "-> Grabando + verify + go..."
stm32flash -w "${BIN}" -v -g 0x0 "${PORT}"

echo
echo "Listo. Poné BOOT0=0, desconectá el USB-serie, enchufá el USB de la Blue Pill y reseteá."
echo "Después: docs/01-convertir-blue-pill.md (paso 4 en adelante)."
