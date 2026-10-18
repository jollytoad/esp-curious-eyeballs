# A Lovelace card — plan, not built

**Status: DESIGNED AND PROVEN IN PART, NOT BUILT.** Nothing in this file exists in
the firmware or in Home Assistant. The WASM approach below was compiled and run
during design, and the numbers in it are from that run. The card, the shim and the
build script do not exist yet.

This lives in `plans/` rather than in `AGENTS.md` on purpose, for the reason
`plans/two-eyes.md` gives: `AGENTS.md` describes what the code *is*, and a plan
written there reads as current state.

## What it is

A Home Assistant dashboard card that shows the eye and drives it. The eye is not a
picture and not a re-implementation. It is `eye-render.cpp`, compiled to WebAssembly
and run in the browser, so the card and the panel come out of the same source file.

Decisions already made:

| question | answer |
|---|---|
| renderer | `eye-render.cpp` compiled to WASM, never transcribed to JS |
| delivery | HACS, one JS file at the repo root |
| what the card renders | the manual look only: demo off, `pres_f` pinned to 0 |
| gaze input | relative drag on the eyeball |
| vessels | baked in the browser at load; nothing embedded |
| presence | not in the card. No entity drives it, and `eye-presence.yaml` is the only writer |
| firmware | unchanged. The renderer is compiled, not edited |

## The renderer is compiled, not ported

The first version of this plan transcribed the per-pixel loop into JavaScript. That
was about 300 lines, and it was the only part of the plan that could disagree with
the device. Compiling the C++ removes the disagreement.

`eye-render.cpp` already has the right shape for it. It is a translation unit that
takes its state through pointers, and the only ESPHome surface it touches is small:

```
esphome::Color, display::Rect, display::Display with
fill / draw_pixel_at / get_clipping, random_float, random_uint,
random_uint32, millis, and the ESP_LOGx macros
```

`.tmp/eye-shot/esphome.h` already stands in for all of that on the desktop. The WASM
build needs a second stand-in, because `millis()` there uses `<chrono>` and the log
macros use `printf`, neither of which exists in a freestanding module.

## What was measured, and how

Measured on the development machine, as a smoke test. Not a verified build.

| | |
|---|---|
| compiler | `zig c++ -target wasm32-wasi-musl`, zig 0.17.0 |
| module, stripped | 22,203 B |
| module, with the two named exports | 27,297 B |
| as base64 inside one JS file | about 36 KB |
| imports | 6 WASI functions, all stubbable with no-ops |
| first frame, including both bakes | 4 ms |
| steady frame, 57,600 pixels | 1.1 ms |

The rendered frame was written out as a PPM and looked like `docs/eye-rest.png`.

### Why zig and not the Homebrew clang

`/opt/homebrew/opt/llvm/bin/clang++` has the wasm32 backend. It has no libc++
headers for wasm32, so `#include <cmath>` fails, and `eye-render.cpp` includes
`<cmath>` and nothing else. Zig ships both the headers and `wasm-ld`, so one
command does the whole job.

An alternative is to declare the handful of maths functions by hand, which drops the
libc++ requirement and turns `sinf`, `cosf`, `acosf` and `fmodf` into JS imports.
That was not tried. Do not assume it is simpler.

### Why the module imports six WASI functions and calls none of them

`zig c++ -target wasm32-wasi-musl` links musl statically, and the C runtime drags in
`args_get`, `args_sizes_get`, `fd_seek`, `fd_write`, `fd_close` and `proc_exit`.
The shim's log macros are no-ops, so nothing is ever printed and none of the six is
ever called. The card supplies six functions that return zero.

All the float maths the renderer uses — `sinf`, `cosf`, `acosf`, `sqrtf`, `floorf`,
`fmodf`, `fabsf`, `fmaxf`, `fminf` — links statically. Nothing comes from JS.

## The shim

`tools/wasm/`, committed, because the card is a shipped artefact. This is different
from `.tmp/eye-shot/`, which is gitignored and gone on a clean checkout: a card
nobody can rebuild is worse than a picture nobody can rebuild.

Two files:

- `esphome.h` — `Color`, `Rect` whose `is_set()` returns false, `Display`,
  `random_uint`, `random_uint32`, `random_float`, `millis`, and the log macros as
  no-ops. **No `<chrono>`, no `<cstdio>`, no `<cmath>`.** The one include that must
  resolve is `<cmath>`, which zig provides.
- `eye-wasm.cpp` — the `Display` writes straight into a linear RGBA buffer, with no
  call back into JS. A deterministic LCG stands in for `random_uint32`, so a seed
  pins the vessel bake. A bump allocator hands out the pixel buffer.

### The allocator must not depend on the link layout

**Every pointer across the boundary is `.byteOffset`, never the typed array.** The
C signature takes an `i32`. Passing an `Int32Array` coerces to `0`, and the renderer
then writes its frame counter to address 0. It does not throw, and the picture still
looks right. This was hit during the smoke test: the tremor counter stayed at zero
and the tremor never moved.

For the same reason the bump allocator lives in a fixed `static` array inside the
shim, not at `__heap_base`. Nothing about the buffer's address may depend on where
the linker put things.

### The exports

```c
extern "C" {
  void eye_alloc_init(void);
  int  eye_alloc(int bytes);                 // 16-byte aligned, returns a byte offset
  void eye_init(int px_ptr, int w, int h);   // the RGBA buffer, once
  void eye_seed(uint32_t s);                 // before the first frame: pins the bake
  void eye_frame(float demo, float yaw, float pitch, float jitter,
                 float hue, float pupil_w, float pupil_h, float vein_tint,
                 int frame_ptr, int presence);
}
```

`eye_seed` is only read on the first frame, because the renderer bakes once per
process. A different seed means a reload. The demo page puts the seed in the URL and
reloads.

## The build

`tools/wasm/build-wasm.sh`, one command:

1. compile `eye-render.cpp` and the shim to wasm32, stripped, with sections
   garbage-collected and only the two exports named
2. base64 the result
3. rewrite the marked block in `eye-card.js`
4. print the SHA-256 of `eye-render.cpp` next to the hash already in that block

`ZIG_GLOBAL_CACHE_DIR` and `ZIG_LOCAL_CACHE_DIR` point inside the workspace, the same
way `run-device.sh` and `run-sandbox.sh` move `HOME`. Zig otherwise reaches for
`~/.cache/zig`, which this machine does not allow.

The module is inlined as base64 in `eye-card.js` rather than shipped beside it, so
HACS still installs one file and there is no relative path to get wrong. The cost is
one machine-written line in a diff.

## One file, two hosts

`eye-card.js` carries no `import` and no `export`. Everything attaches to `window`.
That is what lets the same file load twice:

- as a Home Assistant **module** resource, and
- as a classic `<script>` from `file://`, which browsers refuse for module scripts.

**A module's top level is not global.** Anything the demo page needs must be
attached to `window` explicitly, not merely declared.

Inside it:

| part | knows about |
|---|---|
| `window.EyePreview` | the canvas, the drag mapping, the clamps, the module, the 90 ms tick, the render |
| the Lovelace card | entities, sliders, the demo bar, service calls |

`EyePreview` takes plain numbers and calls back on change. It contains no `hass`, no
service call and no entity lookup, so there is nothing in it that could reach a
device. The coupling is one-way by construction, not by convention.

The slider markup exists in both hosts on purpose. The card reads its bounds from the
entity attributes and the page uses fixed ones, so sharing them would mean sharing
bounds they do not have in common. The slider is a native range input either way.

## The card

```yaml
type: custom:eye-card
eye:
  demo: switch.eye_demo_mode
  yaw: number.eye_gaze_yaw
  pitch: number.eye_gaze_pitch
  hue: number.eye_iris_hue
  vein: number.eye_vein_opacity
  pupil_w: number.eye_pupil_width
  pupil_h: number.eye_pupil_height
  jitter: number.eye_jitter
  randomize_vessels: false
```

Every id is overridable. The defaults are what ESPHome generates from
`friendly_name: Eye`, which is right until the device is renamed.

**The eye is 240×240 and renders at 240×240.** The default display size is 240 CSS
pixels, so what you see is the panel's own pixels one to one. Enlarging it enlarges
a 240 pixel image, which is honest rather than clever.

**The tremor ticks every 90 ms**, the same as `update_interval`. About 11 tremor
steps a second, which is what the panel does. Redraws during a drag happen at once,
so the card still feels immediate.

### Drag is relative

Press anywhere on the eyeball. The iris then moves with the drag rather than jumping
to the finger:

```
yaw   = clamp(yaw_at_press   + dx / radius * 180 / PI, -52, 52)
pitch = clamp(pitch_at_press + dy / radius * 180 / PI, -38, 38)
```

57.3 pixels of drag is one degree, scaled to the rendered radius. The clamps are
`YAW_MAX` and `PITCH_MAX` from `eye-render.cpp`, and they are the same clamps the
renderer applies, because they are what keeps the iris on the globe.

The linear drag delta keeps the iris under the finger at small angles and slightly
ahead of it near the rim. The alternative, inverting so the iris lands exactly under
the finger, puts a hard stop inside the reachable disc. Linear was chosen; that is a
judgement, not a measurement.

### Writes

`number.set_value` for all seven numbers, throttled to 12 Hz, with one final write
when the gesture ends. The card keeps local state during a gesture and adopts the
Home Assistant state otherwise, so an echo cannot fight a drag. The entities are
`optimistic: true`, so the state comes back at once.

### The demo bar

While `switch.eye_demo_mode` is on, the panel ignores every one of those numbers. The
card says so, dims the controls, and offers a button that turns demo off. It still
renders the manual look, so a pose can be set up before it is handed to the panel.

## The demo page

`tools/wasm/demo.html`, committed. It is for testing and fine tuning, and it does not
control the device — there is no path from that page to one.

It loads `eye-card.js` as a classic script, so it needs no server and no build step.
Double-click it. If a browser ever refuses, `python3 -m http.server` in the repo root
is the fallback.

| on the page | why |
|---|---|
| the eye, plus 1× 2× 3× nearest-neighbour zoom | a texel is the unit of tuning |
| a checkbox drawing the yaw and pitch limit ring | the clamps are otherwise invisible |
| drag, plus number fields for yaw and pitch | you want to type 38, −14, not drag there |
| hue, vein tint, pupil width, pupil height, jitter | the renderer's manual inputs |
| demo and presence switches | local rendering only, for comparing against `docs/` |
| four presets: rest, away, alert, away-alert | lines the card up with the README pictures |
| both build hashes | tells you which build you are looking at |
| bake and frame timings | a regression in either is a number, not an opinion |
| a vessel seed in the URL, and a button that reloads with a new one | the bake runs once per load |
| save the current frame as a PNG | compare with the panel by eye |
| values kept in local storage | a reload must not lose the tuning |

## How it is checked

1. `node --check eye-card.js`.
2. `tools/wasm/check-wasm.mjs` runs the shipped module in Node, renders the rest and
   away poses, writes a PPM for each, and prints the bake and frame times.
3. If `.tmp/eye-shot/shot` is present, diff those frames against the same two from
   the desktop build of `eye-render.cpp`. Expect agreement except where musl and
   newlib disagree on `sinf` and `acosf` by an ulp. **This harness is stale**: it
   still calls the 14-argument `eye_render` and has to be given an `EyeLook` before
   it will work.
4. Open `tools/wasm/demo.html` from `file://` and look at it.

There are no tests and no CI in this repo, and this does not add any.

## Open risks

1. **Not bit-identical to the panel.** Same source, different libm: musl in the
   module, newlib on the device. Visually nothing. Do not claim a zero-delta diff.
2. **The committed base64 can go stale.** The build script prints the renderer's
   hash beside the one in the file, so it is visible without a diff. Nothing
   enforces it.
3. **WASM stack traces are opaque.** Mitigated by `check-wasm.mjs`, which renders in
   Node and writes a picture, so a bad frame can be looked at without a browser.
4. **`EyePreview` in Node.** It owns a canvas. Whether it drives cleanly under
   `check-wasm.mjs` is unmeasured. If it is awkward, that harness keeps calling the
   module directly and only the page uses the shared widget.
5. **Entity ids follow `friendly_name`.** The defaults in the card match the current
   config. Renaming the device in Home Assistant changes them, which is why every id
   is overridable.

## Files

| file | change |
|---|---|
| `tools/wasm/esphome.h` | new: the freestanding shim |
| `tools/wasm/eye-wasm.cpp` | new: the Display, the LCG, the allocator, the exports |
| `tools/wasm/build-wasm.sh` | new: compile, inject, report the hash |
| `tools/wasm/check-wasm.mjs` | new: run the shipped module, dump frames and timings |
| `tools/wasm/demo.html` | new: the standalone page |
| `eye-card.js` | new, at the root: `EyePreview` and the Lovelace card |
| `hacs.json` | new, at the root |
| `README.md` | install steps and a layout row |
| `AGENTS.md` | file roles, the build command, and the `.byteOffset` trap |

`eye-render.cpp`, `eye-look.h`, `eye-globals.yaml` and both YAML configs are not
touched. Nothing here costs the device a byte.

## What must not change

- **`eye-render.cpp` is compiled as it is.** If the WASM build needs a change, the
  firmware needs the same change. Do not fork the renderer for the browser.
- **`Rect::is_set()` returns false in the shim.** That is what a full-frame buffer
  looks like, and it is what puts the renderer on its `first_band` path — the same
  one the device takes. A shim that returns true changes the behaviour being shown.
- **`update_interval` is 90 ms on both targets and the tremor tick is 90 ms in the
  card.** `GAZE_*` counts frames, so this is the one timing the shared files do not
  cover.

## Before starting

The manual look was flashed and reported working. Build on top of that, so a
wrong-looking eye is unambiguously the card and not leftover firmware work.