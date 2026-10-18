# A second eye — plan, not implemented

**Status: DESIGNED, NOT BUILT.** Nothing in this file exists in the firmware. The
repo has one panel and one eye. Everything below was checked against ESPHome
2026.9.1 and a throwaway config, not against hardware.

This lives in `docs/` rather than in `AGENTS.md` on purpose. `AGENTS.md`
describes what the code *is*. A plan written there would read as current state,
which is the specific failure its own conventions warn against.

## What it is

A second 240×240 GC9A01A panel on the same SPI bus, driven by the same renderer,
moving in relation to the first.

Decisions already made:

| question | answer |
|---|---|
| hardware | a second 240×240 round panel |
| gaze | one shared target, independent saccade timing and tremor per eye |
| presence | shared — both eyes react to the one radar signal, as now |
| structure | one config, two `display:` entries; the sandbox stays one-eyed |
| wiring | everything shared on the bus except CS |

## Wiring

One SPI bus. **Only CS differs between the panels.**

| signal | pin | pad |
|---|---|---|
| CLK | GPIO4 | 7 |
| MOSI | GPIO1 | 4 |
| DC | GPIO6 | 9 |
| RST | GPIO2 | 5 |
| **CS eye 1** | **GPIO5** | 8 |
| **CS eye 2** | **GPIO7** | 10 |

One new pin. GPIO7 is free and safe: not a strapping pin, not USB, not flash,
not JTAG, not the RGB LED. GPIO8 and the rest stay spare.

## ESPHome rejects shared pins until told otherwise

This is the one thing that is not obvious, and it was verified by trying all three
cases.

```
display.mipi_spi:  Pin 6 is used in multiple places.
```

The rule is in `esphome/pins.py`, checked **per pin entry**:

```python
if count != 1 and not allow_others:   raise "used in multiple places"
if count == 1 and allow_others:       raise "incorrectly sets allow_other_uses: true"
```

So:

| `allow_other_uses` | result |
|---|---|
| on neither display | fails |
| on one display only | **fails** — the other entry still trips the first check |
| **on both displays** | passes |

Both shared pins, DC and RST, carry the flag on **both** display entries. It
reads oddly, since the name suggests the first user is opting out, but the check
is per entry and one flag is not enough.

## Why sharing DC and RST is safe here

Two facts from the ESPHome source, because this is the part that could look wrong:

- **`write_to_display_` re-sends `RASET`, `CASET` and `WDATA` on every push.**
  `mipi_spi.h` lines 365–368 issue them inside `write_to_display_`, which runs per
  frame. The long init sequence is setup-only, so a reset pulse from the second
  panel's setup does not leave the first panel unconfigured.
- **DC only carries meaning while CS is low.** Only one panel is selected at a
  time, so one D/C line is unambiguous.

The cost is diagnostic: a wedged panel cannot be reset without taking the other
one down.

## Memory: both buffers must land in PSRAM

| | bytes |
|---|---|
| one frame buffer | 115,200 |
| two | 230,400 |
| PSRAM free, measured | 1,977,568 |
| PSRAM free after two | 1,747,168 |

The failure case matters more than the success case:

| scenario | internal free left |
|---|---|
| both buffers in PSRAM | 212,452 (unchanged) |
| one in internal, one in PSRAM | 97,252 — probably survivable |
| both in internal | **−17,948 — fails** |

**CHECK `PSRAM free` in the debug sensors after the first flash.** It should
read about **1.86 MB**. Near **2.0 MB** means a buffer went to internal RAM
instead, and the second one will not fit.

## SPI budget

| | ms |
|---|---|
| one full-frame push at 80 MHz | 11.5 |
| two per frame | 23.0 |
| `update_interval` | 90.0 |
| headroom before any lambda work | 67.0 |

Comfortable. This is the real constraint on two eyes, and it is not close.

## The baked textures cost nothing per eye

`IRIS_TEX` and `VEIN_TEX_F` are function-local **`static`** arrays in
`eye-render.cpp`. A second eye **shares the same bake**: zero extra bytes, one
bake time, and identical vessels in both eyes.

## The renderer change

Shared target, independent timing — one structural decision, and it is the whole
character of the thing.

| shared | per eye |
|---|---|
| `yaw_t`, `pitch_t` — one place both eyes look at | `yaw_s`, `pitch_s` — own saccade start |
| `presence`, `pres_f`, `pres_hold`, `pres_seen` | `gmove` — own saccade length |
| `demo`, `hue`, `pupil_w/h`, `vein_tint`, `jitter` | `frame` — own tremor phase |
| | `yaw`, `pitch` — own current gaze |

The current flat pointer list becomes an `EyeGaze` struct, passed one per eye.
`EyeLook` and the presence pointers stay as they are.

## Files

| file | change |
|---|---|
| `eye-globals.yaml` | split the gaze globals per eye; `yaw_t`/`pitch_t` stay single |
| `eye-device.yaml` | second `display:` entry, `cs_pin: GPIO7`, shared DC/RST with `allow_other_uses` on both |
| `eye-render.cpp` | `EyeGaze` struct; per-eye interpolation against the shared target |
| `eye-look.h` | signature follows the struct |
| `eye-sandbox.yaml` | per-eye globals exist; draws one eye only |
| `AGENTS.md` | the shared-bus wiring and the flag rule, once it is real |

## What must not change

- **`buffer_size: 1.0` on both.** Not a speed setting: `mipi_spi` bands below a
  full buffer and calls the lambda once per band, and the renderer cannot tell
  the difference because `mipi_spi` never calls `set_clipping()`. The gaze
  machine would advance per band.
- **`update_interval: 90ms` on both, and equal to the sandbox.** `GAZE_*` counts
  frames, so the two eyes must see the same rate.
- **`frame++` outside any demo gate, for both eyes.** It drives tremor *phase*;
  gating it gives a fixed offset instead of a shimmer, with no error.

## Open risks, unmeasured

1. **Drift between the two timers.** Each display has its own `update_interval`,
   so the eyes may wander apart over hours. If that shows, the fix is to drive
   both from one interval — more work than it sounds.
2. **Which core each display runs on.** The S3 is dual-core and ESPHome puts
   displays on separate tasks, so the second core probably absorbs the second
   eye. Unverified.

## Before starting

The current firmware is flashed and reported working. Build this on top of a
known-good baseline, so a wrong-looking eye is unambiguously the new panel rather
than leftover work.