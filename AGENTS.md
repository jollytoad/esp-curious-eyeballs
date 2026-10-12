# AGENTS.md

ESPHome config repo for a cartoon eye on a Waveshare ESP32-C3-Zero (240×240
round GC9A01A). Four YAML files carry all the logic; there is no application
code, no tests, no CI, and no build/lint manifests.

## Files

| file | role |
|---|---|
| `eye-lambda.yaml` | the entire renderer — shared verbatim by both targets |
| `eye-globals.yaml` | shared animation state (`globals:` block) |
| `eye-device.yaml` | the real hardware config |
| `eye-sandbox.yaml` | local SDL simulator (`host:` platform, macOS) |
| `secrets.yaml` | gitignored, **currently referenced by nothing** |
| `run-sandbox.sh` | launches the simulator with the right env |
| `tools/patch-scons-darwin.sh` | idempotent SCons fix, required before builds |

`eye-lambda.yaml` is a **bare statement block**, not a lambda expression —
ESPHome wraps it. `eye-lambda.yaml` and `eye-globals.yaml` are `!include`d by
both configs specifically so sandbox and device cannot drift.

## Commands

```bash
# simulator (SDL window, no hardware)
./run-sandbox.sh

# device — the USER runs this; ask them, do not assume you can reach USB serial
cd /Users/mgibson/chatbox
export HOME="$PWD/.tmp/home"
export PATH="$PWD/.tmp/toolchain/bin:$PATH"
.venv/bin/esphome run eye-device.yaml
```

Both `export`s matter. `HOME` keeps pkgx/PlatformIO caches inside the
workspace instead of `~/Library/Caches`; `PATH` picks up the workspace-local
toolchain. `run-sandbox.sh` sets both, then runs the SCons patch, then execs
esphome — prefer it over calling esphome directly.

`.venv/bin/esphome` and `/opt/homebrew/bin/esphome` are both 2026.9.1, so
findings apply to either. `tools/patch-scons-darwin.sh` widens a `except
FileNotFoundError` to `OSError` in SCons' macOS probe; PlatformIO can undo it
when it refreshes `tool-scons`, which is why the script is idempotent and
re-run by `run-sandbox.sh`.

## Verifying a change actually landed

`esphome config` passing proves nothing about the binary. Always check the ELF:

```bash
export HOME="$PWD/.tmp/home"; export PATH="$PWD/.tmp/toolchain/bin:$PATH"
.venv/bin/esphome compile eye-device.yaml
ELF=.esphome/build/esp32-c3-zero-a/build/firmware.elf
nm --print-size "$ELF" | grep NZ_LUT          # symbols, sizes
strings "$ELF" | grep <your format string>    # format strings
```

**The build directory follows the config `name:`, not the filename.** It is
`.esphome/build/esp32-c3-zero-a/`, because `eye-device.yaml` sets
`name: esp32-c3-zero-a`. Reading a leftover `.esphome/build/eye-device/`
reports stale symbols and makes a correct change look broken. If a build
result surprises you, confirm which directory you are reading before
believing it.

## Traps that cost real time

- **Preprocessor lines inside `eye-lambda.yaml` must stay indented.** A
  `#if` at column 0 ends the `|-` block scalar; the next line then parses as
  a YAML flow mapping and you get `expected '<document start>', but found
  '<scalar>'`. Indent every `#if`/`#endif` to match the surrounding code.
- **Strip ANSI before grepping esphome output.** `esphome config` is
  colourised: `... | grep -c valid` returns 7 (mostly
  `ignore_pin_validation_error` and your own comments) where the real answer
  is 1. Use
  `sed 's/\x1b\[[0-9;]*m//g' | grep -qE "Configuration is valid!"`.
- **`heap_caps_*` is device-only.** It does not exist on the sandbox's host
  target, so it can never go in the shared `eye-lambda.yaml` — device
  diagnostics must live in `eye-device.yaml`. Relatedly, ESP-IDF 5.5 has no
  `heap_caps_get_used_size()`; only `total`, `free`, `minimum_free`,
  `largest`.
- **macOS `awk` has no `strtonum()`** and `readelf` is absent. Use
  `.venv/bin/python` for anything parsing `nm` output.
- **This is a soft-float build** — no FPU. Measured on target: `sqrtf`
  6000 ns, float multiply 1800 ns. The per-pixel loop is integer for
  performance, not style.
- **When modelling the renderer offline, replicate the C++ integer path, not
  the float maths.** Float models missed the missing `>> 8` on the eye-local
  dot product and an `up`-vector sign error — two bugs that shipped.

## Deliberate constraints — do not "fix" these

Each looks wrong and is not. `eye-device.yaml` documents the reasoning
in full; this is the short version.

- **No `wifi`, `api`, `ota`, `captive_portal` or `mdns`.** Not an oversight.
  A full-frame display buffer needs one contiguous 115,200 B block. With the
  network stack resident, free heap was 75,856 B — *below* the request — and
  the largest block was 61,440 B. Removing WiFi freed enough for the buffer
  *and* the 37,249 B vein texture. Cost: no Home Assistant. Flashing is USB,
  and logging runs on `USB_SERIAL_JTAG`, which is independent of WiFi.
  `secrets.yaml` keeps `api_encryption_key`/`fallback_ap_password` for the day
  that is revisited — which is why it is unreferenced but not deleted.
- **`buffer_size: 1.0` is correctness, not speed.** `mipi_spi` draws in
  horizontal bands and never calls `set_clipping()`, so `get_clipping()` is
  always unset and the lambda cannot tell "first band" from "only band". At
  any smaller buffer the gaze state machine advances once per *band*, so every
  `GAZE_*` constant runs at the wrong speed.
- **`update_interval` must match between `eye-sandbox.yaml` and
  `eye-device.yaml`** (both 200 ms). The `GAZE_*` constants count *frames*,
  not milliseconds, so this is the one timing parameter the shared files do
  not cover — it drifted once already.
- **`data_rate: 40MHz`.** GC9A01A defines no default, so it falls back to
  10 MHz, where a full-screen push tears visibly down the panel.
- **`auto_clear_enabled: false`** is set on both. Harmless now (the renderer
  repaints every frame and calls `it.fill()` itself) but was load-bearing for
  an earlier incremental renderer.

`#define EYE_VEINS` in `eye-lambda.yaml` is a compile-time switch and must
stay `#if`, not a runtime bool: `VEIN_TEX` is a static array occupying
37,249 B of `.bss` whether or not anything writes to it.

## Testing

There is none. Verification is: `esphome config` (both files) → `esphome
compile` (both) → look at the SDL window → user flashes and reports. Ask for
the boot log from the top; the display banner prints *requested* buffer sizes,
so a successful allocation is proven only by the **absence** of
`[E][component:143]: display is marked FAILED: Buffer allocation failed`.

## Conventions

Commits are imperative-subject with a body explaining *why*, and a `Fix:`
prefix for bug fixes. Long explanatory comments that record hard-won
measurements are wanted here — that is where the reasoning lives. Keep
`eye-device.yaml`'s header comment in sync when behaviour changes; it is the
only place several of the constraints above are justified.