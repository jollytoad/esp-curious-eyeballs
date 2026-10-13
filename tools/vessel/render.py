"""Offline scleral-vessel model: 19 trunks, 3 branches each.

NOT the firmware. This is the rig the firmware's vessel parameters are chosen on.
It draws the candidate set at four gaze angles and reports tortuosity, sideways
swing, gap and branch counts, so a change is judged against a measurement.

Two outputs:
  .tmp/sphere.png  the rig view, 400 px supersampled 3x. Judges SHAPE:
                   tortuosity, spacing, whether the set reads as grown.
  .tmp/panel.png   the panel view, 240 px, no supersampling, snapped to the
                   firmware's texel grid. Judges SIZE: width in pixels, and
                   whether a vessel survives quantisation.

The panel view is the one that matters for a width. RAD below is 0.006, which
is 3.6 px on the rig and 0.72 px on the panel - sub-pixel, so the rig alone
cannot show that a trunk has become a dotted line.

Two choices that the C++ cannot rediscover on its own:
  - n_seg 14 over 14/9/7. Fewer segments close the white channels between
    trunks, but the separated look reads better, and shorter trunks lose
    branches to add_branch's `remain < 12` guard.
  - theta_start 30, not 90. The eye rotates 60.98 deg off its front pole at
    worst-case gaze, so the visible sclera is alpha 30..150 - 120 deg of globe.
    The vein texture folds alpha 90..150 back onto alpha 30..90.

Seeds come from os.urandom, so runs are not comparable; that is the same choice
the firmware makes. Parameters, not pixels, are what this preserves.
"""
import importlib.util, math, os, sys
import numpy as np
_HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("v", os.path.join(_HERE, "vessel.py"))
V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)

_r = np.random.default_rng(int.from_bytes(os.urandom(8), "little"))

RAD = 0.006
T0 = 30.0
FE_MAX = 148.0          # no trunk reaches further south than this
FE_MIN = 140.0          # some are drawn short of it
FADE_SPAN = 16.0        # fade_start sits this far north of the trunk's end
N_TRUNK = 19
N_BRANCH = 3
N_SEG = 14
SIGMA = 0.30
ATTACH_POW = 2.0
TIP_FADE = 0.55
JITTER = 0.22
GAP_SEED = int(_r.integers(1 << 30))
TRUNK_SEEDS = _r.integers(1 << 30, size=N_TRUNK).tolist()
BRANCH_SEEDS = _r.integers(1 << 30, size=N_TRUNK).tolist()
G = 6
TILTS = [(180, "SOUTH"), (160, "TILT 160"), (140, "TILT 140"), (120, "TILT 120")]

# ---- panel view ----
# MUST track the firmware's VEIN_TEX_SIDE. The two halves of a texel map to the
# same texture cell, so a texel is (W/2)/(SIDE/2) px across and a vessel
# narrower than that can fall between cells.
#
# Optional argv: SIDE TRUNK_PX [OUT]. Defaults mirror the firmware. Overriding
# both at once is how a width candidate gets judged, because the interesting
# quantity is how many TEXELS wide a trunk is, not how many pixels.
SIDE = int(sys.argv[1]) if len(sys.argv) > 1 else 193
PANEL = 240
# INTENDED VISIBLE width of a trunk, not its radius. The brush falls from full
# at the centre line to nothing at `radius`, so it paints a disc TWICE that
# across, and consecutive stamps 0.5 texel apart saturate that disc solid.
TRUNK_PX = float(sys.argv[2]) if len(sys.argv) > 2 else 3.75
PANEL_OUT = sys.argv[3] if len(sys.argv) > 3 else '.tmp/panel.png'
TEXEL_PX = (PANEL / 2.0) / float(SIDE // 2)
# A branch never thins below the firmware's VEIN_W_MIN, which is a RADIUS. A
# texel centre can sit up to 0.707 texels off the track centreline, so a brush
# narrower than that leaves gaps however densely the curve is sampled, and
# consecutive stamps stop overlapping and the vessel goes dotted.
#
# Every branch tip in the model wants 11 to 42 percent of trunk width, all of
# which is under this floor, so they all clamp to the same value. The trunk has
# to sit above the floor too or the hierarchy inverts and branches come out
# thicker than trunks - which is exactly what a 3.0 px trunk at side 129 does.
W_MIN_TEXELS = 0.75
MIN_FRAC = (2.0 * W_MIN_TEXELS * TEXEL_PX) / TRUNK_PX


def trunk_longitudes(n, rng, jitter):
    gap = 360.0 / n
    g = gap * (1.0 + rng.uniform(-jitter, jitter, n))
    g = g * (360.0 / g.sum())          # jitter the GAPS, not the longitudes,
                                       # or trunks can cross over each other
    lon = np.concatenate([[0.0], np.cumsum(g)[:-1]])
    return (lon + rng.uniform(0.0, gap)) % 360.0, g


def rot_lon(P, lon_deg):
    a = math.radians(lon_deg)
    c, s = math.cos(a), math.sin(a)
    return np.stack([P[:, 0] * c - P[:, 1] * s,
                     P[:, 0] * s + P[:, 1] * c, P[:, 2]], axis=1)


lrng = np.random.default_rng(GAP_SEED)
lons, gaps = trunk_longitudes(N_TRUNK, lrng, JITTER)
grid = np.radians(np.linspace(35.0, 145.0, 45))

TRUNK_END = _r.uniform(FE_MIN, FE_MAX, N_TRUNK)

P, A, RA = [], [], []
pk, tq, nbr = [], [], []
for i in range(N_TRUNK):
    fe = float(TRUNK_END[i])
    fs = fe - FADE_SPAN
    m, th, al = V.build_catmull(SIGMA, tension=0.0, n_seg=N_SEG,
                                seed=TRUNK_SEEDS[i], fade_start=fs,
                                fade_end=fe, theta_start=T0)
    m = rot_lon(m, lons[i])
    la = math.radians(lons[i])
    nrm = np.array([-math.sin(la), math.cos(la), 0.0])
    pk.append(math.degrees(np.max(np.abs(np.interp(grid, th, m @ nrm)))))
    tq.append(V.tortuosity(m[al > 0.05]))
    # branches inherit this trunk's fade, or they outlive their parent
    tp, ta, tr, _ = V.bifurcate(m, al, RAD, n_new=N_BRANCH, seed=BRANCH_SEEDS[i],
                               fade_start=fs, fade_end=fe,
                               attach_pow=ATTACH_POW, tip_fade=TIP_FADE)
    nbr.append(len(tp) - 1)
    P.extend(tp)
    A.extend(ta)
    RA.extend(tr)

# Radii come back in units where a trunk is RAD, so divide it out and the
# whole set is relative to 1.0.
REL = [np.asarray(r, dtype=float) / RAD for r in RA]

print("band theta %.1f..%.1f, sigma %.2f, n_seg %d" % (T0, FE_MAX, SIGMA, N_SEG))
print("trunk south ends: %.1f..%.1f (mean %.1f, max %.1f, cap %.1f)"
      % (TRUNK_END.min(), TRUNK_END.max(), TRUNK_END.mean(),
         TRUNK_END.max(), FE_MAX))
print("seeds: gap %d, trunks %s" % (GAP_SEED, TRUNK_SEEDS[:4]))
print("mean gap %.1f deg (spread %.1f..%.1f, jitter %.0f%%)"
      % (gaps.mean(), gaps.min(), gaps.max(), JITTER * 100))
print("sideways swing %.1f deg, tortuosity %.3f" % (np.mean(pk), np.mean(tq)))
print("branches per trunk: %s" % nbr)
print("%d trunks + %d branches = %d polylines"
      % (N_TRUNK, sum(nbr), len(P)))

# ---- rig view: shape ----
cells = []
for tilt, name in TILTS:
    im = V.render_layers_ortho(P, A, tilt_deg=tilt, radius=RAD)
    # Count before the iris goes on: it is deep red, so scoring after the overlay
    # counts the pupil as vessel.
    red = (im[:, :, 0] - 0.5 * (im[:, :, 1] + im[:, :, 2]) > 40).sum()
    im = V.iris_overlay_ortho(im, tilt, iris_deg=30.0)
    p = np.pad(im, ((G + 12, G), (G, G), (0, 0)), constant_values=255)
    cells.append(V.label(p, "%s red=%d" % (name, red), (0, 0, 0)))
sheet = np.concatenate(cells, axis=1)
sheet = V.label(sheet, "%d trunks  n_seg %d  sigma %.2f  %d branches"
                % (N_TRUNK, N_SEG, SIGMA, sum(nbr)), (0, 0, 0))
V.png('.tmp/sphere.png', sheet)
print("\nwrote .tmp/sphere.png %dx%d" % (sheet.shape[1], sheet.shape[0]))

# ---- panel view: size ----
# R = 1 puts the globe radius at PANEL/2 px, exactly as R=120 does on the panel.
# Visible width is twice the radius, so the knob above halves again here.
half = PANEL / 2.0
unit = TRUNK_PX / (2.0 * half)
texel = TEXEL_PX
pcells = []
for tilt, name in TILTS:
    im = V.render_layers_ortho(P, A, tilt_deg=tilt, W=PANEL, ss=1,
                               radius=unit, radii=[unit * r for r in REL],
                               min_radius=unit * MIN_FRAC, texel=texel)
    im = V.iris_overlay_ortho(im, tilt, W=PANEL, ss=1, iris_deg=30.0)
    p = np.pad(im, ((G + 12, G), (G, G), (0, 0)), constant_values=255)
    pcells.append(V.label(p, name, (0, 0, 0)))
psheet = np.concatenate([np.concatenate(pcells[:2], axis=1),
                         np.concatenate(pcells[2:], axis=1)], axis=0)
psheet = V.label(psheet, "PANEL 240  trunk %.1f px  texel %.2f px  min %.2f px"
                 % (TRUNK_PX, texel, MIN_FRAC * TRUNK_PX), (0, 0, 0))
V.png(PANEL_OUT, psheet)
lo = min(float(r.min()) for r in REL)
hi = max(float(r.max()) for r in REL)
print("wrote %s %dx%d  side %d  trunk %.2f px  texel %.3f px  min %.2f px"
      % (PANEL_OUT, psheet.shape[1], psheet.shape[0], SIDE, TRUNK_PX, texel,
         MIN_FRAC * TRUNK_PX))
print("width relative to trunk: %.2f .. %.2f  (clamped at %.2f)"
      % (lo, hi, MIN_FRAC))
