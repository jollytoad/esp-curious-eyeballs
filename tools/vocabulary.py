"""Draw the eye's three coordinate spaces, labelled.

The diagram is generated from the constants in eye-render.cpp, not from a copy
of them, so it cannot drift from the code the way a hand-drawn figure does. If
you change R, IRIS_ANGLE, YAW_MAX or VEIN_TEX_SIDE in the renderer, re-run this:

    .venv/bin/python tools/vocabulary.py

Writes docs/eye-parts.png. There is no CI here, so nothing will remind you.

Three spaces, and the words that keep getting mixed up between them:

  SCREEN    panel pixels. x right, y down, origin top-left. CX, CY, R.
  GLOBE     the unit normal on the eyeball, in the eye's own frame. theta is
            the polar angle from the eye's forward axis (0 = looking straight at
            the viewer, 90 = the silhouette) and phi is azimuth. `along` is the
            forward component, and it is the ONLY thing that distinguishes a
            point from its antipode, because both project to the same texel.
  TEXTURE   texels, one square grid per texture. Note the two grids use the
            SAME scale factor and DIFFERENT centres.
"""
import re
import textwrap
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent.parent
SRC = HERE / "eye-render.cpp"
OUT = HERE / "docs" / "eye-parts.png"

PANEL = 240
SCALE = 2.4
PAD = 18
GAP = 34
TITLE_H = 30
FOOT_H = 132


def consts():
    """Pull the numbers we draw straight out of the renderer.

    Deriving rather than copying is the whole point - a diagram that quotes its
    own constants goes stale silently, and nobody notices until it lies.
    """
    src = SRC.read_text()
    out = {}

    def literal(name):
        r"""A constant whose value is a plain integer.

        \bNAME\s*=\s*(\d+) finds CX/CY/R inside the comma-separated
        `CX = 120, CY = 120, R = 120` as well as in a standalone declaration,
        and does not match `VEIN_TEX_MID = VEIN_TEX_SIDE / 2`.
        """
        m = re.search(r"\b%s\s*=\s*(\d+)" % re.escape(name), src)
        if not m:
            raise SystemExit("consts(): no integer %s in %s" % (name, SRC.name))
        return int(m.group(1))

    def flt(name):
        m = re.search(r"\b%s\s*=\s*([\d.]+)f" % re.escape(name), src)
        if not m:
            raise SystemExit("consts(): no float %s in %s" % (name, SRC.name))
        return float(m.group(1))

    def derived(name, env):
        r"""A constant written as arithmetic on other constants.

        Only integer literals, names already in `env`, and + - * /. C's `/` on
        ints truncates, so it becomes Python's `//`.
        """
        m = re.search(r"\b%s\s*=\s*([^;]+?);" % re.escape(name), src)
        if not m:
            raise SystemExit("consts(): no expression %s in %s" % (name, SRC.name))
        e = re.sub(r"//.*$", "", m.group(1)).strip().rstrip("f")
        e = re.sub(r"[A-Za-z_][A-Za-z_0-9]*",
                   lambda k: "(%d)" % env[k.group(0)], e)
        if not re.fullmatch(r"[\d()+\-*/ ]+", e):
            raise SystemExit("consts(): cannot evaluate %r for %s" % (e, name))
        return int(eval(re.sub(r"(?<!/)/(?!/)", "//", e)))   # noqa: S307

    for name in ("CX", "CY", "R", "IRIS_TEX_SIDE", "IRIS_TEX_SCALE",
                 "VEIN_TEX_SIDE"):
        out[name] = literal(name)
    for name in ("VEIN_TEX_MID", "VEIN_R_IN"):        # depend on the above
        out[name] = derived(name, out)
    for name in ("IRIS_ANGLE", "PUPIL_FRACTION", "YAW_MAX"):
        out[name] = flt(name)

    m = re.search(r"const int CORNEA_X = CX - (\d+), CORNEA_Y = CY - (\d+)", src)
    out["CORNEA_X"] = out["CX"] - int(m.group(1))
    out["CORNEA_Y"] = out["CY"] - int(m.group(2))

    # The two derived radii the diagram exists to make obvious.
    #   limbus on screen : R * sin(IRIS_ANGLE)
    #   far hemisphere   : the theta=90 circle projects to R * cos(yaw)
    out["LIMBUS_R"] = int(round(out["R"] * np.sin(np.radians(out["IRIS_ANGLE"]))))
    out["IRIS_TEX_R"] = int(round(out["IRIS_TEX_SCALE"]
                                  * np.sin(np.radians(out["IRIS_ANGLE"]))))
    out["FAR_R"] = int(round(out["R"] * np.cos(np.radians(out["YAW_MAX"]))))
    out["FAR_PCT"] = int(round(100 * (1 - (out["FAR_R"] / out["R"]) ** 2)))
    return out


def font(size):
    for p in ("/System/Library/Fonts/Supplemental/Arial.ttf",
              "/System/Library/Fonts/Supplemental/Verdana.ttf",
              "/System/Library/Fonts/Helvetica.ttc"):
        try:
            return ImageFont.truetype(p, size)
        except OSError:
            pass
    return ImageFont.load_default()


def label(d, xy, text, f, fill, anchor="mm", halo=(14, 15, 20)):
    """Text with a halo, so it stays readable over hatching or over the sclera.

    Pass halo=None to disable it where the text already sits on a flat field and
    a dark rim would just make it look smudged.
    """
    x, y = xy
    if halo:
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx or dy:
                    d.text((x + dx, y + dy), text, font=f, fill=halo, anchor=anchor)
    d.text((x, y), text, font=f, fill=fill, anchor=anchor)


def wrap_for(d, text, f, max_w):
    """textwrap width in characters, measured rather than guessed."""
    probe = "abcdefghijklmnopqrstuvwxyz "
    per_char = d.textlength(probe, font=f) / len(probe)
    return max(8, int(max_w / per_char))


K = consts()
f_title = font(17)
f_body = font(14)
f_small = font(12)
f_tiny = font(11)
INK = (236, 240, 246)
DIM = (146, 155, 172)
RED = (255, 96, 96)
CYAN = (104, 216, 228)
AMBER = (246, 196, 104)
BG = (17, 19, 25)
BOX = (66, 74, 92)
OUTER = (198, 206, 222)

# ------------------------------------------------------------------ dimensions
cx, cy, R = K["CX"], K["CY"], K["R"]
ir = K["LIMBUS_R"]
pr = int(round(ir * K["PUPIL_FRACTION"]))
far = K["FAR_R"]
ts, mid, rin = K["VEIN_TEX_SIDE"], K["VEIN_TEX_MID"], K["VEIN_R_IN"]

A = int(PANEL * SCALE)                 # screen panel, px
B = int(ts * SCALE)                    # texture grid, px
STRIP = 96                             # the one-row explainer under B
W = PAD * 2 + A + GAP + B
H = TITLE_H + max(A, B + STRIP) + FOOT_H

img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)

# ================================================================ SCREEN SPACE
ax0, ay0 = PAD, TITLE_H
d.text((ax0, 8), "SCREEN SPACE   panel px, x right, y down, origin top-left",
       font=f_title, fill=CYAN)
d.rectangle([ax0, ay0, ax0 + A, ay0 + A], outline=BOX, width=1)


def sc(px, py):
    return int(ax0 + px * SCALE), int(ay0 + py * SCALE)


# eyeball, shaded so it reads as a sphere
for i in range(R, 0, -1):
    t = i / R
    g = int(228 - 66 * (1 - t) ** 1.5)
    x0, y0 = sc(cx - i, cy - i)
    x1, y1 = sc(cx + i, cy + i)
    d.ellipse([x0, y0, x1, y1], fill=(g, g - 3, min(255, g + 8)))

# The far hemisphere: theta > 90 is the annulus between R*cos(yaw) and R. At
# rest it is entirely off-panel; at full yaw it is most of the visible disc, and
# there is no texture for it - it reads the front mirrored.
# The mask has to be the ALPHA, drawn as greyscale, and masked to the eyeball:
# pasting an RGBA overlay uses the mask value directly and ignores the overlay's
# own alpha, which floods the band solid instead of tinting it.
band = Image.new("L", (A, A), 0)
bm = ImageDraw.Draw(band)
bm.ellipse([sc(cx - R, cy - R)[0] - ax0, sc(cx - R, cy - R)[1] - ay0,
            sc(cx + R, cy + R)[0] - ax0, sc(cx + R, cy + R)[1] - ay0], fill=30)
bm.ellipse([sc(cx - far, cy - far)[0] - ax0, sc(cx - far, cy - far)[1] - ay0,
            sc(cx + far, cy + far)[0] - ax0, sc(cx + far, cy + far)[1] - ay0], fill=0)
img.paste((236, 96, 96), (ax0, ay0), band)
d.ellipse([sc(cx - far, cy - far)[0], sc(cx - far, cy - far)[1],
           sc(cx + far, cy + far)[0], sc(cx + far, cy + far)[1]],
          outline=(198, 60, 60), width=2)

# iris
for i in range(ir, 0, -1):
    t = i / ir
    x0, y0 = sc(cx - i, cy - i)
    x1, y1 = sc(cx + i, cy + i)
    d.ellipse([x0, y0, x1, y1],
              fill=(int(146 + 64 * t), int(56 + 30 * t), int(50 + 24 * t)))
d.ellipse([sc(cx - ir, cy - ir)[0], sc(cx - ir, cy - ir)[1],
             sc(cx + ir, cy + ir)[0], sc(cx + ir, cy + ir)[1]],
            outline=(232, 156, 122), width=2)
x0, y0 = sc(cx - pr, cy - pr)
x1, y1 = sc(cx + pr, cy + pr)
d.ellipse([x0, y0, x1, y1], fill=(13, 12, 16))
kx, ky = K["CORNEA_X"], K["CORNEA_Y"]
x0, y0 = sc(kx - 8, ky - 8)
x1, y1 = sc(kx + 8, ky + 8)
d.ellipse([x0, y0, x1, y1], fill=(255, 251, 236))

label(d, sc(cx, cy - int(ir * 0.60)), "IRIS", f_body, (255, 216, 194))
label(d, sc(cx, cy), "pupil", f_tiny, (176, 172, 186))
label(d, sc(cx - int(ir * 0.52), cy - int(ir * 0.80)),
      "theta < %d" % int(K["IRIS_ANGLE"]), f_small, (255, 216, 194))
label(d, sc(cx + int(ir * 0.42), cy + int(ir * 0.80)),
      "limbus  r = %d" % ir, f_small, AMBER)
label(d, sc(cx - int(R * 0.52), cy - int(R * 0.40)), "SCLERA", f_body,
      (28, 32, 42), halo=None)
label(d, sc(cx - int(R * 0.52), cy - int(R * 0.40) + 18),
      "theta %d..90" % int(K["IRIS_ANGLE"]), f_small, (60, 66, 80), halo=None)
label(d, sc(cx - int(R * 0.56), cy + int(R * 0.52)), "far hemisphere", f_small,
      (116, 12, 12), halo=None)
label(d, sc(cx - int(R * 0.56), cy + int(R * 0.52) + 17),
      "r > %d   %d%% at yaw %d" % (far, K["FAR_PCT"], int(K["YAW_MAX"])),
      f_tiny, (116, 12, 12), halo=None)

# panel edges, and the origin
d.line([ax0, ay0, ax0 + 6, ay0], fill=DIM, width=2)
d.line([ax0, ay0, ax0, ay0 + 6], fill=DIM, width=2)
label(d, (ax0 + 12, ay0 + 12), "(0,0)", f_tiny, DIM, "lm")
d.text((ax0 + 4, ay0 + A - 20), "240 x 240", font=f_small, fill=DIM)
label(d, (ax0 + A - 6, ay0 + A - 8), "CX=CY=%d   R=%d" % (cx, R), f_small, DIM, "rm")
label(d, (ax0 + A // 2, ay0 + A - 34),
      "key light %d,%d   (CORNEA_X/Y)" % (kx, ky), f_small, AMBER)

# ============================================================== TEXTURE SPACE
bx0, by0 = PAD + A + GAP, TITLE_H
d.text((bx0, 8), "TEXTURE SPACE   vessel ring, %d x %d texels" % (ts, ts),
       font=f_title, fill=CYAN)
d.rectangle([bx0, by0, bx0 + B, by0 + B], outline=BOX, width=1)

yy, xx = np.mgrid[0:ts, 0:ts]
r = np.hypot(xx - mid + 0.5, yy - mid + 0.5)
ring = (r >= rin) & (r <= mid)
dead = ~ring
buf = np.zeros((ts, ts, 3), np.uint8)
buf[:] = (19, 21, 28)
buf[ring] = (32, 44, 58)
hatch = dead & (((xx + yy) % 6) == 0)
buf[hatch] = (48, 50, 62)
buf[dead & ~hatch] = (22, 24, 32)
img.paste(Image.fromarray(buf).resize((B, B), Image.NEAREST), (bx0, by0))
td = ImageDraw.Draw(img)


def tc(x, y):
    return int(bx0 + x * SCALE), int(by0 + y * SCALE)


for rad, col in ((mid, OUTER), (rin, AMBER)):
    td.ellipse([tc(mid - rad, mid - rad)[0], tc(mid - rad, mid - rad)[1],
                tc(mid + rad, mid + rad)[0], tc(mid + rad, mid + rad)[1]],
               outline=col, width=2)
td.line([tc(0, mid), tc(ts, mid)], fill=(74, 82, 102), width=1)
td.line([tc(mid, 0), tc(mid, ts)], fill=RED, width=1)

label(td, tc(mid, mid), "axis  (%d,%d)" % (mid, mid), f_tiny, (250, 250, 250))
label(td, tc(mid + int((mid + rin) * 0.30), mid - int((mid + rin) * 0.22)),
      "RING", f_body, INK)
label(td, tc(mid, mid - rin // 2), "dead disc\nunder the iris", f_small, DIM)
label(td, tc(26, 26), "dead\ncorners", f_small, DIM)
td.line([tc(26, 40), tc(58, 58)], fill=DIM, width=1)

td.text((bx0 + 8, by0 + 8), "horizon  r = %d   (theta 90, silhouette)" % mid,
        font=f_tiny, fill=OUTER)
td.text((bx0 + 8, by0 + B - 40), "limbus  r = %d" % rin, font=f_tiny, fill=AMBER)
label(td, (bx0 + B - 8, by0 + 22), "AXIS COLUMN  x = %d" % mid, f_small, RED, "rm")

# one row: both halves, stored left-first and adjacent
sy = by0 + B + 30
td.text((bx0, sy - 18), "ONE ROW   both halves stored left-first, adjacent, no gap",
        font=f_small, fill=AMBER)
rh = 15
td.rectangle([bx0, sy, bx0 + B, sy + rh], outline=BOX, width=1)
hm = bx0 + B // 2
td.rectangle([hm, sy, hm + 3, sy + rh], fill=RED)
label(td, ((bx0 + hm) // 2, sy + rh + 12),
      "left half   offset 0 .. wo-hwi", f_small, DIM)
label(td, ((hm + bx0 + B) // 2, sy + rh + 12),
      "right half   offset wo-hwi+1 .. span-1", f_small, DIM)
label(td, (bx0, sy + rh + 34),
      "when hwi == 0 the halves MEET at x = %d: the row is 2*wo+1 texels "
      "and the right half starts at |dx| = 1" % mid, f_tiny, DIM, "lm")

# ==================================================================== FOOTER
fy = TITLE_H + max(A, B + STRIP) + 8
lines = [
    ("GLOBE SPACE   the unit normal in the eye's own frame.  theta = polar angle "
     "from the eye's forward axis, phi = azimuth, along = the forward component.",
     CYAN, f_title),
    ("The sclera branch sees theta %d..90.  theta > 90 is the far hemisphere: it "
     "projects to the SAME texels as theta < 90, and only the sign of `along` "
     "tells the two apart - so with one texture the far side reads the near "
     "side mirrored." % int(K["IRIS_ANGLE"]), DIM, f_small),
    ("Iris texture: %d x %d grid, centre %d, scale %d - used to radius %d only, "
     "so its outer half is dead.  The vessel ring uses the SAME scale factor "
     "and a DIFFERENT centre, which is worth knowing before editing either."
     % (K["IRIS_TEX_SIDE"], K["IRIS_TEX_SIDE"], K["IRIS_TEX_SIDE"] // 2,
        K["IRIS_TEX_SCALE"], K["IRIS_TEX_R"]), DIM, f_small),
]
y = fy
for text, col, fnt in lines:
    for chunk in textwrap.wrap(text, width=wrap_for(d, text, fnt, W - 2 * PAD)):
        d.text((PAD, y), chunk, font=fnt, fill=col)
        y += fnt.size + 4
    y += 6

OUT.parent.mkdir(parents=True, exist_ok=True)
img.save(OUT)
print("wrote %s  (%dx%d)" % (OUT, img.width, img.height))
print("  screen : panel %d, R=%d, limbus r=%d, far hemisphere beyond r=%d (%d%% at yaw %d)"
      % (PANEL, R, ir, far, K["FAR_PCT"], int(K["YAW_MAX"])))
print("  vessel : grid %d, axis %d, ring r %d..%d" % (ts, mid, rin, mid))
print("  iris   : grid %d, scale %d, used to r=%d"
      % (K["IRIS_TEX_SIDE"], K["IRIS_TEX_SCALE"], K["IRIS_TEX_R"]))