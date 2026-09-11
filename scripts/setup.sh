#!/usr/bin/env bash
set -euo pipefail

check_only=false
case "${1:-}" in
  "") ;;
  --check-only) check_only=true ;;
  *) echo "Usage: bash scripts/setup.sh [--check-only]" >&2; exit 2 ;;
esac

if [[ "$(uname -s 2>/dev/null)" != "Darwin" ]]; then
  echo "Proms setup requires macOS 14 Sonoma or newer." >&2
  exit 1
fi
macos_version="$(sw_vers -productVersion 2>/dev/null || true)"
macos_major="${macos_version%%.*}"
if [[ ! "$macos_major" =~ ^[0-9]+$ ]] || (( macos_major < 14 )); then
  echo "Proms setup requires macOS 14 Sonoma or newer." >&2
  exit 1
fi

script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd -- "$script_dir/.." && pwd)"

for required_file in pyproject.toml uv.lock package.json package-lock.json; do
  if [[ ! -f "$repo_root/$required_file" ]]; then
    echo "Run this script from a complete Proms repository checkout; $required_file is missing." >&2
    exit 1
  fi
done

node_is_supported() {
  local version major minor
  version="$(node --version 2>/dev/null)" || return 1
  version="${version#v}"
  [[ "$version" =~ ^([0-9]+)\.([0-9]+)(\.[0-9]+)? ]] || return 1
  major="${BASH_REMATCH[1]}"
  minor="${BASH_REMATCH[2]}"
  (( major > 20 || (major == 20 && minor >= 9) ))
}

if $check_only; then
  missing=()
  command -v uv >/dev/null 2>&1 || missing+=(uv)
  if ! command -v node >/dev/null 2>&1 || ! node_is_supported; then
    missing+=("Node.js 20.9+")
  fi
  command -v npm >/dev/null 2>&1 || missing+=(npm)
  command -v npx >/dev/null 2>&1 || missing+=(npx)
  if (( ${#missing[@]} )); then
    echo "Missing prerequisites: ${missing[*]}. Run bash scripts/setup.sh to install them." >&2
    exit 1
  fi
  echo "READY: setup prerequisites are available"
  exit 0
fi

require_brew() {
  if ! command -v brew >/dev/null 2>&1; then
    echo "Homebrew is required to install missing tools. Install it from https://brew.sh, then run bash scripts/setup.sh again." >&2
    exit 1
  fi
}

install_node_24() {
  require_brew
  brew install node@24
  export PATH="$(brew --prefix node@24)/bin:$PATH"
  hash -r
}

if ! command -v uv >/dev/null 2>&1; then
  require_brew
  brew install uv
  hash -r
fi

if ! command -v node >/dev/null 2>&1; then
  install_node_24
elif ! node_is_supported; then
  install_node_24
fi

if ! node_is_supported; then
  echo "Node.js 20.9 or newer is required after installation." >&2
  exit 1
fi
if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not installed with Node.js. Repair the Homebrew Node installation, then retry." >&2
  exit 1
fi
if ! command -v npx >/dev/null 2>&1; then
  echo "npx was not installed with Node.js. Repair the Homebrew Node installation, then retry." >&2
  exit 1
fi

cd -- "$repo_root"
uv sync --locked
npm ci
npx playwright install chromium
uv run --locked playwright install chromium
npm run build

if [[ ! -e "$repo_root/proxies.txt" ]]; then
  : > "$repo_root/proxies.txt"
fi

echo "READY: dependencies, Chromium, and the local control panel are installed"
echo "NEXT: run 'uv run --locked proms', then open http://127.0.0.1:8000/control/"
