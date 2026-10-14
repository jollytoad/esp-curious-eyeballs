#!/usr/bin/env bash
# Build and flash the eye to the board over USB.
#
#   ./run-device.sh
#
# The sandbox's counterpart. Same two exports matter for the same reasons:
# HOME keeps the pkgx/PlatformIO caches inside the workspace instead of
# ~/Library/Caches, and PATH picks up the workspace-local toolchain rather than
# the system's. The SCons /etc/paths.d patch is needed here too and is
# re-run every time because PlatformIO can undo it when it refreshes
# tool-scons.
#
# Pass --config-only to validate and compile without touching the hardware:
#
#   ./run-device.sh --config-only
#
# Flash mode needs the BOOT button held down while RESET is tapped, then
# released, so the board comes up in download mode. See eye-device.yaml.
set -euo pipefail
cd "$(dirname "$0")"

export HOME="$PWD/.tmp/home"
export PATH="$PWD/.tmp/toolchain/bin:$PATH"

./tools/patch-scons-darwin.sh

if [ "${1:-}" = "--config-only" ]; then
  shift
  .venv/bin/esphome config eye-device.yaml
  exec .venv/bin/esphome compile eye-device.yaml "$@"
fi

exec .venv/bin/esphome run eye-device.yaml "$@"