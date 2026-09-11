"""Turn a wide panoramic render into a true 2:1 equirectangular image.

The image models never output exactly 2:1, and their top/bottom edges are the
weakest part of the frame (the bottom is often a smeared band that becomes an
ugly blob at the nadir once you map it to a sphere). So instead of squashing the
render to 2:1, we:

  1. trim any smeared dark band off the bottom,
  2. pad top and bottom out to a true 2:1, progressively blurring each padded
     row until it converges to a single colour -- this is what a real ground/sky
     pole looks like, and it removes the blob entirely,
  3. colour-match the left and right edges so the 360 wrap has no visible seam,
  4. resize to the final 4096x2048.

Horizontal pixels are never cropped: that would eat into the 360 degrees of yaw
coverage and break the wrap.
"""

import numpy as np
from PIL import Image

FINAL_W, FINAL_H = 4096, 2048


def _trim_smear(a, max_frac=0.10):
    """Drop bottom rows that are much darker than the rest of the lower image."""
    h = a.shape[0]
    ref = float(np.median(a[int(h * 0.60):].mean(axis=(1, 2))))
    row_mean = a.mean(axis=(1, 2))
    limit = int(h * max_frac)
    cut = 0
    for i in range(1, limit + 1):
        if row_mean[h - i] < ref * 0.55:       # markedly darker than the ground
            cut = i
        elif cut and i - cut > 4:              # smear ended, stop scanning
            break
    return a[:h - cut] if cut else a


def _blur_row(row, keep):
    """Horizontally low-pass one row: keep in (0,1], 1 = full detail, ~0 = flat."""
    w = row.shape[0]
    k = max(1, int(round(w * keep)))
    if k >= w:
        return row
    small = Image.fromarray(row[None, :, :].astype(np.uint8)).resize((k, 1), Image.BILINEAR)
    return np.asarray(small.resize((w, 1), Image.BILINEAR), dtype=np.float32)[0]


def _find_horizon(a):
    """Row index of the strongest sky/ground transition, searched near mid-frame."""
    prof = a.mean(axis=(1, 2))
    k = max(3, len(prof) // 100) | 1                       # light smoothing
    prof = np.convolve(prof, np.ones(k) / k, mode="same")
    h = len(prof)
    lo, hi = int(h * 0.25), int(h * 0.75)
    return lo + int(np.argmax(np.abs(np.diff(prof))[lo:hi]))


def _pad_to_2to1(a, centre_horizon=False):
    """Resize the canvas to exactly 2:1.

    By default the padding is split evenly, which preserves wherever the model
    put the horizon -- the prompt asks for it at 50% height and that is where it
    should come from. `centre_horizon=True` re-centres it after the fact, which
    is a fallback rather than the normal path: it crops real pixels away, and it
    hides a framing problem instead of fixing it at the source.

    In a real equirectangular image the horizon sits exactly halfway down. The
    models place it anywhere from ~0.35 to ~0.55, and padding equally top and
    bottom preserves that error -- cross-fading the series then makes the whole
    world bob up and down.

    Each side is padded *or* cropped independently to put exactly target_h/2
    rows above the horizon and the same below. Distributing a fixed amount of
    padding is not enough on its own: when the model places the horizon well off
    centre, the padding budget runs out before the horizon reaches the middle
    and the correction silently clamps.
    """
    h, w = a.shape[:2]
    target_h = w // 2
    half = target_h // 2

    if not centre_horizon:
        pad = target_h - h
        if pad >= 0:
            top_pad, bot_pad = pad // 2, pad - pad // 2
            return np.concatenate([
                np.repeat(a[:1], top_pad, axis=0), a,
                np.repeat(a[-1:], bot_pad, axis=0)], axis=0).astype(np.float32)
        top = (h - target_h) // 2
        return a[top:top + target_h].astype(np.float32)

    hz = _find_horizon(a)
    above, below = hz, h - hz
    top_pad, top_crop = max(0, half - above), max(0, above - half)
    bot_need = target_h - half
    bot_pad, bot_crop = max(0, bot_need - below), max(0, below - bot_need)

    core = a[top_crop:h - bot_crop] if (top_crop or bot_crop) else a
    parts = []
    if top_pad:
        parts.append(np.repeat(core[:1], top_pad, axis=0))
    parts.append(core)
    if bot_pad:
        parts.append(np.repeat(core[-1:], bot_pad, axis=0))
    out = np.concatenate(parts, axis=0).astype(np.float32) if len(parts) > 1 else core.astype(np.float32)

    # Guard against off-by-one from the integer split.
    if out.shape[0] > target_h:
        out = out[:target_h]
    elif out.shape[0] < target_h:
        out = np.concatenate([out, np.repeat(out[-1:], target_h - out.shape[0], axis=0)], axis=0)
    return out


def _converge_poles(a, band_frac=0.14):
    """Progressively blur the top and bottom bands until they reach one colour.

    A pole in an equirectangular image is a single point, so it cannot carry
    horizontal detail -- a real 360 photo smears into it. Crucially this band
    reaches *into* the rendered image rather than starting at the padding
    boundary, otherwise the transition shows up as a hard circle at the pole.
    """
    h, w = a.shape[:2]
    n = max(1, int(h * band_frac))
    out = a.copy()
    for j in range(n):
        t = (j + 1) / n                        # 0 at the pole, 1 at the band edge
        smooth = t * t * (3.0 - 2.0 * t)       # smoothstep: no crease at the edge
        keep = max(1.0 / w, smooth ** 1.8)
        out[j] = _blur_row(a[j], keep)
        out[h - 1 - j] = _blur_row(a[h - 1 - j], keep)
    return out


def _wrap_seam(a, frac=0.03):
    """Make the panorama genuinely tileable across the 360 wrap.

    These models render a wide photo, not a wrapping sphere: the left and right
    edges are usually different scenes entirely (here, buildings against river),
    so simply nudging their colours together paints an obvious band. Instead we
    cross-fade the right overlap onto the left and drop it, the standard way to
    make an image tile. The last column then continues into the first, so the
    viewer can spin past the join without hitting an edge.

    The cost is `frac` of yaw coverage (~11 degrees at 3%) and a soft dissolve
    in that wedge -- far less objectionable than a hard vertical seam.
    """
    h, w = a.shape[:2]

    # First spread the edge brightness difference across the whole 360 as a
    # single linear ramp. A few levels drifting over the full width is
    # imperceptible, whereas leaving the whole step for the narrow overlap makes
    # the blend show up as a pale vertical band -- very visible once a yaw
    # rotation moves that band into the middle of the view.
    a = a.astype(np.float32).copy()
    delta = a[:, 0].mean(axis=0) - a[:, -1].mean(axis=0)    # per channel
    ramp = (np.arange(w, dtype=np.float32) / max(1, w - 1) - 0.5)[None, :, None]
    a = a + delta[None, None, :] * ramp

    ov = max(8, int(w * frac))
    out = a[:, :w - ov].copy()
    t = np.linspace(0.0, 1.0, ov)[None, :, None]           # 0 at x=0 -> 1 inward
    out[:, :ov] = a[:, :ov] * t + a[:, w - ov:] * (1.0 - t)
    return np.clip(out, 0, 255)


_SIG_N = 360


def _yaw_features(a):
    """Per-column descriptors of what sits in each compass direction.

    No single descriptor is trustworthy on its own. The Bund layout is close to
    symmetric -- built-up on the near bank AND (in a modern reference) on the far
    bank -- so a skyline-roughness profile alone has two rival peaks 180 degrees
    apart and will happily face the panorama backwards. Each of these fails in a
    different direction, so their correlation surfaces are summed and the peak is
    taken from the ensemble.
    """
    im = Image.fromarray(np.clip(a, 0, 255).astype(np.uint8)).convert("RGB")
    im = im.resize((_SIG_N, 180))
    rgb = np.asarray(im).astype(np.float32)
    hsv = np.asarray(im.convert("HSV")).astype(np.float32)
    grey = rgb.mean(axis=2)

    def band(x, lo, hi):
        return x[int(180 * lo):int(180 * hi)]

    return [
        band(grey, 0.20, 0.47).std(axis=0),                      # skyline roughness
        band(hsv[:, :, 2], 0.20, 0.47).mean(axis=0),             # sky vs structure
        band(hsv[:, :, 1], 0.52, 0.72).mean(axis=0),             # water vs paving
        band(grey, 0.52, 0.72).std(axis=0),                      # ground texture
        (band(rgb[:, :, 2], 0.52, 0.72) - band(rgb[:, :, 0], 0.52, 0.72)).mean(axis=0),
    ]                                                            # blueness = river


_ref_sig_cache = {}


def _align_yaw(a, ref_path):
    """Rotate the panorama so it faces the same way as the reference.

    The models copy the reference's framing but not its compass orientation -- a
    year can come back rotated a quarter turn, which is what makes a scrub feel
    like the world swings around. An equirectangular image wraps, so yaw is just
    a horizontal roll and this costs nothing.

    Note that edge symmetry cannot police this: a panorama rotated exactly 180
    degrees still has matching left and right edges, so it scores well while
    facing entirely the wrong way. Hence matching against the reference itself.

    Must run *after* the seam is made tileable, or rolling would drag the hard
    edge discontinuity into the middle of the view.
    """
    key = str(ref_path)
    if key not in _ref_sig_cache:
        ref = np.asarray(Image.open(ref_path).convert("RGB")).astype(np.float32)
        _ref_sig_cache[key] = _yaw_features(ref)

    total = np.zeros(_SIG_N, dtype=np.float64)
    for r, q in zip(_ref_sig_cache[key], _yaw_features(a)):
        r = r - r.mean(); q = q - q.mean()
        r = r / (np.linalg.norm(r) + 1e-9)
        q = q / (np.linalg.norm(q) + 1e-9)
        c = np.fft.irfft(np.fft.rfft(r) * np.conj(np.fft.rfft(q)), _SIG_N)
        sd = c.std()
        total += c / (sd + 1e-9)                                 # z-score, then vote

    k = int(np.argmax(total))
    px = int(round(k / _SIG_N * a.shape[1]))
    confidence = float((total.max() - total.mean()) / (total.std() + 1e-9))
    return np.roll(a, -px, axis=1), (k * 360.0 / _SIG_N), confidence


def to_equirect(src_path, out_path, quality=93, align_to=None, yaw_offset=0.0,
                centre_horizon=False):
    """Read a rendered panorama, write it as a true 2:1 equirectangular JPEG.

    `yaw_offset` (degrees) is a manual correction applied after the automatic
    alignment. The auto step fixes gross rotations but the Bund is close enough
    to symmetric that it still lands 180 degrees out on some years, and no image
    statistic reliably breaks that tie -- so those get pinned by hand in the
    location file rather than left to chance.
    """
    a = np.asarray(Image.open(src_path).convert("RGB")).astype(np.float32)
    a = _trim_smear(a)
    a = _wrap_seam(a)          # before padding: this changes the width
    if align_to:
        a, deg, score = _align_yaw(a, align_to)
        to_equirect.last_align = (deg, score)
    if yaw_offset:
        a = np.roll(a, -int(round(yaw_offset / 360.0 * a.shape[1])), axis=1)
    a = _pad_to_2to1(a, centre_horizon=centre_horizon)
    a = _converge_poles(a)
    im = Image.fromarray(a.astype(np.uint8)).resize((FINAL_W, FINAL_H), Image.LANCZOS)
    im.save(out_path, "JPEG", quality=quality)
    return im.size
