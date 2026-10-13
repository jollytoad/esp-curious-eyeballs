# AGENTS.md

ESPHome config repo for a cartoon eye on a Waveshare ESP32-C3-Zero (240×240
round GC9A01A). Four YAML files carry all the firmware logic; there is no
firmware-side application code, no tests, no CI, and no build/lint manifests.
`tools/vessel/` is a Python model used to choose renderer parameters — it never
ships.

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
| `tools/vessel/render.py` | offline vessel rig — run this for `.tmp/sphere.png` (shape) and `.tmp/panel.png` (size) |
| `tools/vessel/vessel.py` | the model itself; only `render.py` should import it |

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

## Memory: the one thing you cannot reason about

The frame buffer needs **115,200 B in one contiguous block**. The largest block
this board will hand over is **114,688 B** — 512 short — and `Buffer allocation
failed` is the entire symptom. It produces a blank panel and one log line.

Measured, on hardware, by flash:

| RAM used | outcome |
|---|---|
| ~79,4xx, no vessels | works |
| 96,400, vessels in a packed ring at side 129 | works |
| 98,992, same at side 145 | works |
| 101,920, same at side 161 | works |
| **108,656, same at side 193** | **works** |
| 103,000, front-only vessels, side 129 as a square | works |
| 119,696 | fails |
| 125,104 | fails |
| 146,144, side 161 | fails |

**The ceiling is somewhere between 108,656 and 119,696. That 11,040 B gap has
never been measured.** Do not assume 108,656 is the wall, and do not assume it
is not.

The ring ladder predicted every step to within 4 B of the build's own `RAM:`
line, so the ladder in the Vessels section below is worth trusting as a
planning tool. It is still not evidence: predict the number, then flash, then
read whether `Buffer allocation failed` appears.

**The relationship is not monotonic.** 79.4K works, 79,584 fails, 103K works
again. There is no threshold, so *do not model it*. Three models were built and
all three were wrong, one of them fitted to a table row that had been invented
rather than measured. Compile, flash, and read whether the failure line appears.
The `RAM:` line in the build output is a fact; any equation relating it to the
allocation is a guess.

Two corollaries:

- **Adding an `interval:` block with a `heap_caps_*` lambda was enough on its
  own to break a build that worked without it.** If the display is failing and
  the change looks unrelated, suspect whatever was just added, not the vessels.
- **Two vessel textures do not fit; one does.** That is the whole of the
  one-array design, and it is memory, not taste. See the `EYE_VEINS` note in
  `eye-lambda.yaml`.

## Vessels

Baked once at boot into one packed array in eye-local coordinates, from a LCG
seeded by hardware entropy, so the set differs on every boot. **121 ms on the
first frame** on a soft-float C3; the WDT survives it. Roughly 8,600 samples.

The texture is a **ring, not a square**: `uint8_t[21708]` rather than
`uint8_t[193][193]`. The sclera branch samples theta 30..90 deg, which is an
annulus in texture coordinates, so the disc under the iris and the four corners
off the eyeball are 42 percent of the square and are never read. Rows are packed
left half then right half, with `VEIN_ROWOFF[ty]` giving each row's start and
`VEIN_HW_OUT`/`VEIN_HW_IN` its half-widths — 580 B of index.

That layout has three off-by-one rules, all in the comment at `VEIN_R_IN`, and
each one produced a texture that looked nearly right and compiled clean.

**`VEIN_TEX_SIDE` is the only resolution knob, and two constants must be derived
from it or the bump reads as a regression.** `VEIN_R_IN` is `VEIN_TEX_MID / 2`
(the limbus) — a literal left behind silently starts storing texels under the
iris again. `VEIN_W_TRUNK` is `VEIN_TEX_MID / 64.0f`, because brush radii are in
TEXELS and a texel covers less of the eye as the grid grows; leave it and the
vessels get thinner instead of finer. Both were literals, and both were wrong
twice before they were made expressions.

Cost ladder, ring + index, with the RAM each one built to:

| side | MID | ring + index | RAM |
|---|---|---|---|
| 129 | 64 | 10,036 B | 96,400 |
| 145 | 72 | 12,628 B | 98,992 |
| 161 | 80 | 15,552 B | 101,920 |
| 193 | 96 | 22,288 B | 108,656 |
| 209 | 104 | 26,092 B | 112,460 (unflashed) |

The ring packing is why this ladder exists at all. The old side129 *square* cost
16,641 B; the side193 *ring* costs 22,288 B and stores 50 percent more texels.

Cost control, all of it load-bearing:

- The spline runs in **Q12 integer**, and every product of a Q12 coefficient by
  a Q12 power of `t` needs its own `>> 12`. Without them the curve is 4096×
  too large — and it still looks correct at `t = 0`, where all three terms
  vanish, so only the second sample reveals it.
- Re-normalising uses one Newton step, `(3 − d) / 2`, not `sqrtf`. At 6 µs per
  `sqrtf` across ~10,000 samples that is most of the bake.
- `acos` costs several `sqrtf` and is needed per sample, so it is a 257-entry
  table of theta against z.
- Gaussians are Irwin-Hall over 8 uniform draws. Box-Muller would need a
  `logf` and a `sqrtf` per deviate.

Coverage is Q8 where **256 means full**, so it cannot go straight into a
`uint8_t`: `(uint8_t) 256` is 0, and every vessel at full coverage vanishes.

Brush radii are in **texels, and the floor is 0.75**, because a texel centre can
sit up to 0.707 texels off the track and a narrower brush leaves gaps however
densely the curve is sampled. Every branch tip in the model wants 11 to 42
percent of trunk width, all under that floor, so they all clamp to the same
value — which means **the trunk has to clear the floor too or branches come out
thicker than trunks.**

`tools/vessel/render.py` takes optional argv `SIDE TRUNK_PX [OUT]` because the
question that matters is how many *texels* wide a trunk is, not how many pixels.

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
- **`tools/vessel/render.py` and `vessel.py` are verified against the C++ by
  eye, not automatically.** The rig's numbers and the firmware's are produced by
  the same ideas transcribed twice, so a transcription slip is invisible to
  both. Three bugs survived a clean compile and were caught only by dumping the
  baked texture and looking at it: longitudes never accumulated from gaps (all
  19 trunks fanned out of one point), the Q8 coverage overflowed `uint8_t`, and
  the Q12 spline above. **When the bake changes, dump it and look.** The harness
  lifts the C++ out of `eye-lambda.yaml` by text, so it cannot drift.
- **This is a soft-float build** — no FPU. Measured on target: `sqrtf`
  6000 ns, float multiply 1800 ns. The per-pixel loop is integer for
  performance, not style.
- **When modelling the renderer offline, replicate the C++ integer path, not
  the float maths.** Float models missed the missing `>> 8` on the eye-local
  dot product and an `up`-vector sign error — two bugs that shipped.
  `tools/vessel/` follows this: orthographic, matching `INV_R_Q8`.
- **A check that reuses the predicate it is testing cannot fail.** The ring
  packing was verified by walking the ring with the same membership test the
  firmware used, and it passed a layout that dropped a texel column. Verify an
  index against something independent of it — here, plain geometry
  (`R_IN² ≤ r² ≤ MID²`, integer centres) — and report missing, extra and
  colliding texels rather than a pass/fail.

## Deliberate constraints — do not "fix" these

Each looks wrong and is not. `eye-device.yaml` documents the reasoning
in full; this is the short version.

- **No `wifi`, `api`, `ota`, `captive_portal` or `mdns`.** Not an oversight.
  A full-frame display buffer needs one contiguous 115,200 B block. With the
  network stack resident, free heap was 75,856 B — *below* the request — and
  the largest block was 61,440 B. Removing WiFi freed enough for the buffer.
  Cost: no Home Assistant. Flashing is USB, and logging runs on
  `USB_SERIAL_JTAG`, which is independent of WiFi. `secrets.yaml` keeps
  `api_encryption_key`/`fallback_ap_password` for the day that is revisited —
  which is why it is unreferenced but not deleted.
- **`data_rate: 80MHz`, not 40MHz.** GC9A01A defines no default, so it falls
  back to 10 MHz, where a full-screen push tears visibly down the panel. There
  is nothing between 40 and 80: from ESPHome's 80 MHz SPI source, divisor
  rounding accepts only 20, 40 and 80 MHz.
- **`buffer_size: 1.0` is correctness, not speed.** `mipi_spi` draws in
  horizontal bands and never calls `set_clipping()`, so `get_clipping()` is
  always unset and the lambda cannot tell "first band" from "only band". At
  any smaller buffer the gaze state machine advances once per *band*, so every
  `GAZE_*` constant runs at the wrong speed.
- **`update_interval` must match between `eye-sandbox.yaml` and
  `eye-device.yaml`** (both 90 ms). The `GAZE_*` constants count *frames*,
  not milliseconds, so this is the one timing parameter the shared files do
  not cover — it drifted once already.
- **`auto_clear_enabled: false`** is set on both. Harmless: the renderer
  repaints every frame and calls `it.fill()` itself.

## Testing

There is none. Verification is: `esphome config` (both files) → `esphome
compile` (both) → look at the SDL window → user flashes and reports. Ask for
the boot log from the top; the display banner prints *requested* buffer sizes,
so a successful allocation is proven only by the **absence** of
`[E][component:143]: display is marked FAILED: Buffer allocation failed`.

**Ask what the panel shows; the log cannot tell you.** There is no log line for
"the vessels look right", and every claim in this file about appearance came
from the user's eyes. The bake does log its own duration
(`[I][eye]: vessels baked in NN ms`), which is the one thing worth watching for
regressions.

## Conventions

Commits are imperative-subject with a body explaining *why*, and a `Fix:`
prefix for bug fixes.

**Comments: be brutal.** Keep only what stops a future edit from introducing
a bug — constraints and their consequences (the `-cyw*spt` sign, the `>> 8`
after a Q8 dot product, Q8 not fitting a `uint8_t`, `#if` not a runtime bool,
soft-float). Delete everything else:
changelogs, "that was a bug" stories, rationale for code that no longer
exists, and derivation of numbers already recorded elsewhere. A comment
describing a *past* state of the file is worse than none, because it reads
as current. If a comment and the code disagree, one of them is wrong — find
out which before believing the comment.

Keep `eye-device.yaml`'s header comment in sync when behaviour changes; it is
the only place several of the constraints above are justified.
