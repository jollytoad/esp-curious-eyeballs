"""One blood vessel on a sphere. Clean build: no tree, no branching.

North pole = origin, vessel meanders south, stops short of the pole, and fades
to nothing once past the equator. Width is CONSTANT, so the only thing being
judged is the centreline.

TWO CENTRELINE METHODS, so they can be compared at matched tortuosity:
  build_sine   - heading oscillates sinusoidally. Regular: has a recognisable
                 wavelength, which is why it reads as drawn.
  build_catmull- Catmull-Rom through control points scattered by a Gaussian
                 (Lo Castro/Tegolo/Valenti). Irregular by construction.

TORTUOSITY is arc length / chord length. Normal human retinal vessels are
around 1.1; 1.2-1.4 is moderate pathology, 1.5+ severe. Rather than adopt that
paper's sigma=1 blindly - a value with no stated units - sigma is SWEPT to hit a
target tortuosity in the healthy range.

SPHERE ADAPTATION
  Control points are placed in the tangent frame at the segment's start and
  renormalised onto the sphere. Offsets are PERPENDICULAR to the chord only, so
  the coarse course still advances monotonically and the vessel cannot double
  back on itself.
"""
import math, struct, zlib, sys
import numpy as np

TWO = math.pi * 2.0
DEG = math.pi / 180.0
Z = np.array([0.0, 0.0, 1.0])   # the north pole: vessel origin


def png(path, rgb):
    if rgb.ndim == 2:
        rgb = np.repeat(rgb[..., None], 3, 2)
    h, w, _ = rgb.shape
    raw = bytearray()
    for r in range(h):
        raw += b'\x00' + rgb[r].astype(np.uint8).tobytes()
    def ch(t, d):
        c = t + d
        return struct.pack('>I', len(d)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    open(path, 'wb').write(b'\x89PNG\r\n\x1a\n'
        + ch(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
        + ch(b'IDAT', zlib.compress(bytes(raw), 9)) + ch(b'IEND', b''))


FONT = {
    'N': ["10001", "11001", "11001", "10101", "10011", "10011", "10001"],
    'P': ["11110", "10001", "10001", "11110", "10000", "10000", "10000"],
    'O': ["01110", "10001", "10001", "10001", "10001", "10001", "01110"],
    'L': ["10000", "10000", "10000", "10000", "10000", "10000", "11111"],
    'E': ["11111", "10000", "11110", "10000", "10000", "10000", "11111"],
    'S': ["01111", "10000", "01110", "00001", "00001", "10001", "01110"],
    'T': ["11111", "00100", "00100", "00100", "00100", "00100", "00100"],
    'I': ["11111", "00100", "00100", "00100", "00100", "00100", "11111"],
    'A': ["01110", "10001", "10001", "11111", "10001", "10001", "10001"],
    'D': ["11110", "10001", "10001", "10001", "10001", "10001", "11110"],
    'C': ["01111", "10000", "10000", "10000", "10000", "10000", "01111"],
    'G': ["01111", "10000", "10000", "10011", "10001", "10001", "01111"],
    'K': ["10001", "10010", "11100", "10100", "10010", "10001", "10001"],
    'M': ["10001", "11011", "10101", "10101", "10001", "10001", "10001"],
    'R': ["11110", "10001", "11110", "10100", "10010", "10001", "10001"],
    'U': ["10001", "10001", "10001", "10001", "10001", "10001", "01110"],
    'V': ["10001", "10001", "10001", "10001", "10001", "01010", "00100"],
    'X': ["10001", "10001", "01010", "00100", "01010", "10001", "10001"],
    'Y': ["10001", "10001", "01010", "00100", "00100", "00100", "00100"],
    '0': ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    '2': ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    '3': ["11110", "00001", "00001", "01110", "00001", "00001", "11110"],
    '4': ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    '5': ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    '6': ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    '7': ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    '9': ["01110", "10001", "10001", "01111", "00001", "00001", "10000"],
    '1': ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    '8': ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    '.': ["00000", "00000", "00000", "00000", "00000", "01100", "01100"],
    '/': ["00001", "00010", "00010", "00100", "01000", "01000", "10000"],
    ' ': ["00000"] * 7,
}


def label(img, text, colour=(0, 0, 0)):
    out = img.copy()
    h, w, _ = out.shape
    x = 6
    for ch in text:
        g = FONT.get(ch, FONT[' '])
        for r in range(7):
            for c in range(5):
                if g[r][c] == '1' and (12 + r < h) and (x + c < w):
                    out[12 + r, x + c] = colour
        x += 6
    return out


def smoothstep(t):
    """Accepts a scalar or an array."""
    t = np.clip(np.asarray(t, dtype=float), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


def theta_of(P):
    return np.arccos(np.clip(P[:, 2], -1.0, 1.0))


def alphas_from_theta(ths, fade_start=90.0, fade_end=150.0):
    out = np.ones(len(ths))
    m = ths / DEG > fade_start
    out[m] = 1.0 - smoothstep((ths[m] / DEG - fade_start) / (fade_end - fade_start))
    out[ths / DEG >= fade_end] = 0.0
    return out


def tortuosity(pts):
    """Arc length along the surface / GREAT-CIRCLE distance. ~1.0 is a clean
    great circle, 1.1 is a normal human retinal vessel.

    The divisor MUST be the angular distance, not the 3D chord. A meridian
    follows a great-circle ARC, so a straight chord through the sphere is
    shorter than the path: at 150 deg of span a plain meridian scores 1.31 on
    the chord measure, and every vessel then reads as "severe" regardless of
    how straight it actually is.
    """
    chord_ang = math.acos(float(np.clip(np.dot(pts[0], pts[-1]), -1.0, 1.0)))
    arc = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
    return arc / max(chord_ang, 1e-9)


# ---------------------------------------------------------------- sine method
def build_sine(amp_deg, lambda_deg, phase=0.0, radius=0.006,
               fade_start=90.0, fade_end=150.0, max_samples=60000):
    amp = amp_deg * DEG
    lam = lambda_deg * DEG
    ds = radius * 0.30
    P = np.array([0.0, 0.0, 1.0])
    phi = 0.0
    s = 0.0
    pts = []
    while True:
        th = math.acos(max(-1.0, min(1.0, float(P[2]))))
        pts.append(P.copy())
        if th >= fade_end * DEG or len(pts) >= max_samples:
            break
        d = amp * math.sin(TWO * s / lam + phase)
        st, ct = math.sin(th), math.cos(th)
        Ts = np.array([ct * math.cos(phi), ct * math.sin(phi), -st])
        Te = np.array([-math.sin(phi), math.cos(phi), 0.0])
        H = Ts * math.cos(d) + Te * math.sin(d)
        P = P * math.cos(ds) + H * math.sin(ds)
        P /= np.linalg.norm(P)
        phi = math.atan2(float(P[1]), float(P[0]))
        s += ds
    pts = np.array(pts)
    return pts, theta_of(pts), alphas_from_theta(theta_of(pts), fade_start, fade_end)


# -------------------------------------------------------------- Catmull-Rom
def catmull_eval(C, per_seg, tension):
    """Cardinal spline with tension. s = (1-T)/2, so T=0 is uniform
    Catmull-Rom, T=1 is a straight line, T<0 loops."""
    s = (1.0 - tension) * 0.5
    out = []
    for i in range(len(C) - 3):
        P0, P1, P2, P3 = C[i], C[i + 1], C[i + 2], C[i + 3]
        for j in range(per_seg):
            t = j / per_seg
            t2, t3 = t * t, t * t * t
            out.append((2 * P1 + (-P0 + P2) * t
                        + (2 * P0 - 5 * P1 + 4 * P2 - P3) * t2
                        + (-P0 + 3 * P1 - 3 * P2 + P3) * t3) * s)
    out.append(C[-1])
    Q = np.array(out)
    return Q / np.linalg.norm(Q, axis=1, keepdims=True)


def catmull_controls(W, sigma, rng):
    """Two control points per segment, at 1/3 and 2/3 of the chord, offset
    PERPENDICULARLY by a Gaussian of width sigma * chord_length.

    Perpendicular-only is deliberate: it lets the vessel wander sideways while
    the coarse course keeps advancing monotonically, so it still cannot double
    back or self-intersect.
    """
    C = [W[0]]
    for i in range(len(W) - 1):
        A, B = W[i], W[i + 1]
        ch = np.linalg.norm(B - A)
        t = (B - A) / ch
        perp = np.cross(A, t)
        pn = np.linalg.norm(perp)
        if pn < 1e-9:
            perp = np.cross(A, np.array([0.0, 0.0, 1.0]))
            pn = np.linalg.norm(perp)
        perp = perp / pn
        for f in (1.0 / 3.0, 2.0 / 3.0):
            g = rng.normal(0.0, sigma * ch)
            P = A + t * (ch * f) + perp * g
            C.append(P / np.linalg.norm(P))
    C.append(W[-1])
    return np.array(C)


def build_catmull(sigma, tension=0.0, n_seg=6, per_seg=14, seed=7,
                  radius=0.006, fade_start=90.0, fade_end=150.0, mode='independent',
                  theta_start=0.0):
    rng = np.random.default_rng(seed)
    # theta_start clips the vessel to the part of the globe that is EVER seen.
    # The eyeball's rotation is limited to ~140 deg, so everything north of that
    # is permanently hidden behind the eye: there is no point generating it.
    ths = np.linspace(theta_start * DEG, fade_end * DEG, n_seg + 1)
    W = np.stack([np.sin(ths) * np.ones(n_seg + 1),
                  np.zeros(n_seg + 1), np.cos(ths)], axis=1)
    W /= np.linalg.norm(W, axis=1, keepdims=True)
    # Unit tangents along the meridian: d/dtheta (sin t, 0, cos t).
    Tw = np.stack([np.cos(ths), np.zeros(n_seg + 1), -np.sin(ths)], axis=1)
    Tw /= np.linalg.norm(Tw, axis=1, keepdims=True)
    C = catmull_controls(W, Tw, sigma, rng, mode=mode)
    pts = catmull_eval(C, per_seg, tension)
    return pts, theta_of(pts), alphas_from_theta(theta_of(pts), fade_start, fade_end)


# ------------------------------------------------------------------ rendering
def verify(pts, ths, als, label_):
    d = np.diff(ths)
    off = np.abs(np.linalg.norm(pts, axis=1) - 1.0).max()
    print("    %-22s samples %5d  tortuosity %.3f" % (label_, len(pts), tortuosity(pts)))
    print("      theta %.1f -> %.1f deg | alpha %.2f -> %.2f | max |P|-1 %.2e"
          % (math.degrees(ths[0]), math.degrees(ths[-1]), als.max(), als.min(), off))
    assert off < 1e-9, "points left the sphere"
    assert math.degrees(ths[-1]) < 180.0, "reached the south pole"
    return tortuosity(pts)


def render(pts, ths, als, radius, tilt_deg=90.0, yaw_deg=-90.0, W=400, ss=3,
           R=1.0, dist=2.5, tan_half=0.50, opacity_by_calibre=False):
    t = tilt_deg * DEG
    y = yaw_deg * DEG
    fwd = np.array([0.0, math.sin(t), -math.cos(t)])
    up0 = np.array([0.0, math.cos(t), math.sin(t)])
    cz, sz = math.cos(y), math.sin(y)
    def spin(v):
        return np.array([v[0] * cz + v[1] * sz, -v[0] * sz + v[1] * cz, v[2]])
    fwd = spin(fwd); up = spin(up0)
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    oc = -fwd * dist

    px = (np.arange(W * ss) + 0.5) / (W * ss) * 2 - 1
    py = 1 - (np.arange(W * ss) + 0.5) / (W * ss) * 2
    X, Y = np.meshgrid(px * tan_half, py * tan_half)
    dx = fwd[0] + X * right[0] + Y * up[0]
    dy = fwd[1] + X * right[1] + Y * up[1]
    dz = fwd[2] + X * right[2] + Y * up[2]
    nrm = np.sqrt(dx * dx + dy * dy + dz * dz)
    dx, dy, dz = dx / nrm, dy / nrm, dz / nrm
    b = oc[0] * dx + oc[1] * dy + oc[2] * dz
    c = float(oc @ oc - R * R)
    disc = b * b - c
    tq = np.where(disc > 0, -b - np.sqrt(np.maximum(disc, 0)), np.inf)
    hit = np.isfinite(tq)
    hx = np.where(hit, oc[0] + tq * dx, 0.0)
    hy = np.where(hit, oc[1] + tq * dy, 0.0)
    hz = np.where(hit, oc[2] + tq * dz, 0.0)

    nx, ny, z = hx / R, hy / R, np.clip(hz / R, -1.0, 1.0)
    L = np.array([0.45, 0.55, 0.80]); L /= np.linalg.norm(L)
    lam = np.clip(nx * L[0] + ny * L[1] + z * L[2], 0.0, 1.0)
    rim = np.clip(np.sqrt(np.maximum(disc, 0)) / dist * 3.0, 0, 1)
    base = (0.74 + 0.26 * lam) * hit + 0.14 * rim * hit
    col = np.stack([base, base * 0.98, base * 0.95], -1)

    SS = W * ss
    px_per_unit = SS * 0.5 / tan_half
    A = np.zeros((SS, SS))
    vis = pts @ (-fwd)
    for i in range(len(pts)):
        if vis[i] <= 0.0 or als[i] <= 0.0:
            continue
        d = pts[i] - oc
        zc = float(d @ fwd)
        if zc <= 1e-6:
            continue
        u = float(d @ right) / zc
        v = float(d @ up) / zc
        cx = (u / tan_half * 0.5 + 0.5) * SS
        cy = (0.5 - v / tan_half * 0.5) * SS
        rad = radius * px_per_unit
        x0 = max(int(cx - rad) - 1, 0)
        x1 = min(int(cx + rad) + 2, SS)
        y0 = max(int(cy - rad) - 1, 0)
        y1 = min(int(cy + rad) + 2, SS)
        if x1 <= x0 or y1 <= y0:
            continue
        gx = np.arange(x0, x1) - cx
        gy = np.arange(y0, y1) - cy
        cov = np.clip((rad - np.sqrt(gy[:, None] ** 2 + gx[None, :] ** 2))
                      / max(rad * 0.5, 0.5) + 0.5, 0.0, 1.0)
        blk = A[y0:y1, x0:x1]
        blk += als[i] * cov * (1.0 - blk)

    A *= hit
    col = col * (1.0 - A)[..., None] + np.array([0.80, 0.10, 0.10]) * A[..., None]
    img = np.clip(col, 0, 1).reshape(W, ss, W, ss, 3).mean(axis=(1, 3))
    cover = hit.reshape(W, ss, W, ss).mean(axis=(1, 3))
    img[cover <= 0.02] = (0.09, 0.08, 0.11)
    return (img * 255).astype(np.uint8)


def gc_points(B, D, step, n):
    """Exact great-circle advance: n+1 points and unit tangents."""
    P = np.empty((n + 1, 3))
    T = np.empty((n + 1, 3))
    for i in range(n + 1):
        t = i * step
        P[i] = B * math.cos(t) + D * math.sin(t)
        T[i] = -B * math.sin(t) + D * math.cos(t)
    P /= np.linalg.norm(P, axis=1, keepdims=True)
    T /= np.linalg.norm(T, axis=1, keepdims=True)
    return P, T


def scatter_profile(n, sigma, rng, mode):
    """Lateral offset profile for the control points.

    mode='independent' draws a fresh Gaussian per control point. mode='smooth'
    uses a few low-frequency sines instead.

    INDEPENDENT IS THE DEFAULT AND THE BETTER LOOK. It is irregular at a scale
    that reads as a real vessel: quick direction changes, kinked corners, no
    recognisable period. I once replaced it with the smooth profile while
    chasing a "tangent break" that a later measurement showed did not exist in
    the curve at all - it was measured at branch ENDS, where nothing is drawn.
    The fix cost exactly the quality that made the vessel look grown, so it is
    reverted.

    Both modes are kept because sigma means something different in each: the
    smooth profile has lower RMS at the same sigma, so the same number gives a
    visibly straighter curve. Tortuosity, not sigma, is the portable measure.
    """
    if mode == "smooth":
        t = np.linspace(0.0, 1.0, n)
        prof = np.zeros(n)
        for k in range(1, 4):
            f = rng.uniform(0.7, 2.3)
            prof += rng.uniform(0.4, 1.0) / k * np.sin(TWO * f * t + rng.uniform(0.0, TWO))
        rms = float(np.sqrt((prof ** 2).mean())) or 1.0
        return prof * (sigma / rms)
    return rng.normal(0.0, sigma, n)


def catmull_controls(W, T, sigma, rng, per_seg=2, mode="independent",
                     ramp=0.0):
    """Control points at fractions of each chord, offset PERPENDICULARLY.

    Perpendicular-only keeps the coarse course monotone, so the curve still
    cannot double back on itself or self-intersect.
    """
    npt = (len(W) - 1) * per_seg + 1
    offs = scatter_profile(npt, sigma, rng, mode)
    # Ramp the scatter in from zero at the START. At full strength the first
    # control point is thrown sideways by the Gaussian and the curve leaves at
    # 7-79 deg regardless of the departure angle it was given - measured, not
    # assumed. Tortuosity should be wiggle ON TOP of a chosen heading, not a
    # replacement for it.
    if ramp > 0.0:
        r = np.clip(np.arange(npt) / max(ramp * npt, 1.0), 0.0, 1.0)
        offs = offs * (r * r * (3.0 - 2.0 * r))
    C = []
    k = 0
    for i in range(len(W) - 1):
        perp = np.cross(W[i], T[i])
        pn = np.linalg.norm(perp)
        if pn < 1e-9:
            perp = np.cross(W[i], np.array([0.0, 0.0, 1.0]))
            pn = np.linalg.norm(perp)
        perp = perp / pn
        ch = float(np.linalg.norm(W[i + 1] - W[i]))
        if i == 0:
            C.append(W[0])
        for j in range(1, per_seg + 1):
            f = j / (per_seg + 1.0)
            P = W[i] + T[i] * (ch * f) + perp * (offs[k] * ch)
            C.append(P / np.linalg.norm(P))
            k += 1
    C.append(W[-1])
    return np.array(C)


def build_tree(n_trunks=12, sigma=0.25, seg_arc=12.0, n_seg=4,
               fork_deg=20.0, fork_kids=(1, 1, 2), w_root=0.018,
               w_min=0.0016, theta_max=150.0, sigma_jit=0.25,
               len_jit=0.35, wid_jit=0.30, fork_jit=8.0,
               max_branches=400, seed=7):
    """Branches of a vessel tree. Returns a list of (points, width, gen).

    CALIBRE IS A FUNCTION OF DISTANCE FROM THE DISC, not of generation. That is
    the whole point and it is why the earlier trees were unfixable: keying
    width to generation made reach and thickness the same knob, so every
    attempt to spread the vessels further also made them fatter until the
    sphere filled in. Here a branch can travel to theta_max at a hairline while
    a branch that never forked stays comparatively bold at the same place.

    Per the paper, a child draws from BELOW the main calibre at that distance
    rather than dividing by a fixed factor: "secondary vessels can sometimes
    appear much thinner". Opacity is proportional to calibre, so twigs are
    faint as well as thin and stop competing with the trunks.

    w_min is a RESOLVABLE width, not a token one. Generation 2 otherwise
    spans 0.14-2.24 px radius: the thin end is sub-pixel dust that renders as
    loose dots and threads around the tree. Anything below ~0.7 px cannot be
    drawn meaningfully, so a branch stops being GENERATED there instead.
    """
    rng = np.random.default_rng(seed)
    sa = seg_arc * DEG
    stack = []
    for i in range(n_trunks):
        phi = TWO * i / n_trunks + rng.uniform(-0.12, 0.12)
        D = np.array([math.cos(phi), math.sin(phi), 0.0])
        stack.append((Z.copy(), D, 0,
                      w_root * (1.0 + wid_jit * rng.uniform(-1, 1)),
                      sigma * (1.0 + sigma_jit * rng.uniform(-1, 1))))

    out = []
    while stack and len(out) < max_branches:
        B, D, gen, w0, sg = stack.pop()
        th0 = math.degrees(math.acos(max(-1.0, min(1.0, float(B[2])))))
        run = min(seg_arc * n_seg, theta_max - th0)
        if run < 8.0 or w0 < w_min:
            continue
        na = max(2, int(round(run / seg_arc)))
        step = (run * DEG) / na
        W, T = gc_points(B, D, step, na)
        C = catmull_controls(W, T, sg, rng)
        pts = catmull_eval(C, 10, 0.0)
        ths = theta_of(pts)
        # linear calibre falloff from the disc, times this branch's own draw
        wprof = w0 * np.clip(1.0 - (ths / DEG) / theta_max, 0.0, 1.0)
        # Floor test on the RENDERED width at the branch's first sample, not on
        # the spawn parameter. A branch born at theta=95 with w0=0.0032 only
        # renders 0.0012 wide there because the radial falloff is already 0.37,
        # so testing w0 let unresolvable branches through to be drawn as dust.
        if wprof[0] < w_min:
            continue
        out.append((pts, wprof, gen))

        Pend, Dend = pts[-1], T[-1]
        nk = int(rng.choice(np.array(fork_kids)))
        for j in range(nk):
            frac = 0.0 if nk == 1 else (j / (nk - 1.0)) * 2.0 - 1.0
            a = fork_deg * DEG * frac + math.radians(fork_jit) * rng.uniform(-1, 1)
            c, sn = math.cos(a), math.sin(a)
            Dc = Dend * c + np.cross(Pend, Dend) * sn
            Dc /= np.linalg.norm(Dc)
            stack.append((Pend.copy(), Dc, gen + 1,
                          float(wprof[-1]) * (1.0 - wid_jit * rng.uniform(0.0, 1.0)),
                          sg))
    return out


def fibonacci_sphere(n):
    """Near-uniform directions. Stand-in for the paper's probability map: the
    paper's version is macula/fovea Gaussians, which have no scleral analogue,
    so uniform coverage plus the distance weighting below carries the role."""
    i = np.arange(n) + 0.5
    phi = np.arccos(1.0 - 2.0 * i / n)
    golden = math.pi * (1.0 + 5.0 ** 0.5)
    th = golden * i
    return np.stack([np.cos(th) * np.sin(phi),
                     np.sin(th) * np.sin(phi), np.cos(phi)], axis=1)


def dist_to_network(cand, net):
    """Angular distance from each candidate to the nearest network point."""
    return np.arccos(np.clip(cand @ net.T, -1.0, 1.0)).min(axis=1)


def add_branch(net_pts, net_w, net_a, net_t, j, sigma, rng,
               depart=(30.0, 50.0), length=(0.22, 0.55), theta_max=165.0,
               thin=(0.45, 0.85), side=1):
    """Grow one side vessel off network sample j.

    side = +1 or -1 picks which way it leaves the parent. perp = radial x par_t
    is a single direction, so without this every branch grows to the same side
    of the trunk and the set reads as a comb instead of a tree.

    The endpoint is NOT chosen first and then forced. It is placed by walking
    along a CONE around the parent's own heading at the branch point, so the
    departure angle and the course are the same decision and cannot disagree.

    That fixes the two failures of the previous version: aiming at a freely
    sampled endpoint left at 75-98 deg regardless of the departure setting, and
    the correction that pulled the course onto that endpoint produced tight
    zigzags and beaded tails. Here heading and endpoint are consistent by
    construction, so no correction is needed at all.

    length is a fraction of the way to theta_max, which is how a side vessel
    gets to run most of the way down the globe like a real one instead of
    stopping a few degrees from its parent.
    """
    B = net_pts[j]
    th_j = math.degrees(math.acos(max(-1.0, min(1.0, float(B[2])))))
    if net_a[j] < 0.35:
        return None
    remain = theta_max - th_j
    if remain < 12.0:
        return None
    arc = math.radians(remain * rng.uniform(*length))

    radial = B
    par_t = net_t[j]
    perp = np.cross(radial, par_t)
    perp *= side
    perp /= max(np.linalg.norm(perp), 1e-9)
    a = math.radians(rng.uniform(*depart))
    c, s = math.cos(a), math.sin(a)
    head = par_t * c + perp * s
    head -= radial * float(np.dot(radial, head))
    head /= np.linalg.norm(head)

    na = max(3, int(round(arc / (5.0 * DEG))))
    W, T = gc_points(B, head, arc / na, na)
    C = catmull_controls(W, T, sigma, rng, ramp=0.22)
    C[0] = B
    pts = catmull_eval(C, 10, 0.0)
    pts[0] = B
    ths = theta_of(pts)
    w0 = float(net_w[j]) * rng.uniform(*thin)
    wprof = np.linspace(w0, w0 * 0.5, len(pts))
    return pts, wprof


def bifurcate(main_pts, main_als, main_radius, n_new=14, sigma=0.30,
              fade_start=90.0, fade_end=165.0, n_cand=3000,
              dist_power=1.6, south_bias=0.35, seed=11, attach_pow=0.0,
              tip_fade=0.55):
    """Add side vessels to a main vessel, following the paper's iteration:
    choose an endpoint from a probability map, attach to the nearest point on
    the network, then RECOMPUTE the map before the next iteration.

    Weighting candidate endpoints by their distance to the existing network is
    the paper's probability-map-times-distance-map: empty space is favoured, so
    new vessels fill gaps instead of stacking on top of each other.
    """
    rng = np.random.default_rng(seed)
    pts = [main_pts]
    als = [main_als]
    rads = [np.full(len(main_pts), main_radius)]
    # Attach ONLY to the part of the network that is actually drawn. The main
    # vessel fades to zero alpha at fade_end, and a branch attaching to one of
    # those invisible samples appears to start from nothing - which is exactly
    # the "detached branch" look. The attachment set is the visible skeleton.
    vis = main_als > 0.05
    net = main_pts[vis].copy()
    netw = np.full(int(vis.sum()), main_radius)
    neta = main_als[vis].copy()
    Tm = np.gradient(main_pts, axis=0)
    Tm /= np.linalg.norm(Tm, axis=1, keepdims=True)
    nett = Tm[vis].copy()
    sides = []
    for k in range(n_new):
        # Alternate which side each new branch leaves on. Consecutive branches
        # on the same side read as a comb; alternating gives a tree.
        side = 1 if (k % 2 == 0) else -1
        cand = fibonacci_sphere(n_cand)
        d = dist_to_network(cand, net)
        w = (d / max(d.max(), 1e-9)) ** dist_power
        # favour the southern hemisphere: away from the origin the vessels
        # are spreading out
        w = w * np.exp(-south_bias * cand[:, 2])
        if w.sum() <= 0:
            break
        e = cand[rng.choice(n_cand, p=w / w.sum())]
        # pick a BRANCH POINT on the solid trunk (not on the endpoint's own
        # nearest point, which lands at the faded tip), biased toward mid-trunk
        ok = np.nonzero(neta > 0.35)[0]
        if len(ok) == 0:
            break
        # Weight the attachment point toward the SOUTHERN end of the trunk.
        # attach_pow 0 picks uniformly along the whole trunk, which scatters
        # branches back into the nerve-side wrap where they are rarely seen.
        # Weighting by (theta/theta_max)^attach_pow pulls them down toward the
        # iris, where the sclera actually faces the camera.
        if attach_pow > 0.0:
            th_n = np.degrees(np.arccos(np.clip(net[ok, 2], -1.0, 1.0)))
            w = np.clip(th_n / max(fade_end, 1e-9), 0.0, 1.0) ** attach_pow
            if w.sum() <= 0:
                break
            j = int(ok[rng.choice(len(ok), p=w / w.sum())])
        else:
            j = int(ok[rng.choice(len(ok))])
        br = add_branch(net, netw, neta, nett, j, sigma, rng,
                        theta_max=fade_end, side=side)
        if br is None:
            continue
        bp, bw = br
        pts.append(bp)
        sides.append(side)
        # fade the side vessel on the same schedule as the main one
        ths = theta_of(bp)
        a = alphas_from_theta(ths, fade_start, fade_end)
        a[ths / DEG >= fade_end] = 0.0
        # ALSO fade each branch out along its own length. The theta schedule
        # above only bites if a branch reaches the faded band near the iris,
        # which most never do - they attach mid-trunk and run out of band long
        # before fade_start. Without this every branch held alpha 1.0 to its
        # last sample and stopped dead, leaving a blunt stub.
        # tip_fade is the fraction of the branch's length spent fading, so the
        # rest stays solid where it leaves the parent.
        if tip_fade > 0.0:
            u = np.clip((np.linspace(0.0, 1.0, len(bp)) - (1.0 - tip_fade))
                        / tip_fade, 0.0, 1.0)
            a = a * (1.0 - smoothstep(u))
        als.append(a)
        rads.append(bw)
        Tb = np.gradient(bp, axis=0)
        Tb /= np.linalg.norm(Tb, axis=1, keepdims=True)
        # net, nett and neta are indexed by the SAME j in add_branch, so they
        # must stay the same length and row-aligned. Filtering neta by a>0.05
        # here desynchronised it from net/Tb and attached later branches to the
        # wrong parent point.
        net = np.concatenate([net, bp])
        netw = np.concatenate([netw, bw])
        neta = np.concatenate([neta, a])
        nett = np.concatenate([nett, Tb])
    return pts, als, rads, sides


def render_layers_ortho(P, A, tilt_deg=90.0, yaw_deg=-90.0, W=400, ss=3,
                        R=1.0, radius=0.006, vcol=(0.80, 0.10, 0.10),
                        ortho_scale=1.0):
    """ORTHOGRAPHIC render. This is what the eyeball project uses: INV_R_Q8
    maps screen offset straight to a ray direction, so the sphere is exactly R
    across the frame and a cap at angle A has projected radius sin(A).

    The perspective renderer distorted size badly - at dist=2.5 a 30 deg iris
    read as ~0.70 of the eyeball radius instead of 0.50 - which makes any
    judgement about vessel size against the iris meaningless.
    """
    t = tilt_deg * DEG
    y = yaw_deg * DEG
    fwd = np.array([0.0, math.sin(t), -math.cos(t)])
    up0 = np.array([0.0, math.cos(t), math.sin(t)])
    cz, sz = math.cos(y), math.sin(y)
    def spin(v):
        return np.array([v[0]*cz + v[1]*sz, -v[0]*sz + v[1]*cz, v[2]])
    fwd = spin(fwd); up = spin(up0)
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)

    # camera-space offsets; sphere radius R maps to ndc 1/ortho_scale
    px = (np.arange(W*ss) + 0.5)/(W*ss)*2 - 1
    py = 1 - (np.arange(W*ss) + 0.5)/(W*ss)*2
    X, Y = np.meshgrid(px*ortho_scale, py*ortho_scale)
    r2 = (X/R)**2 + (Y/R)**2
    hit = r2 <= 1.0
    Zc = -np.sqrt(np.maximum(1.0 - r2, 0.0)) * R
    # surface points in world coords
    hx = right[0]*X + up[0]*Y + fwd[0]*Zc
    hy = right[1]*X + up[1]*Y + fwd[1]*Zc
    hz = right[2]*X + up[2]*Y + fwd[2]*Zc

    nx, ny, z = hx/R, hy/R, np.clip(hz/R, -1.0, 1.0)
    L = np.array([0.45, 0.55, 0.80]); L /= np.linalg.norm(L)
    lam = np.clip(nx*L[0] + ny*L[1] + z*L[2], 0.0, 1.0)
    Hv = L - fwd; Hv /= np.linalg.norm(Hv)
    spec = np.clip(nx*Hv[0] + ny*Hv[1] + z*Hv[2], 0.0, 1.0) ** 40
    edge = np.clip((1.0 - np.sqrt(np.maximum(r2, 0.0))) * 26.0, 0, 1)
    base = (0.74 + 0.26*lam)*hit + 0.14*edge*hit
    col = np.stack([base, base*0.98, base*0.95], -1)

    SS = W*ss
    px_per_unit = SS*0.5
    acc = np.zeros((SS, SS))
    rad_px = radius*R*px_per_unit
    reach = rad_px + 1.0
    for pts, al in zip(P, A):
        front = pts @ fwd < 0.0            # facing the camera
        idx = np.nonzero(front & (al > 0.0))[0]
        if len(idx) == 0:
            continue
        # ndc = camera coordinate, then pixel = (ndc+1)*SS/2. The previous
        # form omitted the +1, shifting every vessel left by half the frame and
        # pushing most of it outside the image - which is why the orthographic
        # renders showed a bare eyeball.
        cx = ((pts[idx] @ right)/ortho_scale + 1.0)*px_per_unit
        cy = (1.0 - (pts[idx] @ up)/ortho_scale)*px_per_unit
        bx0 = max(int(cx.min()-reach), 0); bx1 = min(int(cx.max()+reach)+1, SS)
        by0 = max(int(cy.min()-reach), 0); by1 = min(int(cy.max()+reach)+1, SS)
        if bx1 <= bx0 or by1 <= by0:
            continue
        for k, i in enumerate(idx):
            x0 = max(int(cx[k]-rad_px)-1, bx0); x1 = min(int(cx[k]+rad_px)+2, bx1)
            y0 = max(int(cy[k]-rad_px)-1, by0); y1 = min(int(cy[k]+rad_px)+2, by1)
            if x1 <= x0 or y1 <= y0:
                continue
            gx = np.arange(x0, x1) - cx[k]
            gy = np.arange(y0, y1) - cy[k]
            cov = np.clip((rad_px - np.sqrt(gy[:, None]**2 + gx[None, :]**2))
                          / max(rad_px*0.5, 0.5) + 0.5, 0.0, 1.0)
            blk = acc[y0:y1, x0:x1]
            blk += float(al[i])*cov*(1.0 - blk)
    acc *= hit
    col = col*(1.0-acc)[..., None] + np.array(vcol)*acc[..., None]
    img = np.clip(col, 0, 1).reshape(W, ss, W, ss, 3).mean(axis=(1, 3))
    cov = hit.reshape(W, ss, W, ss).mean(axis=(1, 3))
    img[cov <= 0.02] = (0.09, 0.08, 0.11)
    return (img*255).astype(np.uint8)


def iris_overlay_ortho(img, tilt_deg, yaw_deg=-90.0, W=400, ss=3, R=1.0,
                       iris_deg=30.0, ortho_scale=1.0):
    """Iris cap at `iris_deg` from the south pole, drawn orthographically so
    its projected radius is sin(iris_deg) of the eyeball radius - matching the
    main project's VEIN_TEX_MID=96 / cap 48 relationship."""
    t = tilt_deg*DEG; y = yaw_deg*DEG
    fwd = np.array([0.0, math.sin(t), -math.cos(t)])
    up0 = np.array([0.0, math.cos(t), math.sin(t)])
    cz, sz = math.cos(y), math.sin(y)
    def spin(v):
        return np.array([v[0]*cz + v[1]*sz, -v[0]*sz + v[1]*cz, v[2]])
    fwd = spin(fwd); up = spin(up0)
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    px = (np.arange(W*ss)+0.5)/(W*ss)*2-1
    py = 1-(np.arange(W*ss)+0.5)/(W*ss)*2
    X, Y = np.meshgrid(px*ortho_scale, py*ortho_scale)
    r2 = (X/R)**2 + (Y/R)**2
    hit = r2 <= 1.0
    Zc = -np.sqrt(np.maximum(1.0-r2, 0.0))*R
    hz = right[2]*X + up[2]*Y + fwd[2]*Zc
    ang = np.arccos(np.clip(-hz/R, -1.0, 1.0))
    a = iris_deg*DEG
    inside = ((ang < a) & hit).reshape(W, ss, W, ss).mean(axis=(1, 3))
    ring = ((np.abs(ang - a) < 1.5*DEG) & hit).reshape(W, ss, W, ss).mean(axis=(1, 3))
    out = img.astype(float)
    m = inside > 0.5
    out[m] = out[m]*0.30 + np.array([72, 42, 32])*0.70
    rg = ring > 0.35
    out[rg] = np.array([40, 200, 220])
    return np.clip(out, 0, 255).astype(np.uint8)


def render_layers(P, A, tilt_deg=90.0, yaw_deg=-90.0, W=400, ss=3,
                  R=1.0, dist=2.5, tan_half=0.50, radius=0.006,
                  vcol=(0.80, 0.10, 0.10)):
    """Render several vessels into one image, each with its own alpha.

    The vessel colour parameter is vcol, NOT col: a local col holding the sphere
    shading shadows it, and compositing that composites the sphere onto itself,
    which renders as a blank ball while still writing plenty of bright pixels.
    """
    t = tilt_deg * DEG
    y = yaw_deg * DEG
    fwd = np.array([0.0, math.sin(t), -math.cos(t)])
    up0 = np.array([0.0, math.cos(t), math.sin(t)])
    cz, sz = math.cos(y), math.sin(y)
    def spin(v):
        return np.array([v[0]*cz + v[1]*sz, -v[0]*sz + v[1]*cz, v[2]])
    fwd = spin(fwd); up = spin(up0)
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    oc = -fwd * dist

    px = (np.arange(W*ss)+0.5)/(W*ss)*2-1
    py = 1 - (np.arange(W*ss)+0.5)/(W*ss)*2
    X, Y = np.meshgrid(px*tan_half, py*tan_half)
    dx = fwd[0] + X*right[0] + Y*up[0]
    dy = fwd[1] + X*right[1] + Y*up[1]
    dz = fwd[2] + X*right[2] + Y*up[2]
    nrm = np.sqrt(dx*dx + dy*dy + dz*dz)
    dx, dy, dz = dx/nrm, dy/nrm, dz/nrm
    b = oc[0]*dx + oc[1]*dy + oc[2]*dz
    c = float(oc @ oc - R*R)
    disc = b*b - c
    tq = np.where(disc > 0, -b - np.sqrt(np.maximum(disc, 0)), np.inf)
    hit = np.isfinite(tq)
    hx = np.where(hit, oc[0]+tq*dx, 0.0)
    hy = np.where(hit, oc[1]+tq*dy, 0.0)
    hz = np.where(hit, oc[2]+tq*dz, 0.0)

    nx, ny, z = hx/R, hy/R, np.clip(hz/R, -1.0, 1.0)
    L = np.array([0.45, 0.55, 0.80]); L /= np.linalg.norm(L)
    lam = np.clip(nx*L[0] + ny*L[1] + z*L[2], 0.0, 1.0)
    rim = np.clip(np.sqrt(np.maximum(disc, 0))/dist*3.0, 0, 1)
    base = (0.74 + 0.26*lam)*hit + 0.14*rim*hit
    col = np.stack([base, base*0.98, base*0.95], -1)

    SS = W*ss
    px_per_unit = SS*0.5/tan_half
    acc = np.zeros((SS, SS))
    for pts, al in zip(P, A):
        vis = pts @ (-fwd)
        rad_px = radius * px_per_unit
        reach = rad_px + 1.0
        idx = np.nonzero((vis > 0.0) & (al > 0.0))[0]
        if len(idx) == 0:
            continue
        d = pts[idx] - oc[None, :]
        zc = np.where(d @ fwd > 1e-6, d @ fwd, 1e-6)
        u = (d @ right)/zc; v = (d @ up)/zc
        sxs = (u/tan_half*0.5 + 0.5)*SS
        sys_ = (0.5 - v/tan_half*0.5)*SS
        bx0 = max(int(sxs.min()-reach), 0); bx1 = min(int(sxs.max()+reach)+1, SS)
        by0 = max(int(sys_.min()-reach), 0); by1 = min(int(sys_.max()+reach)+1, SS)
        if bx1 <= bx0 or by1 <= by0:
            continue
        for i in idx:
            dd = pts[i] - oc
            zc2 = max(float(dd @ fwd), 1e-6)
            cx = (float(dd @ right)/zc2/tan_half*0.5 + 0.5)*SS
            cy = (0.5 - float(dd @ up)/zc2/tan_half*0.5)*SS
            x0 = max(int(cx-rad_px)-1, bx0); x1 = min(int(cx+rad_px)+2, bx1)
            y0 = max(int(cy-rad_px)-1, by0); y1 = min(int(cy+rad_px)+2, by1)
            if x1 <= x0 or y1 <= y0:
                continue
            gx = np.arange(x0, x1) - cx
            gy = np.arange(y0, y1) - cy
            cov = np.clip((rad_px - np.sqrt(gy[:,None]**2 + gx[None,:]**2))
                          / max(rad_px*0.5, 0.5) + 0.5, 0.0, 1.0)
            blk = acc[y0:y1, x0:x1]
            blk += float(al[i]) * cov * (1.0 - blk)
    acc *= hit
    col = col*(1.0-acc)[..., None] + np.array(vcol)*acc[..., None]
    img = np.clip(col, 0, 1).reshape(W, ss, W, ss, 3).mean(axis=(1, 3))
    cover = hit.reshape(W, ss, W, ss).mean(axis=(1, 3))
    img[cover <= 0.02] = (0.09, 0.08, 0.11)
    return (img*255).astype(np.uint8)


def render_many(branches, tilt_deg=90.0, yaw_deg=-90.0, W=400, ss=3,
                R=1.0, dist=2.5, tan_half=0.50, w_ref=0.018, w_min=0.0008):
    t = tilt_deg * DEG
    y = yaw_deg * DEG
    fwd = np.array([0.0, math.sin(t), -math.cos(t)])
    up0 = np.array([0.0, math.cos(t), math.sin(t)])
    cz, sz = math.cos(y), math.sin(y)
    def spin(v):
        return np.array([v[0] * cz + v[1] * sz, -v[0] * sz + v[1] * cz, v[2]])
    fwd = spin(fwd); up = spin(up0)
    right = np.cross(fwd, up); right /= np.linalg.norm(right)
    up = np.cross(right, fwd)
    oc = -fwd * dist

    px = (np.arange(W * ss) + 0.5) / (W * ss) * 2 - 1
    py = 1 - (np.arange(W * ss) + 0.5) / (W * ss) * 2
    X, Y = np.meshgrid(px * tan_half, py * tan_half)
    dx = fwd[0] + X * right[0] + Y * up[0]
    dy = fwd[1] + X * right[1] + Y * up[1]
    dz = fwd[2] + X * right[2] + Y * up[2]
    nrm = np.sqrt(dx * dx + dy * dy + dz * dz)
    dx, dy, dz = dx / nrm, dy / nrm, dz / nrm
    b = oc[0] * dx + oc[1] * dy + oc[2] * dz
    c = float(oc @ oc - R * R)
    disc = b * b - c
    tq = np.where(disc > 0, -b - np.sqrt(np.maximum(disc, 0)), np.inf)
    hit = np.isfinite(tq)
    hx = np.where(hit, oc[0] + tq * dx, 0.0)
    hy = np.where(hit, oc[1] + tq * dy, 0.0)
    hz = np.where(hit, oc[2] + tq * dz, 0.0)

    nx, ny, z = hx / R, hy / R, np.clip(hz / R, -1.0, 1.0)
    L = np.array([0.45, 0.55, 0.80]); L /= np.linalg.norm(L)
    lam = np.clip(nx * L[0] + ny * L[1] + z * L[2], 0.0, 1.0)
    rim = np.clip(np.sqrt(np.maximum(disc, 0)) / dist * 3.0, 0, 1)
    base = (0.74 + 0.26 * lam) * hit + 0.14 * rim * hit
    col = np.stack([base, base * 0.98, base * 0.95], -1)

    SS = W * ss
    px_per_unit = SS * 0.5 / tan_half
    A = np.zeros((SS, SS))
    for (pts, wprof, gen) in branches:
        vis = pts @ (-fwd)
        idx = np.nonzero((vis > 0.0) & (wprof > w_min * 0.4))[0]
        if len(idx) == 0:
            continue
        # bounding box so a branch does not scan the whole frame
        d = pts[idx] - oc[None, :]
        zc = d @ fwd
        zc = np.where(zc > 1e-6, zc, 1e-6)
        u = (d @ right) / zc
        v = (d @ up) / zc
        sxs = (u / tan_half * 0.5 + 0.5) * SS
        sys_ = (0.5 - v / tan_half * 0.5) * SS
        pad = float(wprof[idx].max() * px_per_unit) + 2.0
        bx0 = max(int(sxs.min() - pad), 0); bx1 = min(int(sxs.max() + pad) + 1, SS)
        by0 = max(int(sys_.min() - pad), 0); by1 = min(int(sys_.max() + pad) + 1, SS)
        if bx1 <= bx0 or by1 <= by0:
            continue
        for i in idx:
            u = float((pts[i] - oc) @ right) / max(float((pts[i] - oc) @ fwd), 1e-6)
            v = float((pts[i] - oc) @ up) / max(float((pts[i] - oc) @ fwd), 1e-6)
            cx = (u / tan_half * 0.5 + 0.5) * SS
            cy = (0.5 - v / tan_half * 0.5) * SS
            rad = max(wprof[i] * px_per_unit, 0.40)
            alpha = min(1.0, wprof[i] / w_ref)
            x0 = max(int(cx - rad) - 1, bx0); x1 = min(int(cx + rad) + 2, bx1)
            y0 = max(int(cy - rad) - 1, by0); y1 = min(int(cy + rad) + 2, by1)
            if x1 <= x0 or y1 <= y0:
                continue
            gx = np.arange(x0, x1) - cx
            gy = np.arange(y0, y1) - cy
            cov = np.clip((rad - np.sqrt(gy[:, None] ** 2 + gx[None, :] ** 2))
                          / max(rad * 0.5, 0.5) + 0.5, 0.0, 1.0)
            blk = A[y0:y1, x0:x1]
            blk += alpha * cov * (1.0 - blk)

    A *= hit
    col = col * (1.0 - A)[..., None] + np.array([0.80, 0.10, 0.10]) * A[..., None]
    img = np.clip(col, 0, 1).reshape(W, ss, W, ss, 3).mean(axis=(1, 3))
    cover = hit.reshape(W, ss, W, ss).mean(axis=(1, 3))
    img[cover <= 0.02] = (0.09, 0.08, 0.11)
    return (img * 255).astype(np.uint8)


def show(img):
    pass


if __name__ == '__main__':
    branches = build_tree()
    gens = {}
    for br in branches:
        gens[br[2]] = gens.get(br[2], 0) + 1
    print("  branches %d  per generation %s" % (len(branches), [gens[g] for g in sorted(gens)]))
    W = np.concatenate([b[1] for b in branches])
    print("  calibre range %.4f .. %.4f" % (W.min(), W.max()))
    panels = []
    for tilt, name in ((0, "N POLE"), (45, "TILT 45"), (90, "TILT 90"), (135, "TILT 135")):
        im = render_many(branches, tilt_deg=tilt)
        p = np.pad(im, ((6 + 12, 6), (6, 6), (0, 0)), constant_values=255)
        panels.append(label(p, name, (0, 0, 0)))
    sheet = np.concatenate(panels, axis=1)
    png('.tmp/sphere.png', sheet)
    print("wrote .tmp/sphere.png %dx%d" % (sheet.shape[1], sheet.shape[0]))