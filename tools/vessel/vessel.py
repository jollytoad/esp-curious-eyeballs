"""Scleral vessels on a sphere, for measuring the parameters the firmware bakes.

theta is the polar angle from the optic-nerve pole: theta 0 is the back of the
eye, 180 the iris centre, and 150 the iris edge. render.py draws 19 trunks
across theta 30..148 with branches; everything here is reachable from that.

Control points are offset PERPENDICULAR to the course only, so the coarse run
stays monotone and a curve cannot double back or self-intersect.

Centreline method is Catmull-Rom through Gaussian-scattered control points
(Lo Castro/Tegolo/Valenti). The irregularity is what makes it read as grown;
a sinusoid of matched tortuosity reads as drawn.

Width is not modelled. It is constant here, and the firmware supplies it.
"""
import math, struct, zlib
import numpy as np

TWO = math.pi * 2.0
DEG = math.pi / 180.0


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
    """Arc length over GREAT-CIRCLE distance. ~1.1 is a normal human vessel.

    The divisor MUST be the angular distance, not the 3D chord: a meridian
    follows a great-circle ARC, so a chord is shorter than the path, and a
    straight meridian scores 1.31 on the chord measure.
    """
    chord_ang = math.acos(float(np.clip(np.dot(pts[0], pts[-1]), -1.0, 1.0)))
    arc = float(np.linalg.norm(np.diff(pts, axis=0), axis=1).sum())
    return arc / max(chord_ang, 1e-9)


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


def build_catmull(sigma, tension=0.0, n_seg=6, per_seg=14, seed=7,
                  radius=0.006, fade_start=90.0, fade_end=150.0, mode='independent',
                  theta_start=0.0):
    rng = np.random.default_rng(seed)
    # theta_start clips the vessel to the part of the globe that is EVER seen.
    # theta_start clips the vessel to the part of the globe that is EVER seen.
    # The eye rotates 60.98 deg off its front pole at worst-case gaze, so the
    # visible sclera spans alpha 30..150 - i.e. theta 30..150, not 90..150.
    ths = np.linspace(theta_start * DEG, fade_end * DEG, n_seg + 1)
    W = np.stack([np.sin(ths) * np.ones(n_seg + 1),
                  np.zeros(n_seg + 1), np.cos(ths)], axis=1)
    W /= np.linalg.norm(W, axis=1, keepdims=True)
    Tw = np.stack([np.cos(ths), np.zeros(n_seg + 1), -np.sin(ths)], axis=1)
    Tw /= np.linalg.norm(Tw, axis=1, keepdims=True)
    C = catmull_controls(W, Tw, sigma, rng, mode=mode)
    pts = catmull_eval(C, per_seg, tension)
    return pts, theta_of(pts), alphas_from_theta(theta_of(pts), fade_start, fade_end)


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
    """Lateral offset per control point.

    'independent' draws a fresh Gaussian each time - irregular, no recognisable
    period, which is what reads as a grown vessel. 'smooth' sums three sines.

    sigma is NOT comparable between the two: smooth has lower RMS at the same
    sigma, so one number gives a visibly straighter curve. Compare by
    tortuosity.
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
    # ramp keeps the scatter out of the first control point, or the Gaussian
    # overrides the departure angle the caller asked for and the curve leaves
    # anywhere between 7 and 79 deg off the heading.
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


def fibonacci_sphere(n):
    """Near-uniform directions, standing in for the paper's probability map.

    That map is macula/fovea Gaussians, which have no scleral analogue, so
    uniform coverage plus the distance weighting in bifurcate carries the role.
    """
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

    side = +1 or -1 picks which way it leaves the parent: perp = radial x par_t
    is a single direction, so without it every branch grows on the same side and
    the set reads as a comb.

    The endpoint is placed by walking a CONE around the parent's heading at the
    branch point, so departure angle and course are one decision and cannot
    disagree. length is a fraction of the way to theta_max, which is how a side
    vessel runs most of the way down the globe instead of stopping just past its
    parent.
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
    """Add side vessels, following the paper's iteration: pick an endpoint from a
    probability map, attach to the network, then recompute the map.

    Endpoints are weighted by distance to the existing network, so empty space
    is favoured and new vessels fill gaps instead of stacking.
    """
    rng = np.random.default_rng(seed)
    pts = [main_pts]
    als = [main_als]
    rads = [np.full(len(main_pts), main_radius)]
    # Attach only where alpha > 0.05. A branch on a faded sample appears to
    # start from nothing.
    vis = main_als > 0.05
    net = main_pts[vis].copy()
    netw = np.full(int(vis.sum()), main_radius)
    neta = main_als[vis].copy()
    Tm = np.gradient(main_pts, axis=0)
    Tm /= np.linalg.norm(Tm, axis=1, keepdims=True)
    nett = Tm[vis].copy()
    sides = []
    for k in range(n_new):
        # Consecutive branches on the same side read as a comb.
        side = 1 if (k % 2 == 0) else -1
        cand = fibonacci_sphere(n_cand)
        d = dist_to_network(cand, net)
        w = (d / max(d.max(), 1e-9)) ** dist_power
        w = w * np.exp(-south_bias * cand[:, 2])
        if w.sum() <= 0:
            break
        e = cand[rng.choice(n_cand, p=w / w.sum())]
        # Branch on the solid trunk, not at the endpoint's own nearest point,
        # which lands at the faded tip.
        ok = np.nonzero(neta > 0.35)[0]
        if len(ok) == 0:
            break
        # attach_pow > 0 weights attachment by (theta/fade_end)^attach_pow, which
        # pulls branches south toward the iris. At 0 they scatter uniformly and
        # many land back in the nerve-side wrap, which is rarely visible.
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
        # fade on the parent's schedule
        ths = theta_of(bp)
        a = alphas_from_theta(ths, fade_start, fade_end)
        a[ths / DEG >= fade_end] = 0.0
        # Most branches end well north of fade_start, so the schedule above never
        # reaches them and they stop dead at alpha 1. tip_fade is the fraction
        # of the branch's own length spent easing to zero.
        if tip_fade > 0.0:
            u = np.clip((np.linspace(0.0, 1.0, len(bp)) - (1.0 - tip_fade))
                        / tip_fade, 0.0, 1.0)
            a = a * (1.0 - smoothstep(u))
        als.append(a)
        rads.append(bw)
        Tb = np.gradient(bp, axis=0)
        Tb /= np.linalg.norm(Tb, axis=1, keepdims=True)
        # net, netw, neta and nett are indexed by the SAME j in add_branch, so they
        # must stay the same length and row-aligned. Do NOT filter any of them.
        net = np.concatenate([net, bp])
        netw = np.concatenate([netw, bw])
        neta = np.concatenate([neta, a])
        nett = np.concatenate([nett, Tb])
    return pts, als, rads, sides


def render_layers_ortho(P, A, tilt_deg=90.0, yaw_deg=-90.0, W=400, ss=3,
                        R=1.0, radius=0.006, vcol=(0.80, 0.10, 0.10),
                        ortho_scale=1.0):
    """ORTHOGRAPHIC render, matching the firmware: INV_R_Q8 maps screen offset
    straight to a ray direction, so the sphere is exactly R across the frame and
    a cap at angle A projects to radius sin(A). Perspective would distort size
    and make any vessel-size judgement against the iris meaningless.
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

    # sphere radius R maps to ndc 1/ortho_scale
    px = (np.arange(W*ss) + 0.5)/(W*ss)*2 - 1
    py = 1 - (np.arange(W*ss) + 0.5)/(W*ss)*2
    X, Y = np.meshgrid(px*ortho_scale, py*ortho_scale)
    r2 = (X/R)**2 + (Y/R)**2
    hit = r2 <= 1.0
    Zc = -np.sqrt(np.maximum(1.0 - r2, 0.0)) * R
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
        # pixel = (ndc + 1) * SS / 2. The +1 is required.
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
    """Iris cap at `iris_deg` from the south pole, orthographic so its projected
    radius is sin(iris_deg) of the eyeball radius - matching the firmware's
    VEIN_TEX_MID=96 / cap 48.
    """
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