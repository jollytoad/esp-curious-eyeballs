#!/usr/bin/env bash
# Build and flash the eye to the board over USB.
#
#   ./run-device.sh
#
# Prefer USB, fall back to Over The Air. SERIAL resolves to whichever serial
# ports are present and is SKIPPED when there are none, so unplugging the cable
# moves the upload onto the network instead of failing:
#
#   cable in   -> [1] /dev/cu.usbmodemXXXX   and logs over USB
#   cable out  -> OTA via eyeballs-1.local  and logs over the API
#
# Logs follow whatever the upload used. To pin the choice, put --device before
# "$@" - an explicit flag wins:
#
#   ./run-device.sh --device /dev/cu.usbmodem2101
#
# SERIAL still prompts if you have more than one serial port plugged in. That
# prompt is the right behaviour; do not paper over it.
#
# The sandbox's counterpart. Same two exports matter for the same reasons:
# HOME keeps the pkgx/PlatformIO caches inside the workspace instead of
# ~/Library/Caches, and PATH picks up the workspace-local toolchain rather than
# the system's. The SCons /etc/paths.d patch is needed here too and is re-run
# every time because PlatformIO can undo it when it refreshes tool-scons.
#
# Pass --config-only to validate and compile without touching the hardware:
#
#   ./run-device.sh --config-only
#
# USB upload needs the BOOT button held while RESET is tapped, then released.
# This board has no usb-serial chip, so it often needs doing. OTA does not - and
# OTA cannot recover a board whose current firmware is broken. See AGENTS.md.
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

# A --device given by the caller wins; do not add a second one and make
# argparse ambiguous.
for arg in "$@"; do
  if [ "$arg" = "--device" ]; then
    exec .venv/bin/esphome run eye-device.yaml "$@"
  fi
done

exec .venv/bin/esphome run eye-device.yaml \
  --device SERIAL --device OTA "$@"