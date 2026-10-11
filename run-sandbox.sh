#!/usr/bin/env bash
# Launch the cartoon eye in a local SDL window — no hardware, no upload.
#
#   ./run-sandbox.sh
#
# Sets up the bits this machine needs: a workspace-local HOME (pkgx/platformio
# caches), Homebrew's clang++ (the /usr/bin C++ shims are dead here), and the
# SCons /etc/paths.d patch (which PlatformIO may undo after refreshing its
# toolchain, hence the idempotent re-run).
set -euo pipefail
cd "$(dirname "$0")"

export HOME="$PWD/.tmp/home"
export PATH="$PWD/.tmp/toolchain/bin:$PATH"

./tools/patch-scons-darwin.sh

exec .venv/bin/esphome run eye-sandbox.yaml "$@"
