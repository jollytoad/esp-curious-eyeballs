#!/usr/bin/env bash
# SCons' macOS platform probe does `os.listdir('/etc/paths.d')` and only guards
# against FileNotFoundError. On this machine that directory exists but isn't
# readable, so it raises PermissionError and PlatformIO dies before compiling
# anything. Widening the except to OSError makes it skip the optional
# MacPorts/Fink PATH entries, which we don't use.
#
# Idempotent - safe to re-run after PlatformIO refreshes its tool-scons package.
set -euo pipefail

TARGET=".tmp/home/.platformio/packages/tool-scons/scons-local-4.8.1/SCons/Platform/darwin.py"
OLD="    except FileNotFoundError:"
NEW="    except OSError:"

if [ ! -f "$TARGET" ]; then
  echo "not found: $TARGET (run 'esphome compile' once first to install it)" >&2
  exit 1
fi

if grep -qF "$NEW" "$TARGET"; then
  echo "already patched"
else
  # BSD sed needs an explicit backup suffix argument
  sed -i.bak -e "s|    except FileNotFoundError:|    except OSError:|" "$TARGET"
  rm -f "$TARGET.bak"
  echo "patched: $TARGET"
fi
