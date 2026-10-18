# AGENTS.md

ESPHome config repo for an animated eye on a 240×240 round panel. The renderer
is one real C++ file plus two YAML configs and a YAML globals file; there are no
tests, no CI, and no build/lint manifests. `tools/vessel/` is a Python model
used to choose renderer parameters — it never ships.

## Files

| file | role |
|---|---|
| `eye-render.cpp` | the entire renderer — `eye_render()`, shared by both targets |
| `eye-look.h` | the `EyeLook` struct and the declaration of `eye_render()`, shared by both targets |
| `eye-globals.yaml` | shared animation state (`globals:` block) |
| `eye-presence.yaml` | shared presence driver, the only writer of `presence` on both targets |
| `eye-device.yaml` | the real hardware config |
| `eye-sandbox.yaml` | local SDL simulator (`host:` platform, macOS) |
| `secrets.yaml` | gitignored — wifi credentials and the fallback AP password; `api_encryption_key` waits for its gate |
| `run-sandbox.sh` | launches the simulator with the right env |
| `run-device.sh` | builds and flashes the device with the right env |
| `tools/patch-scons-darwin.sh` | idempotent SCons fix, required before builds |
| `tools/vessel/render.py` | offline vessel rig — run this for `.tmp/sphere.png` (shape) and `.tmp/panel.png` (size) |
| `tools/vessel/vessel.py` | the model itself; only `render.py` should import it |
| `tools/vocabulary.py` | draws `docs/eye-parts.png` from the constants below — re-run it if you change one |
| `docs/eye-parts.png` | the labelled diagram this section describes |
| `docs/eye-rest.png`, `docs/eye-away.png`, `docs/eye-alert.png`, `docs/eye-away-alert.png` | the 2x2 of gaze and presence, for the README |

`presence` and `pres_f` in `eye-globals.yaml` are the presence response. **No
sensor is wired up**: `eye-presence.yaml` drives `presence` on both targets, so
the eye can be seen reacting on the panel as well as in the window. The renderer
eases `presence` into `pres_f` and owns every visual change, so a real sensor
added later replaces the contents of that one file and nothing else changes.
Nothing outside the renderer may touch the pupil or the iris directly.

`eye-render.cpp` is named under `esphome: includes:` in **both** configs. A
`.cpp` there is copied to `src/` and compiled, but — unlike a `.h` — it is
**not** `#include`d into `main.cpp`, so a separate translation unit needs a
declaration of `eye_render`.

**That declaration lives in `eye-look.h`, which is also under `includes:`.** A
`.h` there *is* on the include path of both `main.cpp` and `eye-render.cpp`, so
one declaration serves both and the lambdas carry only a call. This replaced two
hand-written forward declarations, one per config, and it retires a real hazard:
those listed types only, so **the order of the fourteen arguments had to match
`eye-render.cpp` by hand** and a swap compiled fine, failing as a confusing
`cannot convert 'float * to 'int *'` some lines away.

**Keep it that way.** Adding a parameter means editing `eye-look.h`, never the
lambdas. If a `.cpp` is ever listed in `includes:` expecting `main.cpp` to see
it, it will not be.

One thing still true in the lambda: `id(yaw)` already expands to a reference, so
`&id(yaw)` is the `float *` the function wants — `->value()` is wrong there.

## Regenerating the README pictures

`docs/eye-*.png` are NOT screen captures. They are the real `eye-render.cpp`
compiled headless and run four times — gaze centred or averted, crossed with
calm or alert — which is why they share one vessel bake and match each other.

The renderer needs only a small slice of ESPHome — `Color`, `Rect`,
`random_float`/`random_uint`/`random_uint32`, `millis`, the `ESP_LOGx` macros,
and a `display::Display` with `fill`/`draw_pixel_at`/`get_clipping`. Stubbing
that is enough to link the real renderer offline. A scratch `esphome.h` and
harness live in `.tmp/eye-shot/` and are gitignored, so **they are gone on a
clean checkout** — regenerate them or the pictures cannot be rebuilt.

**The harness must now pass an `EyeLook` as the last argument.** Build one with
`demo = 1` and the authored rest values for every other field — that is what
reproduces the pictures the way they were made. `demo = 0` would hold the gaze
and ignore presence, and none of the four frames would match.

The gaze is pinned by setting `gmove = 0` and a huge `ghold`: the machine then
only decrements `ghold`, so it never picks a target and never touches yaw or
pitch. Letting it run instead photographs a lucky saccade. The averted pose is
yaw 38, pitch −14 — inside `YAW_MAX` 52 and `PITCH_MAX` 38, so the iris stays
on the globe.

All four frames share one seed, one gaze and one tremor frame. The alert frames
ease `pres_f` to 1.0 through the real code path rather than being forced, which
is the only way to know the renderer produces that picture rather than the
harness.

`Rect::is_set()` must return **false**. That is what a full-frame buffer looks
like, and it is what puts the renderer on its `first_band` path — the same one
the device takes. A shim that returns true silently changes the behaviour being
photographed.

## Vocabulary

**Three spaces, and the renderer switches between them without saying so.** Most
of the confusion that has cost real time here was vocabulary, not arithmetic.
`docs/eye-parts.png` draws both of the first two side by side.

| space | origin | extent | appears as |
|---|---|---|---|
| **screen** | top-left of the panel | 240×240 px, x right, y down | `CX` `CY` `R` `CORNEA_X/Y` |
| **globe** | the eye's own axes | a unit normal; `theta` 0..180, `phi` 0..360 | `ldx` `ldy` `along` `theta` |
| **texture** | each texture's centre | texels | `VEIN_TEX_*` `IRIS_TEX_*` |

`theta` is the polar angle from the eye's **forward** axis: 0 is straight at the
viewer, 30 is the limbus, 90 is the silhouette. `along` is the forward component
of the normal, and it is the **only** thing that distinguishes a point from its
antipode — both project to the same texel.

The two texture grids use the **same scale factor and different centres**, which
is the easiest thing in the file to get wrong:

```
vessel ring :  centre VEIN_TEX_MID = 96,  grid 193,  ring r = 48..96
iris texture:  centre IRIS_TEX_SIDE/2 = 48,  grid 97,  used to r = 48 only
```

The iris texture's outer half is dead. That is tuned, not broken: the iris spans
`theta < 30`, and `sin(30°) × IRIS_TEX_SCALE = 48` exactly.

### Landmarks in texture space

Say **axis**, never "centre". The texture axis is at `x = VEIN_TEX_MID = 96`;
the screen centre is at `x = CX = 120`. Conflating them cost an hour on the
seam bug.

| name | value | what it is |
|---|---|---|
| **axis** | texel `(96, 96)` | the point the eye looks straight at |
| **axis column** | `x = 96` | where the seam bug was |
| **limbus radius** | `VEIN_R_IN = 48` | `theta = 30`, the inner edge of the ring |
| **horizon radius** | `VEIN_TEX_MID = 96` | `theta = 90`, the silhouette, the outer edge |

### One row of the packed ring

```
      |<--- left half --->|<--- right half --->|
r=0   offset 0 .. wo-hwi   offset wo-hwi+1 .. span-1
|dx|  wo .. hwi            hwi .. wo

when hwi == 0 the halves MEET at x = 96: the row is 2*wo+1 texels,
and the right half starts at |dx| = 1 - hence `hwi ? hwi : 1`.
```

The row index build walks rows **top to bottom**, not by `|dy|`: the row above
centre and the row below it are different rows with different spans, and
walking by `|dy|` gives them one shared offset.

## Pupil

The pupil is a compile-time **ellipse**, not a circle. `PUPIL_W` and `PUPIL_H`
are fractions of the iris radius; equal values give the round pupil. They are
eye-local, so a slit turns with the gaze — only the catchlight and the lids are
screen-fixed. Set one, rebuild, look. There is no runtime switch: the board has
no api and no wifi, so nothing could write one.

**The pupil decides only where the black starts. The iris gradient stays
circular whatever the pupil is.** It is measured on `across8`, the cap radius,
never on `ldx`/`ldy`. An ellipse gradient reads as a distorted iris rather than
as a slit in one, and it looked wrong before anyone asked why. A slit has no
single edge for a circular gradient to start from, so the ramp starts at
`PUPIL_MEAN`, the mean of the two half-extents. At 0.50/0.50 that is `PUPIL_HX`
and the round pupil is bit-identical to before.

**Two pupil tests exist and both stay.** The round one tests `across8 < PUPIL_HX`,
the ellipse tests `ldx`/`ldy` through `q`. `PUPIL_ROUND` is a runtime `const
bool` and **must not go back to an `#if`**: the radar makes the pupil round only
while the room is empty, which is not a build-time property. The round path is
not the fast one — it is the one the verified look was tuned on, and it now has
to stay reachable at run time.

**The pupil is runtime, so the floor at 1 is what keeps a narrowing pupil safe.**
`hx` and `hy` are interpolated by `pres_f` between `PUPIL_*_REST` (round, large)
and `PUPIL_*_PRES` (narrow vertical slit). The ellipse test grows as `1/hx²`,
so closing the pupil is the direction that could overflow `q`. On the cap
`ldx² + ldy² ≤ 16252`, so `q ≤ 65536 × 16252 / 1 = 1.06e9` — under int32 — but
**only because the floor keeps `hx` and `hy` at 1 or above.** Both feed a
reciprocal; a zero axis would make `EYE_RECIP` return 1 and the picture wrong.

**The presence response costs nothing per pixel.** `IR_R/G/B` and the four
fibre channels are lerped on `pres_f` *before* the pixel loop, and `hx`/`hy`
were already hoisted, so the whole feature is a handful of multiplies per
frame. The colour lerp and the pupil half-extents are all hoisted, so a real
sensor costs a few multiplies per frame and nothing per pixel.

**Six parameters blend on `pres_f`, not five.** `VEIN_TINT` is the sixth: the
baked vessel coverage is scaled by it before the blend toward `VEIN_COL`, so at
`VEIN_TINT_REST` a *fully covered* vessel pixel goes `(240,240,235)` to
`(234,208,203)` — a pale pink — and most are not fully covered, so it reads as
barely there. The vessels still cost the same to store; only the tint changes.

**At full presence the eye is NERVOUS, and that is five parameters, not one.**
`GAZE_FRAMES`, `GAZE_HOLD_MIN`, `GAZE_HOLD_MAX`, `GAZE_STARE_CHANCE` and
`TREMOR_DEG` each have a `_REST` and a `_PRES` value, all blended on the same
`pres_f` that drives the colour and the pupil. So the saccade halves
(4 frames to 2), the hold drops from 0.7-5.0 s to 0.2-1.2 s, the chance of a
long stare falls from 30% to 5%, and the tremor quadruples (0.30 to 1.20
degrees). Costs **0 bytes** — it is constants that were already there, duplicated
into pairs.

**`t` in the saccade MUST stay clamped to 0..1.** `gaze_frames` SHRINKS as
`pres_f` rises, so a saccade started at 4 frames and then measured against 2
gives `t = -0.5`, and `smoothstep` of a negative is a large *negative* — the eye
snaps backwards past its start on the way to the target. There is no error and
no log line; it is only visible.

**The tremor FREQUENCIES are not blended, only its amplitude.** `TREMOR_W1/W2`
sit below Nyquist for the frame rate on purpose. Raising them with `pres_f` to
get "more jitter" would push past what the frame rate can carry and alias into a
slow visible beat instead of shaking.

**The presence block runs BEFORE the gaze machine, not after.** The gaze reads
`pres_f`, so it must see this frame's eased value rather than last frame's.

**The eye ignores a presence change for 5 to 15 s before it starts moving.**
`PRES_DELAY_MIN`/`PRES_DELAY_MAX` are FRAMES, not seconds, for the same reason
`GAZE_FRAMES` is: `update_interval` is the one timing parameter the shared files
do not cover. A change sets `pres_hold` to a random value in that range and the
easing does not begin until it reaches zero, so the eye is slow to notice
rather than flinching at every flicker. A change that reverts first restarts the
hold instead of being reacted to, and one that returns to where `pres_f` already
sits expires with nothing to do.

**Anything driving `presence` MUST wait for `pres_hold` to reach 0 and `pres_f`
to reach its target before changing it again.** Flipping the input faster than
the hold expires restarts the hold every time and the eye never moves at all —
no error, no log line, just an eye that sits still. `eye-presence.yaml` checks
both conditions every second; that is why its interval is 1 s and not the delay
itself. It is shared by both targets for the same reason the renderer is: two
copies of a timing rule that has to match to the second will drift.

**The whole presence response costs 120 B: 108,656 → 108,776.** Four globals
plus the shared `interval:` block. The block is on the DEVICE, which the
`heap_caps_*` note above warns about, so it was measured rather than assumed —
and it is a plain tick with no heap call in it, which is the difference.

Three rules, each one edit away from a wrong picture or a crash:

- `qx = (ldx * PUPIL_RX) >> 8` shifts by **8, not 16**. `PUPIL_RX` is
  `65536 / PUPIL_HX`; shift 8 and `qx` lands on 256 exactly at the pupil edge,
  shift 16 and it lands on 1, so nothing is ever pupil.
- Clamp `d` to `PUPIL_SPAN` **before** multiplying by `RECIP_SPAN`, not `s8` to
  255 after. `RECIP_SPAN` is `65536 / PUPIL_SPAN`, so clamping `d` first bounds
  the product by `255 << 16` and leaves `s8` in range with no second clamp.
  Clamp to `PUPIL_SPAN` before 0, because a pupil wider than the iris makes
  `PUPIL_SPAN` negative.
- Both half-extents floor at **1**. That floor is load-bearing: it is what keeps
  `q` inside int32, since `q` tops out at 1.06e9 at the cap corner.

`.tmp/pupil_check.cpp` compares the round pupil against the pre-ellipse code
over every cap sample, then walks every angle of every cap radius to prove the
gradient takes one value per radius. It is gitignored and it went stale the day
this was written — fix it against the renderer before trusting it.

## Commands

```bash
# simulator (SDL window, no hardware)
./run-sandbox.sh

# device — the USER runs this; ask them, do not assume you can reach USB serial
./run-device.sh

# validate and compile the device without touching the hardware
./run-device.sh --config-only

# pin the transport, overriding the USB-then-OTA default
./run-device.sh --device /dev/cu.usbmodem2101
```

Both scripts do the same three things: set `HOME` so the pkgx/PlatformIO caches
stay inside the workspace instead of `~/Library/Caches`, prepend the
workspace-local toolchain to `PATH`, then run the SCons patch. **Both
`export`s matter**; `PATH` matters because the workspace toolchain's clang++
beats the dead `/usr/bin` C++ shims on this machine. Prefer the scripts over
calling esphome directly. Only `run-sandbox.sh` needs a window; `run-device.sh`
is the one that talks to USB.

`tools/patch-scons-darwin.sh` widens an `except FileNotFoundError` to `OSError`
in SCons' macOS probe; PlatformIO can undo it when it refreshes `tool-scons`,
which is why the script is idempotent and re-run by both wrapper scripts.

## Upload: USB first, OTA second, no prompt

`run-device.sh` passes `--device SERIAL --device OTA` unless the caller supplied
its own `--device`. That gets the "choose one" prompt out of the way, and the
mechanism is worth knowing because it is subtle:

- **`SERIAL` is skipped, not failed, when no port exists.** It resolves to
  whatever `get_serial_ports()` finds and is dropped from the list when that is
  empty. So unplugging the cable moves the upload onto the network.
- **`upload_program` then uses `devices[0]` only.** There is no retry down the
  list. The fallback is at *resolution* time, not at *attempt* time.
- **Logs follow the upload.** `command_run` re-resolves for logging with the
  device it just wrote to, so a USB flash logs over USB and an OTA flash streams
  over the API with the cable out.

One behaviour is left deliberately: `SERIAL` still prompts when **more than one**
serial port is plugged in. That prompt is correct — guessing between two boards is
how the wrong one gets flashed.

**USB can recover a board whose current firmware is broken; OTA cannot.** The two
transports have different failure modes, and that asymmetry is the real reason to
prefer USB when the cable is there: if a change bricks the running image, the only
way back is the cable, because OTA will not reach a device that no longer boots.
`safe_mode` rolls back to the last known-good image, but it cannot help if the
device is already wedged before it can serve an update.

## Verifying a change actually landed

`esphome config` passing proves nothing about the binary. Always check the ELF:

```bash
export HOME="$PWD/.tmp/home"; export PATH="$PWD/.tmp/toolchain/bin:$PATH"
.venv/bin/esphome compile eye-device.yaml
ELF=.esphome/build/eyeballs-1/build/firmware.elf
nm --print-size "$ELF" | grep NZ_LUT          # symbols, sizes
strings "$ELF" | grep <your format string>    # format strings
```

**The build directory follows the config `name:`, not the filename.** It is
`.esphome/build/eyeballs-1/`, because `eye-device.yaml` sets `name: eyeballs-1`.
The node name and `friendly_name` are separate: `friendly_name: Eye` is what Home
Assistant shows, and `name:` is the mDNS hostname and the API node name.

**Changing `name:` drops the device out of Home Assistant, and it is not a
rename.** Measured here, not assumed: renaming `esp32-s3-zero-a` to `eyeballs-1`
left the MAC alone (`90:da:72:47:df:d4`), changed the mDNS instance to
`eyeballs-1`, and made HA stop discovering it. The MAC is not the identity the
integration binds to — the node name is, and it is sent in every
`DeviceInfoResponse` alongside `friendly_name` and the MAC. The old entry keeps
matching an old name, so the device is invisible until that entry is deleted and
the device re-added. The `friendly_name` knob exists precisely so the name Home
Assistant shows can be changed without doing this.

The diagnosis when a renamed device vanishes from HA:

```bash
ping -c 1 eyeballs-1.local        # is it on the network at all
dns-sd -B _esphomelib._tcp local  # is it advertising, and under what name
arp -a | grep 192.168.8.211       # does the old name resolve to the same MAC
```

Advertising but not discovered means the HA entry, not the device. Note that a
**stale mDNS cache entry can outlive the rename** — the old instance name showed
in the browse output for a while after it stopped resolving, so do not read a
stale browse row as a second board.

Reading any leftover directory — `.esphome/build/eye-device/`, or the two names
this repo has used before, `esp32-c3-zero-a/` and `esp32-s3-zero-a/` — reports
stale symbols and makes a correct change look broken. If a build result
surprises you, confirm which directory you are reading before believing it.

## Memory: the one thing you cannot reason about

The frame buffer needs **115,200 B in one contiguous block**, and `Buffer
allocation failed` is the entire symptom. It produces a blank panel and one log
line.

**The frame buffer is in PSRAM. Measured, not modelled.** Read from the `debug`
sensors with the network resident, after boot settled:

| reading | value |
|---|---|
| PSRAM free | 1,977,568 B of 2,097,152 — **119,584 used** |
| internal free | 212,452 B |
| internal largest block | 163,840 B |
| internal min free | 198,976 B |

119,584 used against a 115,200 B buffer leaves 4,384 B of allocator overhead,
which is too tight a match to be coincidence. Every claim in this file that said
"should come out of PSRAM but nobody has proven it" was a guess, and it guessed
in the cautious direction.

**Two consequences, and the first one retires a whole section of this file.**

- **"Two vessel textures do not fit" is dead.** That was true on the C3 and it is
  the reason the renderer carries one array. The side 193 ring is 22,288 B, which
  is 0.11 percent of the PSRAM now free, so nothing about the vessel texture is
  memory-constrained here any more. The one-array design is now a **design
  choice, not a budget** — and `EYE_VEINS` in `eye-render.cpp` says so. Raising
  `VEIN_TEX_SIDE` is still pointless on its own terms: side 193 is finer than the
  panel resolves.
- **The largest internal block is 163,840 B**, which also exceeds the buffer. So
  the buffer would have fitted internally as well. PSRAM is simply where
  `RAMAllocator` put it, which is what it prefers. `CONFIG_SPIRAM_TRY_ALLOCATE_WIFI_LWIP`
  has never mattered on this board: the buffer left internal RAM with room to
  spare. It stays unset, and it is still the lever if internal RAM gets tight.

**Everything measured before the swap was the C3.** There, out of 400 KB of RAM
and no PSRAM at all, the largest block the heap would hand over was **114,688 B**
— 512 short. The bracket that mattered was **108,656 works, 119,696 fails**, and
the 11,040 B gap between them was never measured. None of that predicts the S3.
The `RAM:` line in the build output now counts internal RAM only, so it no
longer predicts the allocation either.

**What the network costs, measured gate by gate.** DIRAM is 341,760 B in one
pool. Link-time use:

| stage | DIRAM used | DIRAM free | cost |
|---|---|---|---|
| no network | 110,771 | 230,989 | — |
| `wifi:` + `captive_portal:` | 159,803 | 181,957 | **49,032** |
| + `api:`, `mdns:`, `ota:`, `button:` | 160,075 | 181,685 | 272 |
| + `debug` sensors | 160,283 | 181,477 | 208 |
| + `web_server:` | 160,571 | 181,189 | **288** |

**lwIP is 98 percent of the cost of having a network.** `api:` is 272 B, the
diagnostics are 208 B, and `web_server:` — which looked like the heaviest item on
the list by reputation and which I twice called the risk — is 288 B, the third
cheapest of the four. The expensive thing is the radio and its TCP/IP stack, not
the services on top. Anyone budgeting by "how many HA components" is measuring
the wrong quantity.

**Two ways to get this table wrong, both of which I did.** DIRAM `.text`
(58,711 B) is already inside the "used" column — subtracting it again reports a
false 8 KB of slack. And "DIRAM free" is not headroom: it is static allocation
only, while the wifi stack also allocates pbufs, driver buffers and task stacks
at run time. Measured at run time, internal free was **212,452 B**, which is
*above* the link-time free figure — the two do not agree even in sign. The C3
lesson was that nobody found an equation joining them; this board shows why.

**The relationship was not monotonic, and that lesson outlasts the numbers.**
79.4K worked, 79,584 failed, 103K worked again. There was no threshold, so *do
not model it*. Three models were built and all three were wrong, one of them
fitted to a table row that had been invented rather than measured. Compile,
flash, and read whether the failure line appears. The `RAM:` line is a fact; any
equation relating it to the allocation is a guess.

Two corollaries. Both were learned on the C3 and both still stand:

- **Adding an `interval:` block with a `heap_caps_*` lambda was enough on its
  own to break a build that worked without it.** If the display is failing and
  the change looks unrelated, suspect whatever was just added, not the vessels.
  Measured later, on the S3: the four `debug` sensors that report the same
  numbers cost **208 B** of DIRAM. Diagnostics are cheap here *because* the
  board has margin. They were not cheap on the C3, and the lesson was learned the
  expensive way.
- **The one-array vessel design is a choice now, not a budget.** It was forced on
  the C3, where the texture competed with the display buffer for internal RAM.
  With the buffer in PSRAM it competes with nothing, and `EYE_VEINS` in
  `eye-render.cpp` no longer claims otherwise. Leave it as it is unless someone
  decides they want the far side of the globe.

## Vessels

Baked once at boot into one packed array in eye-local coordinates, from a LCG
seeded by hardware entropy, so the set differs on every boot. **121 ms on the
first frame**, measured on the C3, which had no FPU; the WDT survives it. Roughly
8,600 samples.

The texture is a **ring, not a square**: `uint8_t[21708]` rather than
`uint8_t[193][193]`. The sclera branch samples theta 30..90 deg, which is an
annulus in texture coordinates, so the disc under the iris and the four corners
off the eyeball are 42 percent of the square and are never read. Rows are packed
left half then right half, with `VEIN_ROWOFF[ty]` giving each row's start and
`VEIN_HW_OUT`/`VEIN_HW_IN` its half-widths — 580 B of index. See **Vocabulary**
above for the axis, the limbus radius and the horizon radius, and
`docs/eye-parts.png` for the picture.

That layout has three off-by-one rules, and each one has already cost a bug:
first-valid `|dx|` not last-invalid (a 1-texel seam up from the iris), the
`wi == 0` span of `2*wo + 1`, and the `hwi ? hwi : 1` that keeps a row's two
halves from colliding.

**`VRing::row` is the one definition of a row's span, and both the constexpr
count and the runtime index build call it.** Written as two separate expressions
they once disagreed by 126 texels — an out-of-bounds write on a device with no
allocator to catch it. It is a `static constexpr` member function rather than a
lambda for two reasons: a nested function definition is illegal inside the
display lambda's body, and a constexpr lambda calling another constexpr lambda
compiles on desktop g++ but is rejected by the ESP-IDF toolchain. The `VRing`
bundle carries the texels and the three index tables so the count, the build,
the stamp and the read cannot each be handed different constants.

**`VEIN_TEX_SIDE` is the only resolution knob, and two constants must be derived
from it or the bump reads as a regression.** `VEIN_R_IN` is `VEIN_TEX_MID / 2`
(the limbus) — a literal left behind silently starts storing texels under the
iris again. `VEIN_W_TRUNK` is `VEIN_TEX_MID / 64.0f`, because brush radii are in
TEXELS and a texel covers less of the eye as the grid grows; leave it and the
vessels get thinner instead of finer. Both were literals, and both were wrong
twice before they were made expressions.

Cost ladder, ring + index. The **ring + index** column is arithmetic and still
trusts as a planner; the **RAM** column is C3 data, measured on a board with no
PSRAM, and the gap between the two columns was the whole budget:

| side | MID | ring + index | RAM (C3) |
|---|---|---|---|
| 129 | 64 | 10,036 B | 96,400 |
| 145 | 72 | 12,628 B | 98,992 |
| 161 | 80 | 15,552 B | 101,920 |
| 193 | 96 | 22,288 B | 108,656 |
| 209 | 104 | 26,092 B | 112,460 (unflashed) |

With 2 MB of PSRAM the C3 column no longer says what fits. Re-measure from a
known-good baseline before trusting any of it, and do not raise `VEIN_TEX_SIDE`
on the strength of free PSRAM alone — side 193 is already finer than the panel
resolves, per the note below.

The ring packing is why this ladder exists at all. The old side129 *square* cost
16,641 B; the side193 *ring* costs 22,288 B and stores 50 percent more texels.

**Side 193 is past the point of visible gain.** A texel is `120 / MID` panel
pixels across and the panel resolves 1, so 193 is 1.25 px/texel — already finer
than the screen. Anything above it spends memory on detail nobody can see.

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

- **Strip ANSI before grepping esphome output.** `esphome config` is
  colourised: `... | grep -c valid` returns 7 (mostly
  `ignore_pin_validation_error` and your own comments) where the real answer
  is 1. Use
  `sed 's/\x1b\[[0-9;]*m//g' | grep -qE "Configuration is valid!"`.
- **`heap_caps_*` is device-only.** It does not exist on the sandbox's host
  target, so it can never go in the shared `eye-render.cpp` — device
  diagnostics must live in `eye-device.yaml`. Relatedly, ESP-IDF 5.5 has no
  `heap_caps_get_used_size()`; only `total`, `free`, `minimum_free`,
  `largest`.
- **`gpio_pulldown_en()` does not clear a pull-up, so it proves nothing.**
  The ESP-IDF UART driver enables a pull-up on the RX pin. Enabling a pull-down
  alongside it leaves you unable to say what the line is doing, and reading a
  high level off a floating, unconnected wire is indistinguishable from a
  working one. Use `gpio_set_pull_mode(pin, GPIO_PULLDOWN_ONLY)`, which forces
  the mode. This cost a whole diagnostic round: a "the module is alive" reading
  that was really the board reading its own pull-up.
- **The sandbox has no UI at all, and no component adds one.** `web_server`,
  `api`, `mqtt`, `number`, `select` and `button` all reject the `host` platform.
  A template `switch` there compiles fine and is **unreachable** — it is not a
  working control, and telling someone to flip it sends them looking for a
  button that does not exist. Drive state from an `interval:` and log it.
- **The sandbox needs a `logger:` block or it is silent.** `ESP_LOGI` compiles
  away without one, so a missing log line is indistinguishable from a block
  that never ran. The device has had a `logger:` all along; the sandbox did not.
- **macOS `awk` has no `strtonum()`** and `readelf` is absent. Use
  `.venv/bin/python` for anything parsing `nm` output.
- **The offline rig is verified against the C++ by eye, not automatically.**
  `tools/vessel/vessel.py` and the firmware produce their numbers from the same
  ideas transcribed twice, so a transcription slip is invisible to both. Three
  bugs survived a clean compile and were caught only by dumping the baked
  texture and looking at it: longitudes never accumulated from gaps, the Q8
  coverage overflowed `uint8_t`, and the Q12 spline above. **When the bake
  changes, dump it and look.**
- **The dump harness is currently broken.** `.tmp/veindump.py` lifts the bake
  out of `eye-render.cpp` by text so it cannot drift, but its check functions
  still call lat-long helpers (`vein_ll`, `vein_phi_q8`, `VEIN_LL_COLS`) that
  no longer exist — they died with the reverted lat-long experiment. It does not
  compile. It is gitignored, which is why it went unnoticed. Fix it against
  `VRing` before trusting it.
- **The C3 had no FPU; the S3 does.** Measured on the C3: `sqrtf` 6000 ns, float
  multiply 1800 ns. The per-pixel loop is integer because that is how it was
  written and tuned, and that reasoning does not survive an FPU — re-profile it
  before assuming integer is still the fast form.
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

## Demo mode and the manual look

One `switch` decides who is driving the eye.

| demo | behaviour |
|---|---|
| **on** | exactly what it always did: random saccades, the presence response, the authored constants. **Every `look_*` global is ignored** |
| **off** | the eye holds the gaze `look_yaw`/`look_pitch` give, **ignores presence entirely**, and still jitters |

The HA entities are in `eye-device.yaml`; the globals they write are in
`eye-globals.yaml`, so they exist on both targets and default to the authored
rest values. Nothing writes them except HA.

**Three rules, each one a wrong picture rather than an error.**

- **`frame++` must stay OUTSIDE the demo gate.** It drives the tremor *phase*.
  Gate it with the gaze machine and demo-off produces a fixed displacement
  instead of a shimmer — no error, and it looks nearly right, which is the worst
  kind of bug. `gmove` and `ghold` may be frozen; `frame` may not.
- **The manual gaze is applied AFTER the gaze machine, not before.** Placed after,
  turning demo off mid-saccade *snaps* to the sliders. Placed before, the machine
  immediately overwrites it and the sliders look dead.
- **Demo off PINS `pres_f = 0` rather than overriding `presence`.** Everything
  blended on `pres_f` — pupil, iris, vein tint, fibre channels and all five gaze
  parameters — lands on its rest end in one place. Crucially this means
  `eye-presence.yaml` keeps its single-writer rule untouched: there is no second
  writer, so there is no `pres_hold` protocol for a caller to respect. The random
  driver keeps flipping and keeps logging on the device for nobody's benefit,
  which is harmless.

**The `number` bounds are a UI convenience, not the guarantee.** The renderer
re-clamps what safety depends on, because a global is writable by any
automation, not only by these sliders. The pupil is the one that matters: a
half-extent of 1.0 makes `PUPIL_SPAN` zero and flattens the iris gradient, so
both are clamped to 0.05–0.90 in C++ and the floor at 1 stays.

**Nothing restores.** Every boot is the authored eye unless you choose otherwise,
which also means dragging a slider cannot wear the flash — `store_value_()` is
diff-gated and polled at 1 s, so a drag is at most one write a second.

Deliberately **not** exposed: tremor frequency (it sits below Nyquist on purpose,
and a slider invites pushing past the frame rate into a slow visible beat);
presence (see above); `update_interval` (must match the sandbox, and `GAZE_*`
counts frames); and the sclera, lids, cornea and flare, which are not in scope.

## The board: ESP32-S3-Zero

The device is an **ESP32-S3-Zero** (Waveshare), an ESP32-S3FH4R2: 4 MB flash,
512 KB of RAM and **2 MB of quad PSRAM inside the package**. It replaced an
ESP32-C3-Zero, and the swap changed the pinout, the flash port and the memory
budget. `board: esp32-s3-fh4r2` is the exact chip match — ESPHome has no
`esp32_s3_zero` board, so do not go looking for one.

All five display signals sit on one header row:

| signal | pin | pad |
|---|---|---|
| MOSI | GPIO1 | 4 |
| RST | GPIO2 | 5 |
| CLK | GPIO4 | 7 |
| CS | GPIO5 | 8 |
| DC | GPIO6 | 9 |

**The C3 and the S3 strap different pins, and that is the whole pinout story.**
The C3 straps GPIO2, 8 and 9, so GPIO2 was untouchable and was used for nothing.
The S3 straps **GPIO0, 3, 45 and 46** — of those only 3 and 45 are broken out,
and neither is used. **GPIO0 is the BOOT button and is not on a pad at all**,
which is why RST could not stay where it was. Anything that says "keep off
GPIO2" is a stale C3 rule.

What is not available, so nobody has to rediscover it by probing:

| pins | why not |
|---|---|
| GPIO0 | BOOT button, no pad |
| GPIO19, GPIO20 | native USB, no pad |
| GPIO26–GPIO32 | flash and PSRAM |
| GPIO33–GPIO37 | not broken out, reserved for octal PSRAM |
| GPIO21 | drives the onboard RGB LED — a signal here reads untrustworthy |
| GPIO43, GPIO44 | UART0, pads 16 and 17, and nothing is attached to read them |
| GPIO39–GPIO42 | JTAG |

**There is no usb-serial chip on this board.** The USB-C port goes straight to
the S3's native USB, so the port appears as `/dev/cu.usbmodem*` and not
`/dev/cu.usbserial-*`, and `logger:` needs `hardware_uart: USB_CDC` — the C3's
`USB_SERIAL_JTAG` does not exist on the S3. Do not add `wait_for_cdc`: it blocks
boot until a host opens the port, and the eye has to animate on its own.

**Flashing needs the BOOT button held** while RESET is tapped, then released.
This is more often needed than it was on the C3, and a port that vanishes
mid-upload is the symptom.

## Deliberate constraints — do not "fix" these

Each looks wrong and is not. `eye-device.yaml` documents the reasoning
in full; this is the short version.

- **The network went back in one gate at a time, and that is the method, not a
  one-off.** `wifi:` → `api:`/`mdns:`/`ota:` → `web_server:`, each flashed and
  watched before the next. On the C3 the network stack left 75,856 B free and a
  largest block of 61,440 B against a 115,200 B buffer request, which is why
  everything was removed. **A blank panel cannot tell you which component caused
  it**, so components go in one at a time — adding a whole stack blind
  reproduces the C3 diagnosis problem exactly. The panel is the only output, so
  the boot log is the only witness. It cost 49,804 B of internal RAM and
  629,496 B of flash in total, which turned out to be affordable once the frame
  buffer moved to PSRAM. `secrets.yaml` holds `wifi_ssid`, `wifi_password`,
  `api_encryption_key` and `fallback_ap_password`; all four were already there,
  unreferenced, waiting for this.
- **`web_server:` is deliberately unauthenticated.** ESPHome's `web_server` has no
  default auth, so a bare block is open to anything that can reach the IP. This
  was a deliberate choice on a home network, not an oversight — **do not add
  `auth:` to "fix" it without asking.** If the device ever leaves a trusted
  network, add `auth: {type: digest, ...}`: Basic sends the password in
  cleartext on every request, which ESPHome itself points out when it prefers
  the native API. Adding `web_server:` did **not** change the OTA platform —
  `ota:` declares only `platform: esphome`, and ESPHome prefers the native API
  whenever it is present.
- **`api: reboot_timeout: 0s`.** ESPHome defaults to rebooting the device when
  nothing connects for 15 minutes. **Presence is driven by `eye-presence.yaml` on
  the device, not by Home Assistant**, so the eye is fully functional with HA
  down. The default would restart the panel every 15 minutes for as long as HA
  was unreachable — including every night if HA is switched off to sleep. Do not
  "restore" the default.
- **`power_save_mode: none` on `wifi:`.** ESPHome defaults esp32 to `light`,
  which lets the radio sleep between beacons. Some access points drop it for
  seconds at a time, and an eye that freezes and recovers on its own reads as a
  renderer fault. Do not "save power" here.
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
after a Q8 dot product, Q8 not fitting a `uint8_t`, `#if` not a runtime bool).
Delete everything else:
changelogs, "that was a bug" stories, rationale for code that no longer
exists, and derivation of numbers already recorded elsewhere. A comment
describing a *past* state of the file is worse than none, because it reads
as current. If a comment and the code disagree, one of them is wrong — find
out which before believing the comment.

Keep `eye-device.yaml`'s header comment in sync when behaviour changes; it is
the only place several of the constraints above are justified.
