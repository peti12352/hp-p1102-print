#!/usr/bin/env bash
# curl -fsSL https://raw.githubusercontent.com/peti12352/hp-p1102-print/main/install.sh | bash
# curl -fsSL ... | bash -s -- --with-office   # add LibreOffice for docx/xlsx
set -euo pipefail

REPO_URL="${HP_P1102_REPO:-https://github.com/peti12352/hp-p1102-print.git}"
ROOT="${HP_P1102_HOME:-$HOME/.local/share/hp-p1102-print}"
BIN="${INSTALL_DIR:-$HOME/.local/bin}"
WITH_OFFICE=0

for arg in "$@"; do
  case "$arg" in
    --with-office) WITH_OFFICE=1 ;;
    -h|--help)
      echo "usage: install.sh [--with-office]"
      echo "  default: foo2zjs, ghostscript, cups (PDF printing)"
      echo "  --with-office: also install LibreOffice for docx/xlsx"
      exit 0
      ;;
  esac
done

die() { echo "FAIL $*" >&2; exit 1; }

root() {
  local s="${BASH_SOURCE[0]:-}"
  if [[ -n "$s" && -f "$(dirname "$s")/print_p1102.py" ]]; then
    dirname "$(readlink -f "$s")"
    return
  fi
  command -v git >/dev/null || die "need git"
  [[ -d "$ROOT/.git" ]] || git clone --depth 1 "$REPO_URL" "$ROOT"
  git -C "$ROOT" pull --ff-only 2>/dev/null || true
  echo "$ROOT"
}

deps() {
  case "$(uname -s)" in
    Linux)
      if command -v dnf &>/dev/null; then
        local pkgs=(foo2zjs ghostscript cups)
        if [[ "$WITH_OFFICE" -eq 1 ]]; then
          pkgs+=(libreoffice-core libreoffice-writer libreoffice-calc libreoffice-impress)
        fi
        sudo dnf install -y "${pkgs[@]}"
      elif command -v apt &>/dev/null; then
        sudo apt update
        local pkgs=(foo2zjs ghostscript cups)
        if [[ "$WITH_OFFICE" -eq 1 ]]; then
          pkgs+=(libreoffice-writer libreoffice-calc libreoffice-impress)
        fi
        sudo apt install -y "${pkgs[@]}"
      else
        die "install foo2zjs ghostscript cups manually (add LibreOffice for docx)"
      fi
      ;;
    Darwin)
      command -v brew >/dev/null || die "install homebrew: https://brew.sh"
      brew install foo2zjs ghostscript
      ;;
    *) die "use install.ps1 on windows" ;;
  esac
}

r="$(root)"
deps
mkdir -p "$BIN"
ln -sf "$r/print-p1102" "$BIN/print-p1102"
chmod +x "$r/print-p1102" "$r/print_p1102.py"
if [[ "$WITH_OFFICE" -eq 1 ]]; then
  echo "installed: $BIN/print-p1102 (with office conversion)"
else
  echo "installed: $BIN/print-p1102 (PDF only; use install.sh --with-office for docx)"
fi
"$r/print-p1102" --doctor || exit 1
