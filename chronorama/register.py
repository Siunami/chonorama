"""Compile reviewed panorama landmarks into small, non-destructive UV maps.

Usage: python register.py output/shanghai-bund__gpt25aligned
Requires numpy and scipy; the static site only needs the compiled JSON.
"""

import argparse
import base64
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.interpolate import RBFInterpolator, RegularGridInterpolator


WIDTH, HEIGHT = 129, 65
RANGE = 0.125


def controls(frame):
    a, b, c = frame["rail_curve"]
    points = {f"rail_{x}": [x, a * (x - .52) ** 2 + b * (x - .52) + c]
              for x in [.37, .43, .50, .57, .64, .69]}
    points.update({f"bank_{x}": [x, frame["bank_y"]]
                   for x in [.36, .42, .65, .72]})
    points.update(frame["landmarks"])
    return points


def compile_maps(library):
    annotations = json.loads((library / "landmarks.json").read_text())
    years = json.loads((library / "manifest.json").read_text())["years"]
    frames = annotations["frames"]
    if set(frames) != set(map(str, years)):
        raise ValueError("Landmarks must cover exactly the manifest's years")
    reference = controls(frames[str(annotations["reference_year"])])
    u, v = np.linspace(0, 1, WIDTH), np.linspace(0, 1, HEIGHT)
    grid = np.stack(np.meshgrid(u, v), axis=-1)
    # Fixed borders keep the panorama seam, poles, and rear view unchanged.
    boundary = np.array([[x, y] for x in np.linspace(.16, .86, 15) for y in [.12, .88]] +
                        [[x, y] for y in np.linspace(.16, .84, 15) for x in [.16, .86]])
    mask = ((grid[..., 0] > .16) & (grid[..., 0] < .86) &
            (grid[..., 1] > .12) & (grid[..., 1] < .88))

    def taper(value, low, high):
        t = np.clip((value - low) / (high - low), 0, 1)
        return t * t * (3 - 2 * t)

    weight = (taper(grid[..., 0], .16, .30) * taper(1 - grid[..., 0], .14, .25) *
              taper(grid[..., 1], .12, .24) * taper(1 - grid[..., 1], .12, .22))
    compiled = {}
    for year in years:
        frame = frames[str(year)]
        digest = hashlib.sha256((library / f"{year}.jpg").read_bytes()).hexdigest()
        if digest != frame["sha256"]:
            raise ValueError(f"{year}: photo changed; review its landmarks first")
        source = controls(frame)
        target = np.array([reference[name] for name in source])
        offsets = np.array(list(source.values())) - target
        fit = RBFInterpolator(np.vstack([target, boundary]) * [2, 1],
                              np.vstack([offsets, np.zeros_like(boundary)]),
                              kernel="thin_plate_spline", smoothing=0.00001)
        delta = np.zeros_like(grid)
        delta[mask] = fit(grid[mask] * [2, 1])
        delta *= weight[..., None]
        if not np.isfinite(delta).all() or np.max(np.abs(delta)) >= RANGE:
            raise ValueError(f"{year}: correction exceeds the encoding range")
        packed = np.rint(delta / RANGE * 32768 + 32768).astype(np.uint16)
        decoded = (packed.astype(float) - 32768) * RANGE / 32768
        # Reject folded or heavily compressed geometry before publishing.
        # Check all four corners of each bilinear texture cell, after encoding.
        mapped = grid + decoded
        dx = np.diff(mapped, axis=1) * (WIDTH - 1)
        dy = np.diff(mapped, axis=0) * (HEIGHT - 1)
        area = min(np.min(h[..., 0] * v[..., 1] - h[..., 1] * v[..., 0])
                   for h in [dx[:-1], dx[1:]] for v in [dy[:, :-1], dy[:, 1:]])
        if area < .25:
            raise ValueError(f"{year}: landmarks would fold or compress the scene")
        if mapped.min() < 0 or mapped.max() > 1:
            raise ValueError(f"{year}: correction leaves the panorama")
        rgba = np.stack([packed[..., 0] >> 8, packed[..., 0] & 255,
                         packed[..., 1] >> 8, packed[..., 1] & 255], axis=-1).astype(np.uint8)
        sample = RegularGridInterpolator((v, u), decoded)
        error = (sample(target[:, ::-1]) - offsets) * [4096, 2048]
        compiled[year] = {"sha256": digest, "offsets": base64.b64encode(rgba.tobytes()).decode()}
        print(f"{year}: control RMS {np.sqrt(np.mean(error ** 2)):.2f}px, "
              f"minimum area scale {area:.2f}")
    result = {"version": 1, "width": WIDTH, "height": HEIGHT, "range": RANGE,
              "reference_year": annotations["reference_year"], "frames": compiled}
    (library / "registration.json").write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("library", type=Path)
    compile_maps(parser.parse_args().library)
