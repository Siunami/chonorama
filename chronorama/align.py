#!/usr/bin/env python3
"""Measure (and optionally correct) yaw drift across a panorama series.

An equirectangular image wraps, so a horizontal roll is just turning the camera:
it is lossless and introduces no seam. That makes yaw the one geometry error we
can fix perfectly after the fact.

Alignment is measured between CONSECUTIVE years by circular phase correlation.
Neighbouring years look alike, so their correlation peak is sharp; correlating a
1865 frame against 2020 directly would not be. Per-pair shifts are then summed
into an absolute offset for each year relative to an anchor year.

  python3 align.py output/shanghai-bund__gpt25wide            # measure only
  python3 align.py output/shanghai-bund__gpt25wide --apply    # write aligned/
"""
import os, sys, glob, time
import numpy as np
from PIL import Image

N = 1440                     # columns in the correlation signal


def _load(path, size=(N, 180)):
    for attempt in range(4):
        try:
            return np.asarray(Image.open(path).convert("RGB").resize(size)).astype(np.float32)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2)


def signal(path):
    """Per-column descriptor of the skyline band: where the structures are."""
    a = _load(path)
    grey = a.mean(axis=2)
    band = grey[int(180 * 0.28):int(180 * 0.52)]      # horizon-ish, where buildings sit
    s = band.std(axis=0) + 0.5 * np.abs(np.diff(band.mean(axis=0), prepend=band.mean(axis=0)[:1]))
    s = s - s.mean()
    return s / (np.linalg.norm(s) + 1e-9)


def shift_between(a, b):
    """Circular shift (in degrees) that best moves b onto a, plus peak sharpness."""
    A, B = np.fft.rfft(a), np.fft.rfft(b)
    corr = np.fft.irfft(A * np.conj(B), N)
    k = int(np.argmax(corr))
    deg = (k if k <= N // 2 else k - N) * 360.0 / N
    sharp = float((corr.max() - corr.mean()) / (corr.std() + 1e-9))
    return deg, sharp


def main():
    d = sys.argv[1].rstrip("/")
    apply = "--apply" in sys.argv
    years = sorted(int(os.path.basename(p)[:-4]) for p in glob.glob(f"{d}/*.jpg"))
    sigs = {y: signal(f"{d}/{y}.jpg") for y in years}

    # Anchor on the most recent year: its landmarks are the ones we know best.
    anchor = years[-1]
    offset = {anchor: 0.0}
    print(f"{'pair':<14} {'shift°':>8} {'sharpness':>10}")
    for i in range(len(years) - 2, -1, -1):
        y, nxt = years[i], years[i + 1]
        deg, sharp = shift_between(sigs[nxt], sigs[y])
        offset[y] = offset[nxt] + deg
        flag = "  <-- weak" if sharp < 3.0 else ""
        print(f"{y}->{nxt:<9} {deg:>8.1f} {sharp:>10.1f}{flag}")

    vals = np.array([offset[y] for y in years])
    print(f"\ncumulative offset vs {anchor}: min {vals.min():.1f}°  max {vals.max():.1f}°  "
          f"spread {vals.max()-vals.min():.1f}°  std {vals.std():.1f}°")

    if not apply:
        print("\n(measure only — pass --apply to write aligned copies)")
        return

    out = f"{d}_aligned"
    os.makedirs(out, exist_ok=True)
    for y in years:
        im = Image.open(f"{d}/{y}.jpg").convert("RGB")
        a = np.asarray(im)
        px = int(round(offset[y] / 360.0 * a.shape[1]))
        Image.fromarray(np.roll(a, -px, axis=1)).save(f"{out}/{y}.jpg", "JPEG", quality=93)
    import json, shutil
    if os.path.exists(f"{d}/manifest.json"):
        m = json.load(open(f"{d}/manifest.json"))
        m["id"] = os.path.basename(out); m["name"] = m.get("name", "") + " (aligned)"
        json.dump(m, open(f"{out}/manifest.json", "w"), indent=2)
    print(f"\nwrote {len(years)} aligned images to {out}/")


if __name__ == "__main__":
    main()
