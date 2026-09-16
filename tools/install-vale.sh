#!/usr/bin/env bash
set -euo pipefail

readonly VALE_VERSION="3.9.1"
readonly INSTALL_DIR=".tools/vale/current"

if [[ "$(uname -s)" != "Linux" || "$(uname -m)" != "x86_64" ]]; then
  echo "Automatic Vale installation currently supports Linux x86_64 only." >&2
  echo "Install Vale 3.9.1 on PATH and rerun make policy." >&2
  exit 1
fi

archive_dir="$(mktemp -d)"
trap 'rm -rf "$archive_dir"' EXIT

curl -sSfL \
  "https://github.com/errata-ai/vale/releases/download/v${VALE_VERSION}/vale_${VALE_VERSION}_Linux_64-bit.tar.gz" \
  -o "${archive_dir}/vale.tar.gz"
mkdir -p "$INSTALL_DIR"
tar -xzf "${archive_dir}/vale.tar.gz" -C "$INSTALL_DIR" vale
"${INSTALL_DIR}/vale" --version
