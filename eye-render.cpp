// The eye renderer.
//
// This is a translation unit, not an ESPHome component. eye-device.yaml and
// eye-sandbox.yaml list it under `esphome: includes:`, which copies it into
// src/ and compiles it. A .cpp is NOT #included into main.cpp - only headers
// are - so the declaration of eye_render() lives in eye-look.h, which IS on
// the include path of both this file and main.cpp. One declaration, so the
// signature and its call cannot drift.
//
// The state arrives as pointers because the globals live in eye-globals.yaml,
// which ESPHome emits into main.cpp where a separate translation unit cannot
// see them. The first lines of the body rebind them to local references, so
// everything below reads them as plain locals. The manual look controls arrive
// as one struct by reference, for the same reason.

#include "esphome.h"
#include "eye-look.h"

#include <cmath>

// Everything below is at global scope with `using namespace esphome`, so the
// body needs no qualification.
using namespace esphome;

void eye_render(display::Display *itp,
                float *yaw_p, float *pitch_p,
                float *yaw_t_p, float *pitch_t_p,
                float *yaw_s_p, float *pitch_s_p,
                int *gmove_p, int *ghold_p, int *frame_p,
                int *presence_p, float *pres_f_p,
                int *pres_hold_p, int *pres_seen_p,
                const eye::EyeLook &look) {
  // Bind the shared state to locals, so the body below uses the same names it
  // always did. `it` likewise: the body says it.fill(), not it->fill().
  display::Display &it = *itp;
  float &yaw = *yaw_p, &pitch = *pitch_p;
  float &yaw_t = *yaw_t_p, &pitch_t = *pitch_t_p;
  float &yaw_s = *yaw_s_p, &pitch_s = *pitch_s_p;
  int &gmove = *gmove_p, &ghold = *ghold_p, &frame = *frame_p;
  int &presence = *presence_p;
  float &pres_f = *pres_f_p;
  int &pres_hold = *pres_hold_p, &pres_seen = *pres_seen_p;

  // Demo mode is the master switch. ON: the authored performance, and every
  // other field of `look` is ignored. OFF: the eye holds the gaze yaw and pitch
  // say, presence is ignored, and the tremor still runs.
  const bool DEMO = look.demo != 0.0f;


  // =====================================================================
  // The eye, for a 240x240 round panel.
  //
  // The eyeball is a sphere of radius R seen head-on. Every visible pixel has
  // a surface normal; the iris and pupil are two circles ON that sphere,
  // concentric about the eye's forward axis; the gaze is the angle between
  // that axis and the viewer.
  //
  // The whole eyeball is repainted every frame. There is no dirty region.
  //
  // CONSTRAINT: this build is SOFT-FLOAT, no FPU. Measured on target -
  //   sqrtf 6000 ns, float multiply 1800 ns (an FPU would be 1-4).
  // All per-pixel maths is therefore integer. Floats appear once per frame to
  // derive the gaze basis.
  // =====================================================================

  // ================= tunables =================
  const float DEG = 0.0174532925f;
  const float YAW_MAX   = 52.0f;
  const float PITCH_MAX = 38.0f;

  // ================= gaze, at rest and when nervous =================
  // Five of these have a REST value and a PRES value, blended by pres_f, so the
  // eye gets twitchy when someone is there instead of changing character at a
  // step. pres_f = 0 is the calibrated look in docs/eye-parts.png; pres_f = 1 is
  // all five at their PRES end at once.
  //
  // The eye darts more often because the HOLD is shorter, and darts faster
  // because a saccade takes fewer frames. The blended gaze_frames is a FLOAT for
  // that reason - an int would truncate the blend to 3 or 2 in visible steps.
  const int   GAZE_FRAMES_REST = 4;      // frames per saccade (90 ms each) = 360 ms
  const float GAZE_FRAMES_PRES = 2.0f;   //                              = 180 ms
  const int   GAZE_HOLD_MIN_REST = 8;    // 720 ms at 90 ms/frame
  const int   GAZE_HOLD_MAX_REST = 55;   // 5.0 s
  const int   GAZE_HOLD_MIN_PRES = 2;    // 180 ms
  const int   GAZE_HOLD_MAX_PRES = 13;   // 1.2 s
  // A held, near-centred stare is far more unnerving than a wander, and an eye
  // that only ever looks away reads as disengaged rather than watching. That
  // stops being true once it is nervous: it is the HOLDING that unnerves, so the
  // chance of a stare falls rather than rises.
  const float GAZE_STARE_CHANCE_REST = 0.30f;
  const float GAZE_STARE_CHANCE_PRES = 0.05f;
  const float GAZE_STARE_SPREAD = 7.0f;   // degrees either side of centre
  const int   GAZE_STARE_HOLD_MIN = 18;   // 1.6 s
  const int   GAZE_STARE_HOLD_MAX = 70;   // 6.3 s

  // Micro-tremor, in degrees. 1 degree is ~1.7 px of iris travel here, so this
  // is under a pixel: enough to shimmer, not enough to read as motion. At full
  // presence it is 1.2 degrees, which does read as motion - that is the point.
  //
  // The frequencies are in rad/frame and deliberately LOW. At update_interval
  // 200 ms the frame rate is 5 Hz, so Nyquist is 2.5 Hz - real 8-12 Hz tremor
  // is simply not representable and would alias into a visible slow beat. They
  // are NOT scaled by pres_f: the jitter should come from bigger amplitude at a
  // plausible rate, not from pushing the frequency past what the frame rate can
  // carry.
  const float TREMOR_DEG_REST = 0.30f;
  const float TREMOR_DEG_PRES = 1.20f;
  const float TREMOR_W1  = 1.63f;   // ~1.30 Hz at 5 fps
  const float TREMOR_W2  = 2.21f;   // ~1.76 Hz, incommensurate with W1

  // 30 deg puts the iris at ~60 px radius, so it spans half the globe, close to a
  // real eye (~11.7 mm across on a ~24 mm globe).
  const float IRIS_ANGLE = 30.0f;
  // Pupil half-extents as fractions of the iris radius, in the eye's OWN frame:
  // the pupil turns with the gaze, like the fibre texture. Only the catchlight
  // and the lids are screen-fixed.
  //
  // TWO pairs, not one, because the mmWave radar drives it. Each pair is
  // (half-width along the eye's right axis, half-height along its up axis):
  //     rest      round and large, nobody in the room
  //     presence  a narrow vertical slit, someone there
  // pres_f (0..1) interpolates between them, so the pupil morphs round->slit
  // rather than snapping. Both endpoints floor each half-extent at 1 before the
  // reciprocal, so no interpolation between them can overflow the ellipse test.
  const float PUPIL_W_REST = 0.58f, PUPIL_H_REST = 0.58f;
  const float PUPIL_W_PRES = 0.26f, PUPIL_H_PRES = 0.66f;
  // Fraction of the remaining gap covered per frame. At 90 ms/frame a full
  // 0->1 sweep takes ~0.9 s: reads as a reaction, not a step.
  const float PRES_EASE = 0.11f;
  // The eye IGNORES a change in presence for a random time in this range before
  // it starts moving at all, so it does not flinch at every flicker of the
  // input. In frames, because the gaze machine counts frames for the same reason:
  // at 90 ms these are 5.0 s and 15.0 s. Changing update_interval rescales both.
  const int PRES_DELAY_MIN = 56;   //  5.0 s
  const int PRES_DELAY_MAX = 167;  // 15.0 s
  const float SHADE_VERTICAL = 0.10f;    // extra darkening toward the bottom

  // Lid shadows. SCREEN-fixed, not eye-local: the lids belong to the head and
  // do not rotate with the globe. This is also the single biggest thing that
  // stops the lit hemisphere reading as one flat white disc.
  const float LID_UPPER_REACH = 0.62f;  // fraction of R to reach full strength
  const float LID_UPPER_STR   = 0.46f;
  const float LID_LOWER_START = 0.42f;  // fraction of R below centre
  const float LID_LOWER_REACH = 0.45f;
  const float LID_LOWER_STR   = 0.18f;

  // One catchlight on the cornea. SCREEN-fixed: the cornea is spherical, so its
  // reflection of a fixed light cannot move as the eye looks. Sits on the iris
  // side because the sclera is within 9 of white and a highlight there clips to
  // nothing.
  const int CORNEA_R     = 5;      // hard core
  const int CORNEA_BLOOM = 9;      // soft skirt
  const int CORNEA_BLOOM_PEAK = 70;

  // Lens flare, in pixels of the iris's own frame. Additive on top of the iris
  // shading, so it lifts toward white rather than changing hue.
  //
  // PEAK scales both parts and is not the value either reaches: the streak tops
  // out at LEN*THICK*PEAK/256 and the core at CORE_SQ*PEAK/256. Raising LEN or
  // THICK without scaling PEAK back down pushes the streak past 255, which
  // clamps into a flat grey bar rather than a flare.
  const int FLARE_PEAK   = 72;
  const int FLARE_LEN    = 50;      // half-length of the streak (iris is 60)
  const int FLARE_THICK  = 10;       // half-thickness of the streak
  const int FLARE_CORE   = 20;       // radius of the hot core
  const int FLARE_CORE_SQ = FLARE_CORE * FLARE_CORE;

  // ---- scleral vessels ----
  // MUST stay #if, not a runtime bool: the ring below is a static array, so it
  // occupies VEIN_TEX_N bytes of .bss whether or not anything ever writes to it,
  // and a runtime bool would not save one byte of that. It no longer competes
  // with the display buffer either - that moved to PSRAM - but internal DIRAM is
  // still 341,760 B with ~212,000 B free, so the cost is real, just smaller.
  #define EYE_VEINS 1
  #if EYE_VEINS
  // A texel is indexed by (ldx, ldy) - the projection of a unit normal onto the
  // eye's own right/up axes - and that pair names TWO surface points on the
  // globe, theta and 180 - theta. One array holds the front hemisphere only.
  //
  // WHAT THAT COSTS: at rest every visible pixel has along > 0, so the whole
  // sclera is covered and nothing is wrong. As the eye turns, pixels with
  // along < 0 start reading the SAME array, and what they get is the near-side
  // pattern mirrored onto the far side of the globe - a duplicate that does not
  // track the turn. At yaw 52 that is 71 percent of the visible disc, so the
  // far side of the eye is visibly wrong rather than merely sparse.
  //
  // Side is set by LOOKS, not by memory, and that changed with the board: on the
  // C3 this texture lived in internal RAM beside a 115,200 B buffer the heap
  // could not satisfy, so every byte of .bss was contested. The buffer is now in
  // PSRAM. 193 is still the right number for its own reason - see below - but if
  // you change it, nothing here is defending the number any more.
  const int VEIN_TEX_SIDE = 193;
  const int VEIN_TEX_MID  = VEIN_TEX_SIDE / 2;
  // ---- the ring, not the square ----
  // The sclera branch is the ONLY reader, and it starts where the iris cap
  // ends, at theta = IRIS_ANGLE = 30 deg. Radius r in this square is
  // sin(theta) * MID, so nothing with r < R_IN is ever sampled, and nothing with
  // r > MID is either because that is the silhouette. A square of this side is
  // 21,025 B and the ring inside it is 12,192 B; the middle under the iris and
  // the four corners off the eyeball are 42 percent of the array and dead. A
  // RING, not a disc - a disc would keep the part under the iris.
  //
  // R_IN MUST BE MID / 2. It is the texture radius of the limbus, so leaving it
  // behind while MID moves silently starts storing texels under the iris again
  // and gives back exactly the memory the ring saves. MID8 and the `>> 8` in the
  // sample site both scale off MID, so nothing else here needs editing.
  //
  // THREE RULES below, and each one has already cost a bug. They are all
  // off-by-one rules, all of them produce a texture that looks nearly right,
  // and none of them is caught by a compiler.
  //
  //   1. VEIN_HW_IN is the FIRST VALID |dx| - the smallest |dx| at or outside
  //      the iris hole - NOT the last invalid one. For ay >= R_IN there is no
  //      hole and the centre column belongs to the ring, so it is 0. Reading it
  //      as "last invalid" leaves a 1-texel vertical line at x = MID running
  //      from the iris out through the vessels.
  //   2. A row spans |dx| in [wi, wo] INCLUSIVE: 2 * (wo - wi + 1) texels,
  //      EXCEPT when wi == 0, where the two sides meet on one shared texel and
  //      the span is 2 * wo + 1.
  //   3. Rules 1 and 2 live in ONE place, VRing::row, because the ring's SIZE
  //      and its INDEX BUILD must agree TEXEL FOR TEXEL. Written as two
  //      expressions they disagreed by 126, which is an out-of-bounds write on a
  //      device with no allocator to catch it. The count and the build both call
  //      that function; the runtime check below is a tripwire, not the mechanism.
  const int VEIN_R_IN = VEIN_TEX_MID / 2;
  // Everything the index maths needs in one bundle, so the count, the build, the
  // stamp and the read cannot each be handed a different set of constants.
  //
  // `row` is a static constexpr MEMBER FUNCTION, not a lambda, for two reasons.
  // A local function definition is illegal inside the display lambda's body, and
  // a constexpr lambda calling another constexpr lambda compiles on desktop g++
  // and is rejected by the ESP-IDF toolchain. `wo` and `wi` come back through
  // pointers because the count needs only the span while the build also needs
  // the half-widths, and duplicating the maths to avoid the pointers is exactly
  // the drift rule 3 is about.
  struct VRing {
    uint8_t *tex;
    uint16_t *rowoff;
    uint8_t *hw_out, *hw_in;
    int side, mid, n;
    static constexpr int row(int side, int r_in, int ty, int *wo, int *wi) {
      const int mid = side / 2;
      int ay = ty - mid;
      if (ay < 0) ay = -ay;
      *wo = 0;
      *wi = 0;
      if (ay > mid) return 0;
      while ((*wo + 1) * (*wo + 1) <= mid * mid - ay * ay) (*wo)++;
      if (ay < r_in) {
        const int hole = r_in * r_in - ay * ay;
        while (*wi * *wi < hole) (*wi)++;
      }
      return *wi == 0 ? 2 * *wo + 1 : 2 * (*wo - *wi + 1);
    }
  };
  // A constexpr IIFE, not a helper function: this text is inside the display
  // lambda's body, where a nested function definition is illegal.
  constexpr int VEIN_TEX_N = []() {
    int n = 0, wo = 0, wi = 0;
    for (int ty = 0; ty < VEIN_TEX_SIDE; ty++)
      n += VRing::row(VEIN_TEX_SIDE, VEIN_R_IN, ty, &wo, &wi);
    return n;
  }();
  // Per-|dy| half-widths, and the start of each row's span. They replace a
  // bounds check and a multiply in the per-pixel loop rather than adding to it.
  static uint8_t VEIN_HW_OUT[VEIN_TEX_MID + 1];
  static uint8_t VEIN_HW_IN[VEIN_TEX_MID + 1];
  static uint16_t VEIN_ROWOFF[VEIN_TEX_SIDE];
  // The texels themselves, and the ring that describes how they are packed.
  static uint8_t VEIN_TEX_F[VEIN_TEX_N];
  static VRing RING{VEIN_TEX_F, VEIN_ROWOFF, VEIN_HW_OUT, VEIN_HW_IN,
                    VEIN_TEX_SIDE, VEIN_TEX_MID, VEIN_TEX_N};

  // ---- layout ----
  // Vessels are born at the back of the globe and wrap forward, so the run is
  // long: 19 trunks at jittered longitudes, each 14 waypoint intervals from
  // theta 30 to its own south end.
  const int   VEIN_TRUNKS    = 19;
  const int   VEIN_BRANCHES  = 3;
  const int   VEIN_SEGS      = 14;   // waypoint intervals along a trunk
  const int   VEIN_CTRL      = 2;    // control points per waypoint interval
  // 10, not 14: the samples land 0.48 texels apart and the brush radius is
  // 1.0, so they still overlap. It buys 1,344 B of the memory the frame buffer
  // needs - see the heap note at VEIN_TEX_SIDE.
  const int   VEIN_PERS      = 10;   // spline samples per control segment
  const int   VEIN_BPERS     = 10;   // ... and per branch segment
  // Offsets are Gaussian, drawn independently at every control point. The
  // irregularity is what makes a run read as grown; a sinusoid of matched
  // tortuosity reads as drawn.
  const float VEIN_SIGMA     = 0.30f;
  // theta_start clips every vessel to the part of the globe that is EVER seen.
  // The eye rotates 60.98 deg off its front pole at worst-case gaze, so the
  // visible sclera is alpha 30..150, not 90..150.
  const float VEIN_THETA0    = 30.0f;
  const float VEIN_FADE_MIN  = 140.0f;
  const float VEIN_FADE_MAX  = 148.0f;
  const float VEIN_FADE_SPAN = 16.0f;   // fade_start sits this far north
  // Jitter the GAPS, never the longitudes: jittering the longitudes themselves
  // lets two trunks cross over one another.
  const float VEIN_LON_JIT   = 0.22f;

  // ---- branching ----
  // Attachment is weighted by (theta/fade_end)^VEIN_ATTACH_POW, which pulls
  // branches toward the limbus, and rejected outright where less than
  // VEIN_MIN_REMAIN degrees of globe are left below the attachment point. The
  // two together put almost every attachment in a narrow band just inside the
  // guard, which is why the branches come out short.
  const int   VEIN_ATTACH_POW = 2;
  const float VEIN_MIN_REMAIN = 12.0f;
  // A branch on a faded sample appears to start from nothing.
  const float VEIN_TIP_FADE   = 0.55f;
  const float VEIN_DEPART_LO  = 30.0f, VEIN_DEPART_HI = 50.0f;
  const float VEIN_LEN_LO     = 0.22f, VEIN_LEN_HI   = 0.55f;
  const float VEIN_THIN_LO    = 0.45f, VEIN_THIN_HI  = 0.85f;
  const float VEIN_BRANCH_DEG = 5.0f;    // great-circle step for a branch

  // Tint strength, applied at the sample site as a blend toward VEIN_COL, and
  // scaled by the baked coverage so it is a strength and not a colour swap.
  //
  // REST and PRES like the gaze parameters: a calm eye has almost no blood in
  // it, and the vessels only come up when there is someone to be angry at. A
  // FULLY covered vessel pixel goes (240,240,235) -> (204,26,26) at PRES and
  // -> (234,208,203) at REST: a pale pink that reads as barely there. Most
  // pixels are not fully covered, so in practice REST is fainter still.
  const float VEIN_TINT_REST = 0.15f;
  const float VEIN_TINT_PRES = 1.00f;

  // Scratch for the bake. Not stack: loop_task_stack is 8,192 B and these two
  // alone are over 7,000. They are only touched once, at first frame.
  //
  // Sizes are tight on purpose. The frame buffer needs 115,200 B out of ONE
  // block, and DRAM is split at a fixed address into a fixed 114,688 B region
  // plus a first region of (239,792 - RAM_used) that shrinks as .bss grows.
  // Only the first can ever satisfy the request, so every byte here is a byte
  // off the frame buffer. The limit is RAM_used <= 124,592.
  //
  // VEIN_NET_MAX must clear the peak. Candidates are thinned to every 3rd
  // sample, which took the measured peak from 529 to 177. The append is
  // guarded, so running short does not corrupt anything, it just quietly stops
  // offering late branches anywhere to attach.
  const int VEIN_MAXPTS = 288;    // longest run: 27 segments x 10 + 1
  const int VEIN_NET_MAX = 192;
  const int VEIN_MAXCP = VEIN_SEGS * VEIN_CTRL + 2;
  const int VEIN_MAXGC = 32;      // great-circle points on one branch
  #endif


  // ---- iris fibres ----
  // MUST stay #if, not a runtime bool: this array is in .bss whether or not
  // anything ever writes to it. It is 9,409 B, and the full-frame display
  // buffer needs one contiguous 115,200 B block.
  #define EYE_IRIS_FIBRES 1
  #if EYE_IRIS_FIBRES
  // Maps the eye-local Q8 coordinate out to the texture's 48-texel half-width.
  // At IRIS_ANGLE 30 the cap radius is sin(30)*256 = 128, and 128*96>>8 = 48,
  // so the whole cap is covered and the texture stays 97x97 whatever the angle.
  // Indexing it as (ldx>>1) instead would overflow the array at any angle over
  // ~25 deg.
  const int IRIS_TEX_SIDE = 97;
  const int IRIS_TEX_SCALE = 96;
  #endif

  // R = 120 inscribes the 240x240 panel exactly, so there is no margin and no
  // room for the brow below. The loop is inclusive of CY+R, which is y = 240 -
  // one past the last row. That one pixel is safe: draw_pixel_at range-checks
  // through get_clipping().inside(), so it is dropped rather than written.
  const int CX = 120, CY = 120, R = 120;
  const int R_SQ = R * R;
  #if EYE_VEINS
  // Brush RADII in texels. The brush falls to zero AT its radius and
  // consecutive stamps saturate that disc solid, so it covers twice the radius
  // across - one texel of radius is 2 texels of width.
  //
  // Both radii are in TEXELS, not panel pixels, because the floor is a property
  // of the texel grid and not of the panel. Every branch tip in the model wants
  // 11 to 42 percent of trunk width, all of it under the floor, so they all
  // clamp to the same value: the trunk has to clear the floor too or branches
  // come out thicker than trunks. Offline at 3.0 px and side 129 that is exactly
  // what happens, and the set reads as a uniform rash instead of a tree.
  //
  // VEIN_W_TRUNK is therefore in PANEL pixels' worth of texels and has to move
  // with MID, while VEIN_W_MIN below does not - the floor is about the grid.
  // Deriving the trunk from MID is what keeps a resolution bump from reading as
  // a regression: leave it at 1.0 and a bigger grid does not make the vessels
  // finer, it makes them thinner, because a texel now covers less of the eye.
  // 1.0 at side 129 is 3.75 px on the panel, and 3.75 px is 2 * W * 120 / MID.
  const float VEIN_W_TRUNK = VEIN_TEX_MID / 64.0f;
  // A texel centre can sit up to 0.707 texels off the track centreline, so a
  // brush narrower than this leaves gaps however densely the curve is sampled.
  const float VEIN_W_MIN    = 0.75f;
  const int   VEIN_WMIN_Q8 = (int) (VEIN_W_MIN * 8.0f + 0.5f);
  #endif

  Color SCLERA_HI(0xFF, 0xFD, 0xF6);    // brightest, facing the light
  // Shadow is warmer and more saturated, not merely darker white. A single
  // lerp to a darker SCLERA_HI cannot express that; this is the colour the
  // sclera shading actually resolves to at t8 = 255.
  Color SCLERA_LO(0xC4, 0xB4, 0xA2);    // shadowed, at the rim
  Color SKIN(0x14, 0x10, 0x18);         // backdrop
  // Iris colour, on the same pres_f as the pupil: green while the room is empty,
  // red once the radar reports someone. Three colours each, not one, because a
  // lerp on the base alone leaves the stroma fibres a fixed orange on a green
  // iris and the crypts a fixed maroon, which reads as a bug rather than a hue.
  Color IRIS_REST(44, 172, 66);        // bright centre of the iris, idle
  Color IRIS_PRES(200, 45, 45);        // bright centre of the iris, someone there
  #if EYE_VEINS
  Color VEIN_COL(0xCC, 0x1A, 0x1A);     // blood, at full coverage
  #endif
  #if EYE_IRIS_FIBRES
  Color IRIS_FIBRE_REST    (104, 214, 128);   // stroma fibres, lighter
  Color IRIS_FIBRE_DK_REST ( 14,  62,  26);   // crypts, darker
  Color IRIS_FIBRE_PRES    ( 222, 150,  88);
  Color IRIS_FIBRE_DK_PRES (  60,  12,  12);
  #endif


  #if EYE_VEINS
  // Unit vector. Q12 during the bake so the spline can stay integer; a point
  // on the sphere is 4096, and |P| never leaves [0.98, 1.02] after the Newton
  // step, so it fits int16 in the net below.
  struct V3 { int32_t x, y, z; };
  struct F3 { float x, y, z; };
  // One sample a branch may attach to. The tangent is NOT stored: it is
  // recovered from the neighbours at the single moment it is needed, which
  // saves 6 B on every entry and 2,600 sqrtf across the bake.
  struct VNet {
    int16_t x, y, z;
    uint16_t th8;      // polar angle, Q8 degrees
    uint8_t alpha;
    uint8_t wq;        // brush radius, 1/8 texel
  };
  // ================= vessel texture ================
  // Baked ONCE at boot into a RING, not a square - see VEIN_R_IN. The LAYOUT is
  // fixed; only the LCG is seeded, from hardware entropy, so the set differs on
  // every boot.
  static bool veins_built = false;
  if (!veins_built) {
    veins_built = true;
    const uint32_t vb0 = millis();
    const int32_t MID8 = (int32_t) VEIN_TEX_MID << 3;   // centre, in 1/8 texel
    for (int i = 0; i < VEIN_TEX_N; i++) VEIN_TEX_F[i] = 0;

    // ---- ring index ----
    // Built once, before anything stamps. rowoff[ty] is where that row's span
    // starts in the packed array. Rows are walked TOP TO BOTTOM, not by |dy|:
    // the row above centre and the row below it are DIFFERENT rows with
    // DIFFERENT spans, and walking by |dy| gives them one shared offset and
    // aliases half the ring onto the other half.
    {
      int off = 0;
      for (int ty = 0; ty < RING.side; ty++) {
        int wo = 0, wi = 0;
        RING.rowoff[ty] = (uint16_t) off;
        off += VRing::row(RING.side, VEIN_R_IN, ty, &wo, &wi);
        int ay = ty - RING.mid;
        if (ay < 0) ay = -ay;
        if (ay <= RING.mid) {              // ay is the table index, not ty
          RING.hw_out[ay] = (uint8_t) wo;
          RING.hw_in[ay] = (uint8_t) wi;
        }
      }
      if (off != VEIN_TEX_N) {
        ESP_LOGE("eye", "vessel ring index: packed %d, expected %d", off, VEIN_TEX_N);
      }
    }

    // ---- random ----
    // A zero seed is not a fixed point here: next(0) = 12345.
    uint32_t seed = esphome::random_uint32();
    auto rnd = [&]() -> float {
      seed = (1103515245u * seed + 12345u) & 0x7FFFFFFFu;
      return (float) seed * (1.0f / 2147483648.0f);
    };
    auto uni = [&](float lo, float hi) { return lo + (hi - lo) * rnd(); };
    // Irwin-Hall over 8 draws. The sum has sigma sqrt(8/12), so scaling by
    // 1/sqrt(8/12) makes it a unit normal near the centre, and it is bounded at
    // 4.9 sigma. Box-Muller would cost a logf and a sqrtf per deviate, and at
    // ~6 us for a sqrtf that is most of the bake.
    auto gauss = [&]() -> float {
      float s = 0.0f;
      for (int i = 0; i < 8; i++) s += rnd();
      return (s - 4.0f) * 1.2247449f;
    };

    // ---- theta without acos ----
    // acos costs several sqrtf and the bake needs theta for every one of
    // ~10,000 samples. One 257-entry table of theta in Q8 DEGREES against z in
    // Q8 removes every call; acos(-z) = 180 - acos(z) halves the table.
    static uint16_t acos_q8[257];
    for (int a = 0; a <= 256; a++)
      acos_q8[a] = (uint16_t) (acosf((float) a * (1.0f / 256.0f))
                               * (180.0f / 3.14159265f) * 256.0f);
    auto q8z = [](V3 v) -> int {
      int z = v.z >> 4;
      return z > 256 ? 256 : (z < -256 ? -256 : z);
    };
    auto theta_q8 = [&](int z8) -> int {
      return z8 >= 0 ? acos_q8[z8] : 46080 - acos_q8[-z8];
    };

    // Coverage is Q8 with 256 meaning FULL, so it cannot be stored in a
    // uint8_t directly: (uint8_t) 256 is 0, and every vessel at full coverage
    // would vanish. Clamp on the way in, once, here.
    auto q8c = [](int v) -> uint8_t { return (uint8_t) (v > 255 ? 255 : v); };

    // ---- brush ----
    // One falloff table for every width, indexed by (distance/radius)^2 * 64.
    // It reaches zero exactly AT the radius, which is why the brush covers
    // twice its radius across.
    uint8_t fall[65];
    for (int k = 0; k <= 64; k++)
      fall[k] = (uint8_t) (255.0f * (1.0f - sqrtf((float) k * (1.0f / 64.0f))));

    // `front` is the hemisphere test, z >= 0. With one array the far hemisphere
    // is simply not stamped: it would land on the same texels as the near side
    // and the two sets would have to be picked between at sample time, which is
    // the thing there is no memory for.
    //
    // cxi/cyi are ABSOLUTE in 1/8 texels - the same frame as the texel index
    // below - with the centre at RING.mid << 3. Mixing an absolute texel index
    // with a centre-relative offset offsets the whole brush by mid texels, which
    // does not fail loudly: it just paints a fraction of the vessels.
    auto stamp = [&](int32_t cxi, int32_t cyi, int wi, int amp, bool front) {
      if (!front) return;
      int wi2 = wi * wi;
      int sc = (64 << 12) / wi2;
      for (int yy = (cyi - wi) >> 3; yy <= (cyi + wi) >> 3; yy++) {
        if (yy < 0 || yy >= RING.side) continue;
        int ay = yy - RING.mid;
        if (ay < 0) ay = -ay;
        if (ay > RING.mid) continue;
        const int wo = RING.hw_out[ay], hwi = RING.hw_in[ay];
        const int base = RING.rowoff[yy];
        int ey = (yy << 3) + 4 - cyi;
        int ey2 = ey * ey;
        for (int xx = (cxi - wi) >> 3; xx <= (cxi + wi) >> 3; xx++) {
          if (xx < 0 || xx >= RING.side) continue;
          int dx = xx - RING.mid;
          int ax = dx < 0 ? -dx : dx;
          if (ax < hwi || ax > wo) continue;      // outside the ring
          int ex = (xx << 3) + 4 - cxi;
          int d2 = ex * ex + ey2;
          if (d2 >= wi2) continue;
          int k = (d2 * sc) >> 12;
          if (k > 64) continue;
          // A row is packed as TWO halves, left first, adjacent, no gap.
          //   hwi > 0  left is |dx| = hwi..wo (offsets 0..wo-hwi),
          //             right is |dx| = hwi..wo and starts after the left half.
          //   hwi == 0 the halves MEET: there is one shared texel at |dx| = 0
          //             and it belongs to the LEFT half, so the right half runs
          //             from |dx| = 1. That is the `hwi ? hwi : 1` - one texel.
          // Getting it wrong does not lose a texel, it OVERLAPS two, and the
          // row's brightest texel ends up written twice.
          int off = dx < 0 ? (wo - ax)
                           : (wo - hwi + 1) + (ax - (hwi ? hwi : 1));
          uint8_t &cell = RING.tex[base + off];
          // Over, not max: two vessels crossing must darken where both pass.
          // cell + add*(1 - cell/256).
          int add = (amp * fall[k]) >> 8;
          int v = cell + add - ((cell * add) >> 8);
          cell = (uint8_t) (v > 255 ? 255 : v);
        }
      }
    };

    // ---- spline ----
    // Q12 throughout. Each coefficient is Q12 and each power of t is Q12, so
    // EVERY product needs its own >> 12. Without them the polynomial is 4096x
    // too large - and it still looks right at t = 0, where all three terms
    // vanish, so only the second sample onwards reveals it.
    //
    // The widest coefficient is 12 and t2 reaches 4096, so the largest product
    // is 2.0e8 against a limit of 2.1e9: Q16 would overflow here. One Q12 step
    // is 1/4096 of a unit vector, which is 0.024 texels - four orders of
    // magnitude below anything the texel grid can show.
    #define VQ 4096
    auto vnorm = [](V3 v) -> V3 {
      int32_t d = (v.x * v.x + v.y * v.y + v.z * v.z) >> 12;   // |P|^2, Q12
      // One Newton step on 1/|P| taken about |P| = 1. Exact to 0.015 percent
      // at d = 1.02, and a true sqrtf here is 6 us across ~10,000 samples.
      int32_t r = (3 * VQ - d) >> 1;
      v.x = (v.x * r) >> 12; v.y = (v.y * r) >> 12; v.z = (v.z * r) >> 12;
      return v;
    };
    // Cardinal spline, tension 0 -> uniform Catmull-Rom, so s = 1/2 and the
    // factor collapses into the final shift. The first sample lands on C[1],
    // not C[0], which is why a branch sets its own start point afterwards.
    auto catmull = [&](const V3 *C, int nc, int per_seg, V3 *out) -> int {
      int n = 0;
      for (int i = 0; i + 3 < nc; i++) {
        int32_t a0 = C[i].x, b0 = C[i+1].x, c0 = C[i+2].x, d0 = C[i+3].x;
        int32_t a1 = C[i].y, b1 = C[i+1].y, c1 = C[i+2].y, d1 = C[i+3].y;
        int32_t a2 = C[i].z, b2 = C[i+1].z, c2 = C[i+2].z, d2 = C[i+3].z;
        for (int j = 0; j < per_seg; j++) {
          int32_t t  = (j * VQ) / per_seg;
          int32_t t2 = (t * t) >> 12;
          int32_t t3 = (t2 * t) >> 12;
          out[n].x = (2*b0 + (((c0-a0)*t) >> 12)
                          + (((2*a0-5*b0+4*c0-d0)*t2) >> 12)
                          + (((3*b0-a0-3*c0+d0)*t3) >> 12)) >> 1;
          out[n].y = (2*b1 + (((c1-a1)*t) >> 12)
                          + (((2*a1-5*b1+4*c1-d1)*t2) >> 12)
                          + (((3*b1-a1-3*c1+d1)*t3) >> 12)) >> 1;
          out[n].z = (2*b2 + (((c2-a2)*t) >> 12)
                          + (((2*a2-5*b2+4*c2-d2)*t2) >> 12)
                          + (((3*b2-a2-3*c2+d2)*t3) >> 12)) >> 1;
          out[n] = vnorm(out[n]);
          n++;
        }
      }
      out[n++] = C[nc - 1];
      return n;
    };
    #undef VQ

    // Control points at fractions of each chord, offset PERPENDICULARLY.
    // Perpendicular-only is what keeps the coarse course monotone, so the
    // curve cannot double back on itself or self-intersect.
    static V3 CPQ[VEIN_MAXCP];
    auto toq = [](F3 f) -> V3 {
      return V3 { (int32_t) (f.x * 4096.0f), (int32_t) (f.y * 4096.0f),
                  (int32_t) (f.z * 4096.0f) };
    };
    // Rotation commutes with the spline - it is linear in the control points -
    // so it is cheaper here than on all ~400 samples, and theta is unaffected.
    auto rotq = [](int n, int32_t c, int32_t s) {
      for (int i = 0; i < n; i++) {
        int32_t x = CPQ[i].x, y = CPQ[i].y;
        CPQ[i].x = (x * c - y * s) >> 12;
        CPQ[i].y = (x * s + y * c) >> 12;
      }
    };
    auto controls = [&](const F3 *W, const F3 *T, int nseg, float ramp) -> int {
      int nq = 0, k = 0;
      for (int i = 0; i < nseg; i++) {
        F3 p = { W[i].y*T[i].z - W[i].z*T[i].y,
                 W[i].z*T[i].x - W[i].x*T[i].z,
                 W[i].x*T[i].y - W[i].y*T[i].x };
        float pn = sqrtf(p.x*p.x + p.y*p.y + p.z*p.z);
        if (pn < 1e-9f) { p.x = 1.0f; p.y = 0.0f; p.z = 0.0f; pn = 1.0f; }
        p.x /= pn; p.y /= pn; p.z /= pn;
        float dx = W[i+1].x - W[i].x, dy = W[i+1].y - W[i].y, dz = W[i+1].z - W[i].z;
        float ch = sqrtf(dx*dx + dy*dy + dz*dz);
        if (i == 0) CPQ[nq++] = toq(W[0]);
        for (int j = 1; j <= VEIN_CTRL; j++) {
          float o = gauss() * VEIN_SIGMA;
          // ramp keeps the scatter out of the first control points, or the
          // Gaussian overrides the departure angle the caller asked for.
          if (ramp > 0.0f) {
            float u = (float) k / (ramp * (float) (nseg * VEIN_CTRL + 1));
            u = u < 0.0f ? 0.0f : (u > 1.0f ? 1.0f : u);
            o *= u * u * (3.0f - 2.0f * u);
          }
          float f = (float) j / (float) (VEIN_CTRL + 1);
          F3 q = { W[i].x + T[i].x*(ch*f) + p.x*(o*ch),
                   W[i].y + T[i].y*(ch*f) + p.y*(o*ch),
                   W[i].z + T[i].z*(ch*f) + p.z*(o*ch) };
          float qn = sqrtf(q.x*q.x + q.y*q.y + q.z*q.z);
          CPQ[nq++] = toq(F3 { q.x/qn, q.y/qn, q.z/qn });
          k++;
        }
      }
      CPQ[nq++] = toq(W[nseg]);
      return nq;
    };

    // ---- the network ----
    // Samples a later branch may attach to. Only alpha > 0.35 can ever be an
    // attachment, so filtering at 0.05 costs nothing and keeps it short. The
    // tangent is NOT stored: it is recovered from the neighbours at the one
    // moment it is needed.
    static VNet net[VEIN_NET_MAX];
    static V3 pts[VEIN_MAXPTS];
    static uint8_t alp[VEIN_MAXPTS];
    static uint8_t wq[VEIN_MAXPTS];   // brush radius, 1/8 texel
    int nn = 0;
    int drawn = 0;

    // ---- longitudes ----
    float lons[VEIN_TRUNKS];
    float gsum = 0.0f;
    for (int i = 0; i < VEIN_TRUNKS; i++) {
      lons[i] = (360.0f / (float) VEIN_TRUNKS)
                * (1.0f + VEIN_LON_JIT * (rnd() * 2.0f - 1.0f));
      gsum += lons[i];
    }
    float gk = 360.0f / gsum;
    for (int i = 0; i < VEIN_TRUNKS; i++) lons[i] *= gk;
    // GAPS become LONGITUDES by accumulation. Without this every trunk is
    // placed at its own gap, all 19 inside a 19 deg wedge, and the set renders
    // as a fan out of one point on the rim instead of a ring.
    float run = uni(0.0f, 360.0f / (float) VEIN_TRUNKS);   // rotate the set
    for (int i = 0; i < VEIN_TRUNKS; i++) {
      float g = lons[i];
      lons[i] = run;
      run += g;
    }

    // ---- trunks and their branches ----
    for (int ti = 0; ti < VEIN_TRUNKS; ti++) {
      float fe = uni(VEIN_FADE_MIN, VEIN_FADE_MAX);
      float fs = fe - VEIN_FADE_SPAN;
      int fe8 = (int) (fe * 256.0f), fs8 = (int) (fs * 256.0f);
      int fade_num = (255 << 12) / (fe8 - fs8);
      // Q16 reciprocal of fe8, so theta/fe lands in Q8 and stays in 0..256.
      // The product peaks at 46,080 * 458 = 2.1e7, well inside uint32.
      int fei = (1 << 24) / fe8;

      // Alpha from theta, all integer. smoothstep runs 0..256, where 256 is
      // full, so the formula is the same one the lid ramp uses.
      auto fade = [&](int th8) -> int {
        if (th8 >= fe8) return 0;
        if (th8 <= fs8) return 256;
        int u = (int) ((((uint32_t) (th8 - fs8)) * (uint32_t) fade_num) >> 12);
        if (u > 255) u = 255;
        return (u * u * (768 - 2 * u)) >> 16;
      };

      float la = lons[ti] * DEG;
      int32_t cq = (int32_t) (cosf(la) * 4096.0f);
      int32_t sq = (int32_t) (sinf(la) * 4096.0f);

      // Waypoints on the meridian theta0..fe, and their tangents.
      F3 W[VEIN_SEGS + 1], T[VEIN_SEGS + 1];
      for (int i = 0; i <= VEIN_SEGS; i++) {
        float th = (VEIN_THETA0 + (fe - VEIN_THETA0)
                    * (float) i / (float) VEIN_SEGS) * DEG;
        float s = sinf(th), c = cosf(th);
        W[i] = F3 { s, 0.0f, c };
        T[i] = F3 { c, 0.0f, -s };
      }
      int nc = controls(W, T, VEIN_SEGS, 0.0f);
      rotq(nc, cq, sq);
      int n = catmull(CPQ, nc, VEIN_PERS, pts);

      int wt = (int) (VEIN_W_TRUNK * 8.0f + 0.5f);
      for (int i = 0; i < n; i++) {
        alp[i] = q8c(fade(theta_q8(q8z(pts[i]))));
        wq[i] = wt;
      }
      nn = 0;
      for (int i = 0; i < n; i++) {
        int a = alp[i];
        // Every 3rd sample only. The net exists to CHOOSE one attachment point,
        // weighted by theta, so thinning the candidates changes nothing about
        // the distribution - and it is the difference between a cap of 529
        // entries and a cap of 192, which is 3,360 B of the frame buffer's
        // margin. Measured peak over all 19 trunks was 529 undiluted.
        if (a < 13 || (i % 3)) continue;         // 0.05, for the net only
        net[nn].x = (int16_t) pts[i].x; net[nn].y = (int16_t) pts[i].y;
        net[nn].z = (int16_t) pts[i].z;
        net[nn].th8 = (uint16_t) theta_q8(q8z(pts[i]));
        net[nn].alpha = a;
        net[nn].wq = (uint8_t) wt;
        nn++;
      }
      for (int i = 0; i < n; i++) {
        if (!alp[i]) continue;
        stamp(((pts[i].x * (int32_t) VEIN_TEX_MID) >> 9) + MID8,
              ((pts[i].y * (int32_t) VEIN_TEX_MID) >> 9) + MID8,
              wt, alp[i], pts[i].z >= 0);
      }
      drawn += n;

      for (int br = 0; br < VEIN_BRANCHES; br++) {
        // Weight by (theta/fade_end)^VEIN_ATTACH_POW, all integer. Doing this
        // in float would be ~23,000 float multiplies. u is theta/fe in Q8 and
        // w is its power in Q8, so both stay in 0..256 and the running total
        // cannot overflow however many candidates there are.
        auto weight = [&](int i) -> uint32_t {
          if (net[i].alpha <= 89) return 0;       // 0.35
          uint32_t u = ((uint32_t) net[i].th8 * (uint32_t) fei) >> 16;
          uint32_t w = 256;
          for (int p = 0; p < VEIN_ATTACH_POW; p++) w = (w * u) >> 8;
          return w;
        };
        uint32_t total = 0;
        for (int i = 0; i < nn; i++) total += weight(i);
        if (total == 0) continue;
        uint32_t pick = (uint32_t) (rnd() * (float) total);
        int j = -1;
        for (int i = 0; i < nn; i++) {
          uint32_t w = weight(i);
          if (w == 0) continue;
          if (pick < w) { j = i; break; }
          pick -= w;
        }
        if (j < 0) continue;
        float remain = fe - (float) net[j].th8 * (1.0f / 256.0f);
        if (remain < VEIN_MIN_REMAIN) continue;
        float arc = remain * uni(VEIN_LEN_LO, VEIN_LEN_HI) * DEG;

        F3 B = { net[j].x * (1.0f/4096.0f), net[j].y * (1.0f/4096.0f),
                 net[j].z * (1.0f/4096.0f) };
        int ja = j > 0 ? j - 1 : j, jc = (j + 1 < nn) ? j + 1 : j;
        F3 D = { (net[jc].x - net[ja].x) * (1.0f/4096.0f),
                 (net[jc].y - net[ja].y) * (1.0f/4096.0f),
                 (net[jc].z - net[ja].z) * (1.0f/4096.0f) };
        float dn = sqrtf(D.x*D.x + D.y*D.y + D.z*D.z);
        if (dn < 1e-9f) continue;
        D.x /= dn; D.y /= dn; D.z /= dn;
        // perp is radial x parent-tangent, a single direction, so without an
        // explicit side every branch grows on the same side and the set reads
        // as a comb.
        F3 pp = { B.y*D.z - B.z*D.y, B.z*D.x - B.x*D.z, B.x*D.y - B.y*D.x };
        float sgn = (br % 2 == 0) ? 1.0f : -1.0f;
        float pn = sqrtf(pp.x*pp.x + pp.y*pp.y + pp.z*pp.z);
        if (pn < 1e-9f) continue;
        pp.x = pp.x / pn * sgn; pp.y = pp.y / pn * sgn; pp.z = pp.z / pn * sgn;

        // Departure angle and course are ONE decision, made by walking a cone
        // around the parent's heading, so they cannot disagree.
        float ad = uni(VEIN_DEPART_LO, VEIN_DEPART_HI) * DEG;
        float ca = cosf(ad), sa = sinf(ad);
        F3 hd = { D.x*ca + pp.x*sa, D.y*ca + pp.y*sa, D.z*ca + pp.z*sa };
        float dp = hd.x*B.x + hd.y*B.y + hd.z*B.z;
        hd.x -= B.x*dp; hd.y -= B.y*dp; hd.z -= B.z*dp;
        float hn = sqrtf(hd.x*hd.x + hd.y*hd.y + hd.z*hd.z);
        if (hn < 1e-9f) continue;
        hd.x /= hn; hd.y /= hn; hd.z /= hn;

        int na = (int) (arc / (VEIN_BRANCH_DEG * DEG) + 0.5f);
        if (na < 3) na = 3;
        if (na > VEIN_MAXGC - 1) na = VEIN_MAXGC - 1;
        F3 GW[VEIN_MAXGC], GT[VEIN_MAXGC];
        for (int i = 0; i <= na; i++) {
          float t = arc * (float) i / (float) na;
          float c2 = cosf(t), s2 = sinf(t);
          F3 p = { B.x*c2 + hd.x*s2, B.y*c2 + hd.y*s2, B.z*c2 + hd.z*s2 };
          float q = sqrtf(p.x*p.x + p.y*p.y + p.z*p.z);
          F3 q2 = { -B.x*s2 + hd.x*c2, -B.y*s2 + hd.y*c2, -B.z*s2 + hd.z*c2 };
          float q3 = sqrtf(q2.x*q2.x + q2.y*q2.y + q2.z*q2.z);
          GW[i] = F3 { p.x/q, p.y/q, p.z/q };
          GT[i] = F3 { q2.x/q3, q2.y/q3, q2.z/q3 };
        }
        int nb = controls(GW, GT, na, 0.22f);
        // Start exactly at the attachment: catmull's first sample is C[1].
        CPQ[0] = V3 { net[j].x, net[j].y, net[j].z };
        int n2 = catmull(CPQ, nb, VEIN_BPERS, pts);
        pts[0] = CPQ[0];

        // Width, all integer. Thins to half along the run, floored at the
        // one-texel minimum.
        int w0 = (int) ((float) net[j].wq * uni(VEIN_THIN_LO, VEIN_THIN_HI) + 0.5f);
        if (w0 < VEIN_WMIN_Q8) w0 = VEIN_WMIN_Q8;
        int we = w0 >> 1;
        if (we < VEIN_WMIN_Q8) we = VEIN_WMIN_Q8;
        int dq = we - w0;
        int tip8 = (int) (VEIN_TIP_FADE * 256.0f);
        for (int i = 0; i < n2; i++) {
          int th = theta_q8(q8z(pts[i]));
          int t8 = (int) (((uint32_t) i * 256u) / (uint32_t) (n2 - 1));
          int d8 = t8 - (256 - tip8);
          if (d8 < 0) d8 = 0;
          if (d8 > tip8) d8 = tip8;
          int tip = 256 - ((d8 * d8 * (768 - 2 * d8)) >> 16);
          alp[i] = q8c((fade(th) * tip) >> 8);
          wq[i] = (uint8_t) (w0 + (dq * i) / (n2 - 1));
        }
        for (int i = 0; i < n2; i++) {
          if (!alp[i]) continue;
          stamp(((pts[i].x * (int32_t) VEIN_TEX_MID) >> 9) + MID8,
                ((pts[i].y * (int32_t) VEIN_TEX_MID) >> 9) + MID8,
                wq[i], alp[i], pts[i].z >= 0);
        }
        drawn += n2;
        for (int i = 0; i < n2 && nn < VEIN_NET_MAX; i++) {
          int a = alp[i];
          if (a < 13 || (i % 3)) continue;        // same thinning as the trunk
          net[nn].x = (int16_t) pts[i].x; net[nn].y = (int16_t) pts[i].y;
          net[nn].z = (int16_t) pts[i].z;
          net[nn].th8 = (uint16_t) theta_q8(q8z(pts[i]));
          net[nn].alpha = (uint8_t) a;
          net[nn].wq = (uint8_t) wq[i];
          nn++;
        }
      }
    }
    ESP_LOGI("eye", "vessels baked in %u ms, %d samples, net %d",
             (unsigned) (millis() - vb0), drawn, nn);
  }
  #endif

  #if EYE_IRIS_FIBRES
  // Baked once at boot. Stored biased at 128 so one array carries both
  // stroma fibres (above) and crypts (below) with no second channel.
  //
  // Indexed by (ldx * IRIS_TEX_SCALE >> 8) + 48. Deliberately cartesian rather
  // than polar: a polar LUT would be ~1.5 KB instead of 9.4 KB, but it needs an
  // atan2 on each of the ~11,000 cap pixels. Revisit only if 9,409 B of .bss
  // ever becomes the binding constraint.
  static uint8_t IRIS_TEX[IRIS_TEX_SIDE * IRIS_TEX_SIDE];
  static bool iris_built = false;
  if (!iris_built) {
    iris_built = true;
    const int IS = IRIS_TEX_SIDE;
    const float IMID = (float) (IS / 2);
    const float IRAD = (float) (IS / 2 - 1);   // usable radius in texels

    for (int i = 0; i < IS * IS; i++) IRIS_TEX[i] = 128;

    uint32_t iseed = 7717u;
    auto irnd = [&]() {
      iseed = (1103515245u * iseed + 12345u) & 0x7FFFFFFFu;
      return (float) iseed * (1.0f / 2147483648.0f);
    };

    // Parabolic falloff over radius w, keeping the extreme toward `target`.
    // Lighten keeps the max, darken the min.
    auto mark = [&](float fx, float fy, float w, int target, bool lighten) {
      float rr = w * w;
      for (int yy = (int) (fy - w) - 1; yy <= (int) (fy + w) + 1; yy++) {
        if (yy < 0 || yy >= IS) continue;
        for (int xx = (int) (fx - w) - 1; xx <= (int) (fx + w) + 1; xx++) {
          if (xx < 0 || xx >= IS) continue;
          float ex = (float) xx - fx, eyy = (float) yy - fy;
          float d2 = ex * ex + eyy * eyy;
          if (d2 >= rr) continue;
          float a = 1.0f - sqrtf(d2) / w;
          uint8_t &cell = IRIS_TEX[yy * IS + xx];
          int v = lighten ? (int) (128.0f + a * (float) (target - 128))
                          : (int) (128.0f - a * (float) (128 - target));
          if (v < 0) v = 0;
          if (v > 255) v = 255;
          if (lighten ? (v > cell) : (v < cell)) cell = (uint8_t) v;
        }
      }
    };

    // Stroma fibres: radial, from just outside the pupil to the limbus, each
    // wandering a little so they are not spokes.
    //
    // Step size and wander are coupled: 0.10 rad per step is ~4 texels of
    // sideways jump out at the iris rim, which leaves a field of dots rather
    // than radial fibres.
    const int FIBRES = 80;
    const float FR_IN  = IRAD * 0.30f;    // under the pupil edge (0.50), on purpose
    const float FR_OUT = IRAD * 0.96f;    // just inside the limbal ring
    for (int i = 0; i < FIBRES; i++) {
      float ang = 6.2831853f * ((float) i + irnd()) / (float) FIBRES;
      float bright = 0.35f + 0.65f * irnd();
      int steps = (int) ((FR_OUT - FR_IN) * 2.0f);   // ~0.5 texel steps
      // At 1 texel the line staircases into dashes; nothing here is
      // antialiased.
      float w = 1.6f + 0.8f * irnd();
      for (int k = 0; k <= steps; k++) {
        float t = (float) k / (float) steps;
        ang += (irnd() - 0.5f) * 0.012f;
        float r = FR_IN + (FR_OUT - FR_IN) * t;
        mark(IMID + r * cosf(ang), IMID + r * sinf(ang), w,
             (int) (128.0f + 92.0f * bright), true);
      }
    }

    // Collarette: the raised ruff at roughly a third of the iris radius. It is
    // a RING, so it is stamped around a circle - filling a disc there just
    // paints a blob over the pupil margin.
    {
      const float CR = IRAD * 0.36f;
      const int CN = 220;
      for (int i = 0; i < CN; i++) {
        float a = 6.2831853f * (float) i / (float) CN;
        mark(IMID + CR * cosf(a), IMID + CR * sinf(a), 1.8f, 172, true);
      }
    }

    // Crypts: small dark pits clustered just outside the pupil margin.
    for (int i = 0; i < 26; i++) {
      float ang = 6.2831853f * irnd();
      float r = FR_IN + (FR_OUT - FR_IN) * (0.08f + 0.42f * irnd());
      mark(IMID + r * cosf(ang), IMID + r * sinf(ang), 1.4f + 1.6f * irnd(), 96, false);
    }

    // Limbal ring: the dark band where the iris meets the sclera.
    for (int yy = 0; yy < IS; yy++) {
      for (int xx = 0; xx < IS; xx++) {
        float ex = (float) xx - IMID, ey = (float) yy - IMID;
        float r = sqrtf(ex * ex + ey * ey) / IRAD;
        if (r > 0.86f) {
          float a = r - 0.86f;
          if (a > 1.0f) a = 1.0f;
          uint8_t &cell = IRIS_TEX[yy * IS + xx];
          int v = (int) (128.0f - 76.0f * a);
          if (v < cell) cell = (uint8_t) v;
        }
      }
    }
  }
  #endif

  // ================= lookup tables =================
  // Pure functions of compile-time constants, so these are built once: 9,474 sqrtf.
  //
  // Q8 encodes 1.0 as 256, which does NOT fit a uint8_t. NZ_LUT hits 256 at
  // r2=0 and ACROSS_LUT at a=0; casting straight to uint8_t wraps both to 0.
  // With nz=0 the centre pixels compute along=0, fall below COS_IRIS, and
  // shade as mid-grey sclera. Hence EYE_Q8.
  static uint8_t NZ_LUT[R_SQ + 1];
  static uint8_t ACROSS_LUT[257];
  static bool luts_built = false;
  if (!luts_built) {
    luts_built = true;
    #define EYE_Q8(v) ((uint8_t) ((v) > 255 ? 255 : (int) (v)))
    for (int32_t r2 = 0; r2 <= R_SQ; r2++)
      NZ_LUT[r2] = EYE_Q8(sqrtf((float) (R_SQ - r2)) * 256.0f / (float) R + 0.5f);
    for (int a = 0; a <= 256; a++)
      ACROSS_LUT[a] = EYE_Q8(sqrtf(1.0f - ((float) a / 256.0f) * ((float) a / 256.0f)) * 256.0f + 0.5f);
    #undef EYE_Q8
  }

  // ================= per-band bookkeeping =================
  // first_band is always true under a full-frame buffer. It guards against
  // mipi_spi banding, which the lambda cannot detect - see eye-device.yaml.
  display::Rect clip = it.get_clipping();
  bool has_clip = clip.is_set();
  bool first_band = !has_clip || (clip.y == 0);

  // ================= presence =================
  // Runs BEFORE the gaze machine, because the gaze reads pres_f and must see
  // this frame's value rather than the previous one.
  //
  // `presence` is the raw input; everything visual is eased off `pres_f` here,
  // so the pupil, the iris colour and the whole gaze character move together
  // and nothing snaps. Under the same first_band gate as the gaze machine: a
  // banded buffer would otherwise advance this several times per displayed
  // frame.
  //
  // Also the only writer of pres_f and pres_hold. Nothing outside touches them.
  //
  // A change is HELD for a random PRES_DELAY_MIN..MAX frames before any easing
  // begins, so the eye is slow to notice. Two consequences, both intended:
  // a change that reverts before the hold expires restarts the hold rather than
  // being reacted to, and a change back to where pres_f already sits expires
  // with nothing to do - the eye simply never noticed.
  // DEMO OFF DOES NOT OVERRIDE `presence`, IT IGNORES IT. Nothing here writes
  // `presence` except eye-presence.yaml, which keeps its single-writer rule on
  // both targets; there is no second writer to get wrong and no hold protocol
  // for a caller to respect. Pinning pres_f to 0 puts EVERY pres_f-blended value
  // - pupil, iris colour, vein tint, fibre channels and all five gaze
  // parameters - at its rest end in one place, instead of gating each one.
  if (!DEMO) {
    pres_f = 0.0f;
  } else if (first_band) {
    if (presence != pres_seen) {
      pres_seen = presence;
      pres_hold = PRES_DELAY_MIN +
                  (int) (esphome::random_float() *
                         (float) (PRES_DELAY_MAX - PRES_DELAY_MIN));
    }
    if (pres_hold > 0) {
      pres_hold--;
    } else {
      const float want = pres_seen ? 1.0f : 0.0f;
      if (pres_f < want) {
        pres_f += PRES_EASE;
        if (pres_f > want) pres_f = want;
      } else if (pres_f > want) {
        pres_f -= PRES_EASE;
        if (pres_f < want) pres_f = want;
      }
    }
  }

  // Blend every gaze parameter on pres_f. Integer frame counts are truncated
  // toward zero, so a partial blend darts slightly sooner than the exact lerp
  // says; at 90 ms that is under half a frame and not worth a rounding rule.
  const float gaze_frames = GAZE_FRAMES_REST +
                            (GAZE_FRAMES_PRES - GAZE_FRAMES_REST) * pres_f;
  const int hold_min = GAZE_HOLD_MIN_REST +
                       (int) ((GAZE_HOLD_MIN_PRES - GAZE_HOLD_MIN_REST) * pres_f);
  const int hold_max = GAZE_HOLD_MAX_REST +
                       (int) ((GAZE_HOLD_MAX_PRES - GAZE_HOLD_MAX_REST) * pres_f);
  const float stare_chance = GAZE_STARE_CHANCE_REST +
                             (GAZE_STARE_CHANCE_PRES - GAZE_STARE_CHANCE_REST) * pres_f;
  const float tremor_deg = DEMO
      ? (TREMOR_DEG_REST + (TREMOR_DEG_PRES - TREMOR_DEG_REST) * pres_f)
      // Demo off: the manual jitter IS the amplitude. There is no presence end
      // to blend toward, because pres_f is pinned to 0 and never reaches 1.
      // Floored at 0 - a negative amplitude is not a tremor.
      : (look.jitter > 0.0f ? look.jitter : 0.0f);

  // ================= gaze ====================
  // gaze_frames is the smoothness lever, not update_interval: the state
  // machine renders at t = 1/F, 2/F ... 1.0, so F=2 gives a single midpoint
  // and smoothstep(0.5) is exactly 0.5 - a straight linear two-step jump.
  // Without the first_band gate this runs once per band and the gaze advances
  // several times per displayed frame.
  if (first_band && DEMO && gmove > 0) {
    gmove--;
    float t = 1.0f - (float) gmove / gaze_frames;
    // MUST be clamped. gaze_frames SHRINKS as pres_f rises, so a saccade
    // started at 4 frames and now measured against 2 gives t = -0.5, and
    // smoothstep of a negative is a large NEGATIVE - the eye would snap
    // backwards past its start on the way to the target.
    if (t < 0.0f) t = 0.0f;
    if (t > 1.0f) t = 1.0f;
    t = t * t * (3.0f - 2.0f * t);
    yaw   = yaw_s   + (yaw_t   - yaw_s)   * t;
    pitch = pitch_s + (pitch_t - pitch_s) * t;
  } else if (first_band && DEMO && ghold > 0) {
    ghold--;
  } else if (first_band && DEMO) {
    yaw_s   = yaw;
    pitch_s = pitch;
    gmove = (int) gaze_frames;
    if (esphome::random_float() < stare_chance) {
      yaw_t   = (esphome::random_float() - 0.5f) * 2.0f * GAZE_STARE_SPREAD;
      pitch_t = (esphome::random_float() - 0.5f) * 2.0f * GAZE_STARE_SPREAD;
      ghold = GAZE_STARE_HOLD_MIN +
                  (int) (esphome::random_float() * (float) (GAZE_STARE_HOLD_MAX - GAZE_STARE_HOLD_MIN));
    } else {
      float ang = esphome::random_float() * 6.2831853f;
      float rad = sqrtf(esphome::random_float());
      yaw_t   = cosf(ang) * rad * YAW_MAX;
      pitch_t = sinf(ang) * rad * PITCH_MAX;
      ghold = hold_min +
                  (int) (esphome::random_float() * (float) (hold_max - hold_min));
    }
  }

  // Demo off: hold the gaze where the sliders say. Placed AFTER the machine so
  // that turning demo off mid-saccade SNAPS rather than coasting to the old
  // target - gmove stops advancing the moment DEMO goes false.
  //
  // The caller clamps to YAW_MAX/PITCH_MAX. Clamped again here because these are
  // globals, and a global is writable by anything.
  if (!DEMO) {
    float ly = look.yaw, lp = look.pitch;
    if (ly > YAW_MAX) ly = YAW_MAX;
    if (ly < -YAW_MAX) ly = -YAW_MAX;
    if (lp > PITCH_MAX) lp = PITCH_MAX;
    if (lp < -PITCH_MAX) lp = -PITCH_MAX;
    yaw = ly;
    pitch = lp;
  }

  // ================= micro-tremor =================
  // A perfectly still eye reads as a dead object. Added as a RENDER-ONLY
  // offset: folding it back into yaw/pitch would make the gaze
  // random-walk off the globe over time.
  //
  // frame++ MUST stay outside the demo gate. It drives the tremor PHASE, not the
  // gaze: gate it and demo off gives a fixed displacement instead of a shimmer,
  // which produces no error and looks nearly right. That is the worst kind of
  // bug, so it is called out here.
  if (first_band) frame++;
  const float tf = (float) frame;
  const float yaw_trem = (sinf(tf * TREMOR_W1) + 0.55f * sinf(tf * TREMOR_W2 + 1.7f)) * tremor_deg;
  const float pit_trem = (sinf(tf * TREMOR_W2 + 2.3f) + 0.55f * sinf(tf * TREMOR_W1)) * tremor_deg;

  // ================= the eye's frame =================
  const float yaw_rad = (yaw + yaw_trem) * DEG;
  const float pitch_rad = (pitch + pit_trem) * DEG;
  const float cyw = cosf(yaw_rad), syw = sinf(yaw_rad);
  const float cpt = cosf(pitch_rad), spt = sinf(pitch_rad);

  // eye-local basis in screen space (x right, y down, z toward viewer)
  const float fwd_x = syw * cpt, fwd_y = spt,     fwd_z = cyw * cpt;
  const float rgt_x = cyw,          rgt_y = 0.0f, rgt_z = -syw;
  // up = fwd x rgt. The -cyw*spt sign is what makes this orthonormal: with
  // +cyw*spt instead, up.fwd = sin(pitch)*cos(pitch), which is 0.485 at
  // pitch 38, a badly skewed basis.
  const float up_x  = -syw * spt,    up_y  = cpt,   up_z  = -cyw * spt;

  // Q8 for the integer loop
  const int FWD_X = (int) (fwd_x * 256.0f);
  const int FWD_Y = (int) (fwd_y * 256.0f);
  const int FWD_Z = (int) (fwd_z * 256.0f);
  const int RGT_X = (int) (rgt_x * 256.0f);
  const int RGT_Y = (int) (rgt_y * 256.0f);
  const int RGT_Z = (int) (rgt_z * 256.0f);
  const int UP_X  = (int) (up_x  * 256.0f);
  const int UP_Y  = (int) (up_y  * 256.0f);
  const int UP_Z  = (int) (up_z  * 256.0f);

  const int COS_IRIS = (int) (cosf(IRIS_ANGLE * DEG) * 256.0f);
  const int SIN_IRIS = (int) (sinf(IRIS_ANGLE * DEG) * 256.0f);
  // Pupil half-extents, in the eye-local Q8 that ldx and ldy already use.
  // Derived from SIN_IRIS so the two cannot drift, and interpolated by pres_f
  // between the two tunables pairs, so the radar moves the pupil without the
  // per-pixel loop knowing about it. At PUPIL_*_REST both are round.
  //
  // Floored at 1, which is the smallest extent the ellipse test survives. On
  // the cap ldx^2 + ldy^2 <= 256^2 - 222^2, so q tops out at 65536 * 16252 =
  // 1.06e9 and fits int32 - but only just, and only because neither axis can
  // be 0. Both feed a reciprocal. The floor is therefore what keeps a NARROWING
  // pupil safe: it bounds the 1/hx^2 term below, so q cannot grow as the pupil
  // closes.
  // Manual pupil bounds. PUPIL_SPAN below is SIN_IRIS - PUPIL_MEAN, so a
  // half-extent of 1.0 zeroes the span and the iris gradient disappears
  // entirely - the eye becomes a flat black iris. 0.90 still leaves a visible
  // band. THIS CLAMP IS THE GUARANTEE; the HA number's max is only a
  // convenience, because a global is writable by any automation.
  const float PUPIL_LO = 0.05f, PUPIL_HI = 0.90f;
  float pw = PUPIL_W_REST + (PUPIL_W_PRES - PUPIL_W_REST) * pres_f;
  float ph = PUPIL_H_REST + (PUPIL_H_PRES - PUPIL_H_REST) * pres_f;
  if (!DEMO) {
    pw = look.pupil_w;
    ph = look.pupil_h;
    if (pw < PUPIL_LO) pw = PUPIL_LO;
    if (pw > PUPIL_HI) pw = PUPIL_HI;
    if (ph < PUPIL_LO) ph = PUPIL_LO;
    if (ph > PUPIL_HI) ph = PUPIL_HI;
  }
  int hx = (int) (pw * (float) SIN_IRIS);
  int hy = (int) (ph * (float) SIN_IRIS);
  // Load-bearing, and it stays even though the manual clamp above already
  // bounds the half-extents well above 0. See the int32 note below.
  if (hx < 1) hx = 1;
  if (hy < 1) hy = 1;
  const int PUPIL_HX = hx, PUPIL_HY = hy;
  // The gradient starts here, NOT at the pupil edge: the pupil may not be round,
  // and a slit has no single edge for a circular gradient to start from. The
  // mean is what keeps the round pupil bit-identical and gives a slit a band
  // that is neither buried under the pupil nor stranded halfway out.
  const int PUPIL_MEAN = (PUPIL_HX + PUPIL_HY) / 2;
  // NO LONGER FOLDED AT COMPILE TIME. It was, while the half-extents were
  // compile-time constants. pres_f now makes hx and hy move at runtime, so both
  // branches stay in the binary and the compiler cannot drop the round one.
  // Do not turn this back into an #if: the pupil is round only while the room is
  // empty, which is not a build-time property. The round path is the one the
  // verified look was tuned on and must stay reachable.
  const bool PUPIL_ROUND = PUPIL_HX == PUPIL_HY;

  // Fixed directional light, upper left.
  const int LIT_X = (int) (-0.55f * 256.0f);
  const int LIT_Y = (int) (-0.45f * 256.0f);
  const int LIT_Z = (int) (0.70f * 256.0f);
  const int VERTICAL_Q8 = (int) (SHADE_VERTICAL * 256.0f);

  // Lid ramp numerators: (255<<8) / reach-in-pixels, so `dist * NUM >> 8`
  // reaches 255 exactly at the reach and the caller just clamps beyond it.
  // Written as a ratio rather than a per-pixel scale because the Q8 scale
  // itself truncates to 1 at these radii, which silently yields zero shade.
  const int LID_UP_NUM = (255 << 8) / (int) (LID_UPPER_REACH * R);
  const int LID_LO_NUM = (255 << 8) / (int) (LID_LOWER_REACH * R);
  const int LID_LO_OFF = (int) (LID_LOWER_START * R);
  const int LID_UP_S_Q8 = (int) (LID_UPPER_STR * 256.0f);
  const int LID_LO_S_Q8 = (int) (LID_LOWER_STR * 256.0f);

  // Placed on the IRIS, not the pupil. Scaled to the iris it lands ~40 px out,
  // between the pupil edge (30) and the limbus (60); on the pupil the same
  // additive white has no base to lift and blows out into a headlight.
  const int CORNEA_X = CX - 27, CORNEA_Y = CY - 30;
  const int CORNEA_CORE_SQ = CORNEA_R * CORNEA_R;
  const int CORNEA_CORE_K  = (255 << 16) / CORNEA_CORE_SQ;
  const int CORNEA_BLOOM_SQ = CORNEA_BLOOM * CORNEA_BLOOM;
  const int CORNEA_BLOOM_K = (CORNEA_BLOOM_PEAK << 16) / CORNEA_BLOOM_SQ;

  const int SR = SCLERA_LO.r - SCLERA_HI.r;
  const int SG = SCLERA_LO.g - SCLERA_HI.g;
  const int SB = SCLERA_LO.b - SCLERA_HI.b;
  // Every iris colour is one lerp on pres_f, hoisted out of the pixel loop, so
  // the radar costs the same here as it did for the pupil: a handful of
  // multiplies per FRAME, not per pixel. Doing it here and not inside the loop
  // is the whole reason this feature is free at run time.
  #define EYE_LERP(a, b) ((int) ((a) + ((b) - (a)) * pres_f))
  // Demo off: the manual RGB IS the colour, since pres_f is pinned to 0 and the
  // presence colour could never be reached anyway. Clamped to 0..255 because
  // these are globals.
  int IR_R, IR_G, IR_B;
  if (DEMO) {
    IR_R = EYE_LERP(IRIS_REST.r, IRIS_PRES.r);
    IR_G = EYE_LERP(IRIS_REST.g, IRIS_PRES.g);
    IR_B = EYE_LERP(IRIS_REST.b, IRIS_PRES.b);
  } else {
    IR_R = look.iris_r < 0.0f ? 0 : (look.iris_r > 255.0f ? 255 : (int) look.iris_r);
    IR_G = look.iris_g < 0.0f ? 0 : (look.iris_g > 255.0f ? 255 : (int) look.iris_g);
    IR_B = look.iris_b < 0.0f ? 0 : (look.iris_b > 255.0f ? 255 : (int) look.iris_b);
  }
  #if EYE_IRIS_FIBRES
  const int FR_R = EYE_LERP(IRIS_FIBRE_REST.r, IRIS_FIBRE_PRES.r);
  const int FR_G = EYE_LERP(IRIS_FIBRE_REST.g, IRIS_FIBRE_PRES.g);
  const int FR_B = EYE_LERP(IRIS_FIBRE_REST.b, IRIS_FIBRE_PRES.b);
  const int FK_R = EYE_LERP(IRIS_FIBRE_DK_REST.r, IRIS_FIBRE_DK_PRES.r);
  const int FK_G = EYE_LERP(IRIS_FIBRE_DK_REST.g, IRIS_FIBRE_DK_PRES.g);
  const int FK_B = EYE_LERP(IRIS_FIBRE_DK_REST.b, IRIS_FIBRE_DK_PRES.b);
  #endif
  #undef EYE_LERP
  #if EYE_VEINS
  // Hoisted like the iris colours, so the vessel strength costs one lerp per
  // frame and not one per pixel. Demo off: the manual value is the coverage
  // scale outright, clamped to 0..1 - at 0 the vessels vanish entirely, which
  // is a legitimate thing to want and costs nothing.
  float vein_tint = VEIN_TINT_REST + (VEIN_TINT_PRES - VEIN_TINT_REST) * pres_f;
  if (!DEMO) {
    vein_tint = look.vein_tint;
    if (vein_tint < 0.0f) vein_tint = 0.0f;
    if (vein_tint > 1.0f) vein_tint = 1.0f;
  }
  const int VEIN_TINT_Q8 = (int) (vein_tint * 256.0f);
  #endif


  // A 32-bit integer divide is ~50 cycles on the C3 and this loop would do
  // four per pixel. Each is a multiply-shift instead, verified against the
  // division it replaces to a max error of 1 on a 0-255 scale.
  // 65536/R, i.e. 256/R in Q8: (dx * INV_R_Q8) >> 8 == dx/R*256. MUST be
  // recomputed whenever R changes - at 683 (= 65536/96) with R = 120 the
  // normal is 25% too large everywhere and the sphere flattens.
  const int INV_R_Q8 = 546;            // 65536 / 120
  const int RECIP_SHIFT = 16;
  #define EYE_RECIP(d) ((d) > 0 ? (1 << RECIP_SHIFT) / (d) : 1)
  // The iris gradient is CIRCULAR whatever the pupil is, so it is driven by the
  // cap radius and not by the pupil edge. RECIP_SPAN is its scale: full
  // darkening PUPIL_SPAN Q8 units out from the pupil, reaching 255 at the
  // limbus. PUPIL_MEAN is the pupil's average half-extent - at 0.50/0.50 it is
  // PUPIL_HX, so the round pupil is unchanged.
  const int PUPIL_SPAN = SIN_IRIS - PUPIL_MEAN;
  const int RECIP_SPAN = EYE_RECIP(PUPIL_SPAN);
  // PUPIL_RX is 65536 / PUPIL_HX, so `(ldx * PUPIL_RX) >> 8` is 256 exactly
  // on the pupil edge. The shift is 8, NOT 16: 16 lands it on 1.
  const int PUPIL_RX = EYE_RECIP(PUPIL_HX);
  const int PUPIL_RY = EYE_RECIP(PUPIL_HY);
  #undef EYE_RECIP


  // ================= draw =====================
  // Background via it.fill(), which MipiSpiBuffer OVERRIDES with a bulk
  // std::fill_n over the band buffer (~2 cycles/px).
  it.fill(SKIN);

  for (int y = CY - R; y <= CY + R; y++) {
    int dy = y - CY;
    int dy_sq = dy * dy;

    // Row-constants, hoisted out of the inner loop.
    int ny8 = (dy * INV_R_Q8) >> 8;
    int dy_lit = ny8 * LIT_Y;
    int vert = (dy * VERTICAL_Q8) >> 8;

    // Lid shading, hoisted per row: it depends on y only.
    // Upper lid grows toward the top edge, eased so it does not terminate on
    // a hard line at y = CY; the lower lid is weaker and starts further out,
    // because anatomically it sits below the equator.
    int lid = ((CY - y) * LID_UP_NUM) >> 8;
    if (lid < 0) lid = 0;
    if (lid > 255) lid = 255;
    lid = (lid * lid * (768 - 2 * lid)) >> 16;
    int lid2 = ((y - CY - LID_LO_OFF) * LID_LO_NUM) >> 8;
    if (lid2 < 0) lid2 = 0;
    if (lid2 > 255) lid2 = 255;
    lid2 = (lid2 * lid2 * (768 - 2 * lid2)) >> 16;
    int lid_shade = ((lid * LID_UP_S_Q8) >> 8) + ((lid2 * LID_LO_S_Q8) >> 8);

    for (int x = CX - R; x <= CX + R; x++) {
      int dx = x - CX;
      int r2 = dx * dx + dy_sq;
      if (r2 > R_SQ)
        continue;                       // off the eyeball

      int nz8 = NZ_LUT[r2];
      int nx8 = (dx * INV_R_Q8) >> 8;

      int along = (nx8 * FWD_X + ny8 * FWD_Y + nz8 * FWD_Z) >> 8;

      // Surface coordinate in the eye's own frame. Projecting the world normal
      // onto the eye's right/up axes is what makes the texture travel with the
      // globe as it turns.
      //
      // The >> 8 is NOT optional: nx8 and RGT_X are both Q8, so the product
      // is Q16. Without it every index lands outside the 97x97 texture and
      // the bounds check rejects all of them - the iris renders bare.
      //
      // dot(fwd, rgt) and dot(fwd, up) are both exactly 0, so this origin is
      // the iris centre, not the eye centre, and a point on the cap sits at a
      // screen radius of l * R / 256.
      int ldx = (nx8 * RGT_X + ny8 * RGT_Y + nz8 * RGT_Z) >> 8;
      int ldy = (nx8 * UP_X + ny8 * UP_Y + nz8 * UP_Z) >> 8;

      int rr = 0, rg = 0, rb = 0;
      if (along > COS_IRIS) {
        // ---- lens flare ----
        // An anamorphic streak through the iris plus a hot core up-left, to
        // agree with LIT_X / LIT_Y. Iris-local, so it turns with the gaze.
        int flx = (ldx * R) >> 8;
        int fly = (ldy * R) >> 8;
        int ax = flx < 0 ? -flx : flx;
        int ay = fly < 0 ? -fly : fly;

        // Streak: product of the two remaining extents, giving a parabolic
        // cross-section that reaches zero exactly at LEN / THICK. The >> 8 is
        // the scaling; peak is LEN*THICK*PEAK/256.
        int fl = 0;
        if (ax < FLARE_LEN && ay < FLARE_THICK)
          fl = ((FLARE_LEN - ax) * (FLARE_THICK - ay) * FLARE_PEAK) >> 8;

        // (16, 13) is LIT_X,LIT_Y scaled to ~20 px, so the core sits on the key light.
        int dcx = flx + 16, dcy = fly + 13;
        int dc2 = dcx * dcx + dcy * dcy;
        if (dc2 < FLARE_CORE_SQ) {
          int fc = ((FLARE_CORE_SQ - dc2) * FLARE_PEAK) >> 8;
          if (fc > fl) fl = fc;
        }

        // rr/rg/rb start black - that is the pupil - and take the iris
        // shading outside it. The flare is then added on top of BOTH: it is
        // glare on the front surface, so it crosses the pupil rather than
        // stopping at its edge. Applying it after the pupil test buries its
        // peak in a 17 px black disc.
        //
        // The pupil decides only where the black starts. The shading below is
        // measured on across8, the cap radius, so it stays circular whatever
        // shape the pupil is - an ellipse gradient here reads as a distorted
        // iris rather than as a slit in one.
        //
        // `along` is the angle from the forward axis, so the perpendicular
        // component is fixed: across^2 = 1 - along^2.
        int a = along < 0 ? -along : along;
        if (a > 256) a = 256;
        int across8 = ACROSS_LUT[a];

        bool pupil;
        if (PUPIL_ROUND) {
          pupil = across8 < PUPIL_HX;
        } else {
          // Ellipse. qx and qy are Q8 and reach 256 on the edge, so q is
          // 65536 there and grows with the square of the radius.
          int qx = (ldx * PUPIL_RX) >> 8;
          int qy = (ldy * PUPIL_RY) >> 8;
          pupil = qx * qx + qy * qy <= 65536;
        }

        if (!pupil) {
          // Clamp d to PUPIL_SPAN BEFORE the multiply, not s8 to 255 after.
          // RECIP_SPAN is 65536 / PUPIL_SPAN, so this bounds the product by
          // 255 << 16 and leaves s8 in 0..255 with no second clamp. Clamping
          // to PUPIL_SPAN first and to 0 second also absorbs a pupil wider
          // than the iris, where PUPIL_SPAN is negative.
          int d = across8 - PUPIL_MEAN;
          if (d > PUPIL_SPAN) d = PUPIL_SPAN;
          if (d < 0) d = 0;
          int s8 = (d * 255 * RECIP_SPAN) >> RECIP_SHIFT;
          s8 = (s8 * s8 * (768 - 2 * s8)) >> 16;
          int k = 255 - s8;
          rr = (IR_R * k) >> 8;
          rg = (IR_G * k) >> 8;
          rb = (IR_B * k) >> 8;

        #if EYE_IRIS_FIBRES
          // Fibre/crypt detail, signed around the baked 128 bias.
          int ix = ((ldx * IRIS_TEX_SCALE) >> 8) + (IRIS_TEX_SIDE / 2);
          int iy = ((ldy * IRIS_TEX_SCALE) >> 8) + (IRIS_TEX_SIDE / 2);
          if ((unsigned) ix < IRIS_TEX_SIDE && (unsigned) iy < IRIS_TEX_SIDE) {
            int f = (int) IRIS_TEX[iy * IRIS_TEX_SIDE + ix] - 128;
            if (f > 0) {
              rr += ((FR_R - rr) * f) >> 7;
              rg += ((FR_G - rg) * f) >> 7;
              rb += ((FR_B - rb) * f) >> 7;
            } else if (f < 0) {
              int d = -f;
              rr += ((FK_R - rr) * d) >> 7;
              rg += ((FK_G - rg) * d) >> 7;
              rb += ((FK_B - rb) * d) >> 7;
            }
          }
        #endif
        }
        rr += fl; if (rr > 255) rr = 255;
        rg += fl; if (rg > 255) rg = 255;
        rb += fl; if (rb > 255) rb = 255;
      } else {
        // ---- sclera ----
        int lit = (nx8 * LIT_X + dy_lit + nz8 * LIT_Z) >> 8;
        int t8 = 128 - (lit >> 1);
        if (t8 < 0) t8 = 0;
        if (t8 > 255) t8 = 255;
        // Half-strength shoulder. A full smoothstep has zero derivative at
        // t8 = 0, which is the LIT end, so it crushed the whole lit hemisphere
        // into a flat near-white disc. Blending 50/50 with the linear term
        // restores the slope there and still eases the terminator.
        t8 = (((t8 * t8 * (768 - 2 * t8)) >> 16) + t8) >> 1;
        t8 += vert + lid_shade;
        if (t8 < 0) t8 = 0;
        if (t8 > 255) t8 = 255;
        rr = SCLERA_HI.r + ((SR * t8) >> 8);
        rg = SCLERA_HI.g + ((SG * t8) >> 8);
        rb = SCLERA_HI.b + ((SB * t8) >> 8);

      #if EYE_VEINS
        // ---- vessels ----
        // One array, so there is no hemisphere test here at all. At rest every
        // visible pixel has along > 0 and this is exactly right; as the eye
        // turns, pixels with along < 0 read the near-side pattern mirrored. See
        // the note on EYE_VEINS for what that costs.
        //
        // The array is a RING, not a square, so this is three rejects before a
        // read: off the texture, inside the iris, outside the silhouette. Only
        // sclera pixels get here, and the texture is 2*MID+1 across, so |dy| and
        // |dx| are bounded by the texture radius rather than by the panel.
        int tx = ((ldx * RING.mid) >> 8) + RING.mid;
        int ty = ((ldy * RING.mid) >> 8) + RING.mid;
        if ((unsigned) tx < RING.side && (unsigned) ty < RING.side) {
          int dy = ty - RING.mid;
          int ay = dy < 0 ? -dy : dy;
          if (ay <= RING.mid) {
            int dx = tx - RING.mid;
            int ax = dx < 0 ? -dx : dx;
            int wo = RING.hw_out[ay], hwi = RING.hw_in[ay];
            if (ax >= hwi && ax <= wo) {
              int v = RING.tex[RING.rowoff[ty]
                               + (dx < 0 ? (wo - ax)
                                         : (wo - hwi + 1) + (ax - (hwi ? hwi : 1)))];
              if (v) {
                // Straight lerp from the shaded sclera toward the vessel colour.
                // No gamma and no radius-driven hue shift: the baked value is
                // already coverage, which is what the offline model composites.
                int amt = (v * VEIN_TINT_Q8) >> 8;
                rr += ((VEIN_COL.r - rr) * amt) >> 8;
                rg += ((VEIN_COL.g - rg) * amt) >> 8;
                rb += ((VEIN_COL.b - rb) * amt) >> 8;
              }
            }
          }
        }
      #endif
      }

      // ---- catchlight ----
      int cdx = x - CORNEA_X, cdy = y - CORNEA_Y;
      int cd2 = cdx * cdx + cdy * cdy;
      if (cd2 < CORNEA_BLOOM_SQ) {
        int cw = ((CORNEA_BLOOM_SQ - cd2) * CORNEA_BLOOM_K) >> 16;
        if (cd2 < CORNEA_CORE_SQ) {
          int cc = ((CORNEA_CORE_SQ - cd2) * CORNEA_CORE_K) >> 16;
          if (cc > cw) cw = cc;
        }
        rr += cw; if (rr > 255) rr = 255;
        rg += cw; if (rg > 255) rg = 255;
        rb += cw; if (rb > 255) rb = 255;
      }

      it.draw_pixel_at(x, y, Color(rr, rg, rb));
    }
  }
}
