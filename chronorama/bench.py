#!/usr/bin/env python3
"""Head-to-head benchmark of image models on the same years, prompt and seeds.

Both models see identical inputs, so differences are the model's. Reports the
objective things we already care about -- does the horizon land on the equator,
does the Bund frontage stay inside the layout contract's edge bands -- plus
wall-clock time.

    python3 bench.py locations/shanghai-bund.json
"""

import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
YEARS = [1865, 1937, 1975, 1992, 2008, 2020]
MODELS = {"pro": "gemini-3-pro-image", "flash31": "gemini-3.1-flash-image"}


def load(p, size=(512, 256)):
    for attempt in range(4):
        try:
            return np.asarray(Image.open(p).convert("L").resize(size)).astype(np.float32)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2)


def horizon(p):
    a = load(p)
    g = np.abs(np.diff(a.mean(axis=1)))
    return (38 + int(np.argmax(g[38:217]))) / 256.0


def edge_bands(p):
    """How much structure sits in the outer 12% vs the middle -- the layout
    contract wants buildings at the edges and open water in the middle."""
    a = load(p)
    upper = a[int(256 * 0.20):int(256 * 0.47)]
    col = upper.std(axis=0)
    edge = np.concatenate([col[:int(512 * 0.12)], col[-int(512 * 0.12):]]).mean()
    mid = col[int(512 * 0.30):int(512 * 0.70)].mean()
    return edge, mid


def run(loc_path, tag, model, year):
    t = time.time()
    r = subprocess.run(
        ["python3", "generate.py", str(loc_path), "--only", str(year),
         "--force", "--tag", tag, "--model", model],
        cwd=ROOT, capture_output=True, text=True)
    ok = "FAILED" not in r.stdout
    m = re.search(r"done in (\d+)s", r.stdout)
    return year, ok, int(m.group(1)) if m else round(time.time() - t)


def main():
    loc_path = Path(sys.argv[1])
    loc = json.loads(loc_path.read_text())
    rows = {}
    for tag, model in MODELS.items():
        print(f"\n=== {model} (tag {tag}) ===", flush=True)
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(lambda y: run(loc_path, tag, model, y), YEARS))
        out = ROOT / "output" / f"{loc['id']}__{tag}"
        stats = []
        for year, ok, secs in sorted(results):
            p = out / f"{year}.jpg"
            if not ok or not p.exists():
                print(f"  {year}: FAILED", flush=True)
                continue
            hz = horizon(p)
            edge, mid = edge_bands(p)
            stats.append((year, hz, edge, mid, secs))
            print(f"  {year}: horizon {hz:.3f}  edge/mid structure {edge:5.1f}/{mid:5.1f}  {secs}s",
                  flush=True)
        rows[tag] = stats

    print("\n=== SUMMARY ===")
    print(f"{'model':<24} {'horizon dev':>12} {'edge:mid':>10} {'median s':>9}")
    for tag, stats in rows.items():
        if not stats:
            print(f"{MODELS[tag]:<24}  no successful runs")
            continue
        dev = np.mean([abs(h - 0.5) for _, h, _, _, _ in stats])
        ratio = np.mean([e / max(m, 1e-6) for _, _, e, m, _ in stats])
        med = int(np.median([s for *_, s in stats]))
        print(f"{MODELS[tag]:<24} {dev:>12.4f} {ratio:>10.2f} {med:>9}")
    print("\nhorizon dev: mean |horizon-0.5|, lower is better")
    print("edge:mid   : structure at the edges vs the middle; higher means the")
    print("             frontage stayed at the edges and the river stayed open")


if __name__ == "__main__":
    main()
