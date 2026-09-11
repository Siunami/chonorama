#!/usr/bin/env python3
"""Generate any missing years, then reseed the ones whose horizon lands off-centre.

Generation is deterministic for a given (seed, prompt), so a year that frames
badly can never be improved by re-running it -- only by drawing a different
sample. This generates what is missing, measures every year, and sweeps
alternate seeds for the outliers, recording the winning seed in the location
file so the result reproduces.

    python3 tune.py locations/shanghai-bund.json
"""

import json
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
TARGET, TOL = 0.50, 0.04          # horizon must land within +/- TOL of centre
GOOD = 0.025                      # close enough to stop sweeping
SEEDS = [404, 77, 1234, 9091]


def horizon(path):
    for attempt in range(4):
        try:
            a = np.asarray(Image.open(path).convert("L").resize((512, 256))).astype(np.float32)
            break
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2)
    g = np.abs(np.diff(a.mean(axis=1)))
    return (38 + int(np.argmax(g[38:217]))) / 256.0


def run(loc_path, year, seed=None, force=False):
    cmd = ["python3", "generate.py", str(loc_path), "--only", str(year)]
    if force:
        cmd.append("--force")
    if seed is not None:
        cmd += ["--seed", str(seed)]
    r = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True)
    return "FAILED" not in r.stdout, r.stdout


def main():
    loc_path = Path(sys.argv[1])
    loc = json.loads(loc_path.read_text())
    out = ROOT / "output" / loc["id"]

    missing = [s["year"] for s in loc["years"] if not (out / f"{s['year']}.jpg").exists()]
    if missing:
        print(f"generating {len(missing)} missing year(s): {missing}", flush=True)
        with ThreadPoolExecutor(max_workers=4) as pool:
            for ok, log in pool.map(lambda y: run(loc_path, y), missing):
                line = [l for l in log.splitlines() if "done in" in l or "FAILED" in l]
                if line:
                    print("  " + line[-1][:110], flush=True)

    scores = {}
    for s in loc["years"]:
        p = out / f"{s['year']}.jpg"
        if p.exists():
            scores[s["year"]] = horizon(p)
    bad = [y for y, v in scores.items() if abs(v - TARGET) > TOL]
    print(f"\n{len(scores)} year(s) measured; {len(bad)} outside +/-{TOL}: {bad}", flush=True)

    chosen = {}

    def sweep(y):
        best = (abs(scores[y] - TARGET), None)
        for seed in SEEDS:
            ok, _ = run(loc_path, y, seed=seed, force=True)
            if not ok:
                print(f"  {y} seed {seed}: FAILED", flush=True)
                continue
            v = horizon(out / f"{y}.jpg")
            print(f"  {y} seed {seed}: {v:.3f}", flush=True)
            if abs(v - TARGET) < best[0]:
                best = (abs(v - TARGET), seed)
            if abs(v - TARGET) <= GOOD:
                break
        # Leave the winning sample on disk, not whatever the last attempt was.
        if best[1] is not None and abs(horizon(out / f"{y}.jpg") - TARGET) > best[0] + 1e-6:
            run(loc_path, y, seed=best[1], force=True)
        return y, best[1]

    if bad:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for y, seed in pool.map(sweep, bad):
                if seed is not None:
                    chosen[y] = seed

    if chosen:
        loc = json.loads(loc_path.read_text())
        for s in loc["years"]:
            if s["year"] in chosen:
                s["seed"] = chosen[s["year"]]
        loc_path.write_text(json.dumps(loc, indent=2, ensure_ascii=False))
        print(f"\nrecorded seeds: {chosen}", flush=True)

    final = {s["year"]: horizon(out / f"{s['year']}.jpg")
             for s in loc["years"] if (out / f"{s['year']}.jpg").exists()}
    v = list(final.values())
    still = {y: round(x, 3) for y, x in final.items() if abs(x - TARGET) > TOL}
    print(f"\nFINAL {len(v)} years | horizon std {np.std(v):.4f} "
          f"range {min(v):.3f}-{max(v):.3f}")
    print(f"{sum(1 for x in v if abs(x-TARGET)<=TOL)} of {len(v)} within +/-{TOL}")
    print("still out:", still or "NONE")


if __name__ == "__main__":
    main()
