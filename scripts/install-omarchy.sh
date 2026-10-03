#!/usr/bin/env bash
set -euo pipefail
if [[ "$(uname -s)" != Linux ]]; then
  echo "This installer targets Omarchy / Linux. Use --demo from source on other platforms." >&2
  exit 1
fi
if [[ "$EUID" -eq 0 ]]; then
  echo "Run this installer as your regular desktop user." >&2
  exit 1
fi
command -v uv >/dev/null || { echo "Install uv first: sudo pacman -S --needed uv" >&2; exit 1; }
ROOT=$(cd "$(dirname "$0")/.." && pwd)
DATA_DIR="${XDG_DATA_HOME:-$HOME/.local/share}"
APP_DIR="$DATA_DIR/ruuvilinux"
VENV="$APP_DIR/venv"
mkdir -p "$APP_DIR"
if [[ ! -x "$VENV/bin/python" ]]; then uv venv --python python3 "$VENV"; fi
uv pip install --python "$VENV/bin/python" --upgrade "$ROOT"
mkdir -p "$HOME/.local/bin"
ln -sfn "$VENV/bin/ruuvilinux" "$HOME/.local/bin/ruuvilinux"
"$VENV/bin/python" "$ROOT/scripts/install-desktop.py" "$VENV/bin/ruuvilinux" "$ROOT/packaging/org.ruuvilinux.app.svg"
if command -v update-desktop-database >/dev/null; then
    update-desktop-database "$DATA_DIR/applications"
fi
echo "Installed RuuviLinux. Open it from Super + Space, or run ~/.local/bin/ruuvilinux."
