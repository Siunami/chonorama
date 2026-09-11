#!/usr/bin/env python3
"""chronorama — generate a time series of 360° equirectangular panoramas with Gemini.

Usage:
  python3 generate.py locations/shanghai-bund.json            # generate all missing years
  python3 generate.py locations/shanghai-bund.json --only 1994
  python3 generate.py locations/shanghai-bund.json --force    # regenerate everything

The anchor year is generated first from text alone. Every other year is then
generated outward from the anchor, feeding the nearest already-generated year's
image back in as a reference so the camera position and geography stay locked
while the era changes.

Key: GEMINI_API_KEY or GOOGLE_API_KEY, from the environment or a .env file
next to this script. Output: output/<location-id>/<year>.jpg at 4096x2048,
plus raw/ originals and a manifest.json for viewer.html.
"""

import argparse
import base64
import hashlib
import json
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path


def ssl_context():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")

ROOT = Path(__file__).resolve().parent
API_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
VERTEX_URL = ("https://{host}/v1/projects/{project}/locations/{location}/"
              "publishers/google/models/{model}:generateContent")
# Nano Banana Pro. NOTE: the id is "gemini-3-pro-image" (no -preview suffix) and it
# is served ONLY from the "global" endpoint; every regional host 404s.
DEFAULT_MODEL = "gemini-3-pro-image"
# 2:1 is rejected by the API, so render the widest ratio on offer and pad to 2:1.
ASPECT_RATIO = "21:9"
FINAL_W, FINAL_H = 4096, 2048


def find_gcloud():
    import shutil
    return (shutil.which("gcloud")
            or str(Path.home() / "google-cloud-sdk" / "bin" / "gcloud"))


def load_auth():
    """Prefer Vertex AI via ADC (VERTEX_PROJECT in .env); fall back to an API key.

    Returns a dict: {"mode": "vertex", "project": ...} or {"mode": "apikey", "key": ...}.
    """
    import os
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    project = os.environ.get("VERTEX_PROJECT")
    if project:
        return {"mode": "vertex", "project": project,
                "location": os.environ.get("VERTEX_LOCATION", "global")}
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        sys.exit("No auth. Put VERTEX_PROJECT=... (ADC via gcloud) or GEMINI_API_KEY=... "
                 f"in {env_file} or export it in your shell.")
    return {"mode": "apikey", "key": key}


_token_cache = {"token": None, "at": 0.0}


def vertex_token():
    if _token_cache["token"] and time.time() - _token_cache["at"] < 45 * 60:
        return _token_cache["token"]
    out = subprocess.run(
        [find_gcloud(), "auth", "application-default", "print-access-token"],
        capture_output=True, text=True, check=True,
    )
    _token_cache.update(token=out.stdout.strip(), at=time.time())
    return _token_cache["token"]


def call_gemini(model, auth, prompt, ref_image=None, image_size="4K",
                seed=None, temperature=None):
    parts = []
    if ref_image is not None:
        parts.append({"inlineData": {
            "mimeType": "image/jpeg",
            "data": base64.b64encode(ref_image).decode(),
        }})
    parts.append({"text": prompt})
    image_config = {"aspectRatio": ASPECT_RATIO}
    if image_size and model.startswith("gemini-3"):  # 2.5-flash-image rejects imageSize
        image_config["imageSize"] = image_size
    gen_config = {
        "responseModalities": ["IMAGE"],
        "imageConfig": image_config,
    }
    # Every year shares one seed and a low temperature: same starting noise plus
    # the same reference means the composition holds still across the series and
    # only the era content changes. This is what keeps the framing consistent
    # without rotating or cropping anything afterwards.
    if seed is not None:
        gen_config["seed"] = seed
    if temperature is not None:
        gen_config["temperature"] = temperature
    body = json.dumps({
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": gen_config,
    }).encode()

    if auth["mode"] == "vertex":
        location = auth["location"]
        host = "aiplatform.googleapis.com" if location == "global" else f"{location}-aiplatform.googleapis.com"
        url = VERTEX_URL.format(host=host, project=auth["project"], location=location, model=model)
        headers = {"Content-Type": "application/json",
                   "Authorization": f"Bearer {vertex_token()}",
                   "x-goog-user-project": auth["project"]}
    else:
        url = API_URL.format(model=model)
        headers = {"Content-Type": "application/json", "x-goog-api-key": auth["key"]}
    req = urllib.request.Request(url, data=body, headers=headers)
    last_err = None
    for attempt in range(4):
        try:
            # Image-conditioned 4K renders measured ~640s, so the ceiling has to
            # sit well above that; at 600s every call timed out just short of
            # finishing and silently retried.
            with urllib.request.urlopen(req, timeout=1500, context=ssl_context()) as resp:
                data = json.load(resp)
            for part in data["candidates"][0]["content"]["parts"]:
                blob = part.get("inlineData") or part.get("inline_data")
                if blob:
                    return base64.b64decode(blob["data"])
            raise RuntimeError(f"No image in response: {json.dumps(data)[:2000]}")
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:1000]
            last_err = f"HTTP {e.code}: {detail}"
            if e.code in (429, 500, 503) and attempt < 3:
                wait = 15 * (attempt + 1)
                print(f"    {last_err.splitlines()[0]} — retrying in {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(last_err) from None
        except (urllib.error.URLError, TimeoutError) as e:
            last_err = str(e)
            if attempt < 3:
                time.sleep(10)
                continue
            raise RuntimeError(last_err) from None
    raise RuntimeError(last_err)


from equirect import to_equirect  # trims smear, pads to true 2:1, blends the seam


def build_prompt(loc, step, with_ref, base_ref=False):
    era = step["notes"]
    year = step["year"]
    if base_ref:
        # A single real 360 photo anchors every year, so geometry cannot drift the
        # way it does when each year references the previous one. The layout is
        # ALSO spelled out in words: the model matches framing from the image far
        # more reliably than it matches orientation, and a written compass gives
        # it an unambiguous target instead of something it has to infer.
        framing = loc.get("framing", "")
        head = (
            "The attached image is a real 360 degree equirectangular photograph of "
            f"{loc['scene']}. It is your geometry reference. Reproduce its viewpoint "
            f"exactly, but showing the year {year}.\n\n"
            f"CAMERA AND ORIENTATION (must match the attached image exactly): {framing}\n\n"
            "HORIZON AND ELEVATION -- this is the most common thing to get wrong, so "
            "check it: the image spans a full 180 degrees vertically. Its TOP edge is "
            "the zenith, the sky directly overhead. Its BOTTOM edge is the nadir, the "
            "ground directly beneath the camera's own feet. The horizon lies exactly "
            "halfway between those two, so the top half of the image is sky and the "
            "bottom half is water and ground, in equal measure. Measure it: the number "
            "of pixels of sky above the horizon must equal the number of pixels of "
            "water and ground below it. Do NOT render more ground than sky and do not "
            "place the horizon high in the frame. The camera is level, so the horizon "
            "is dead straight and never tilts. Keep the eye height and the apparent "
            "distance to the far bank identical to the attached image, so the two can "
            "be cross-faded without the horizon moving.\n\n"
            "ALIGNMENT: any landmark that sits at a given horizontal position in the "
            "attached image must sit at that same horizontal position in yours. Do not "
            "rotate, mirror or re-centre the scene. If you were to lay your image on "
            "top of the attached one, the shoreline, the horizon and the railing would "
            "line up.\n\n"
            f"WHAT CHANGES: only history. Do NOT copy the attached photo's time of day, "
            "lighting, weather or sky, and do NOT include any building, vehicle, sign, "
            f"object or person that did not exist in {year} -- the attached photo is "
            "modern and is a geometry reference only.\n\n"
            f"THE YEAR {year}: "
        )
    elif with_ref:
        head = (
            "The attached image is a 360 degree equirectangular panorama of "
            f"{loc['scene']}. Generate the exact same location, same camera position, "
            f"same viewpoint and same projection, but as it appeared in the year {year}. "
            "Keep the river, shoreline, street layout and camera height identical; "
            "change only what history changed. "
        )
    else:
        head = (
            f"360 degree equirectangular panorama of {loc['scene']} in the year {year}, "
            "full spherical 360x180 view, 2:1 aspect ratio. Camera at eye level. "
        )
    tail = (
        f" {era} Era-accurate architecture, vehicles, boats, clothing, signage and "
        f"street furniture for {year}. Photorealistic. Clear late-afternoon daylight "
        "with the sun high and slightly behind the camera -- use this same lighting for "
        "every year so the series can be cross-faded without the light jumping. "
        "Strict equirectangular (spherical) projection covering the full 360 degrees of "
        "yaw and the full 180 degrees of pitch, from the zenith at the top edge to the "
        "nadir at the bottom edge, with the horizon on the exact middle row so that sky "
        "fills the entire top half and water and ground the entire bottom half. "
        "Straight lines near the top and bottom curve outward the way a real 360 camera "
        "renders them. "
        "The far left edge and the far right edge show the same direction and must "
        "join seamlessly with no visible seam, mirroring or duplicated buildings. "
        "No text overlays, no watermark, no borders, no black bands, no tripod."
    )
    return head + tail


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("location", help="path to a location json, e.g. locations/shanghai-bund.json")
    ap.add_argument("--only", type=int, help="generate just this year")
    ap.add_argument("--force", action="store_true", help="regenerate even if the file exists")
    ap.add_argument("--model", default=DEFAULT_MODEL)
    ap.add_argument("--size", default="4K", help="imageSize for the pro model (1K/2K/4K); use '' to omit")
    ap.add_argument("--no-ref", action="store_true", help="text-only prompts, ignore the geometry reference")
    ap.add_argument("--jobs", type=int, default=3, help="how many years to render concurrently")
    ap.add_argument("--seed", type=int, default=20250828,
                    help="shared seed; the same value for every year keeps the framing steady")
    ap.add_argument("--temperature", type=float, default=0.15,
                    help="low values follow the layout contract more literally")
    ap.add_argument("--tag", default="",
                    help="write to output/<id>__<tag>/ instead of output/<id>/ (for benchmarks)")
    ap.add_argument("--reprocess", action="store_true",
                    help="re-run equirect post-processing on saved raws; no API calls")
    args = ap.parse_args()

    loc = json.loads(Path(args.location).read_text())
    out_dir = ROOT / "output" / (loc["id"] + (f"__{args.tag}" if args.tag else ""))
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Alignment corrections are measured against one rendered batch and are wrong
    # for every other batch, so they live with the library rather than in the
    # location file that all of them reprocess from.
    alignment_path = out_dir / "alignment.json"
    overrides = json.loads(alignment_path.read_text()) if alignment_path.exists() else {}
    centre_horizon = overrides.get("centre_horizon", loc.get("centre_horizon", False))

    # Auto yaw-alignment is opt-in ("auto_yaw": true). Once the prompt states the
    # orientation explicitly the model gets it right on its own, and the
    # correlation-based fix is the unreliable step -- the Bund is near enough to
    # symmetric that it lands 180 degrees out on some years. Prompt first, and
    # only fall back to this for a location the prompt cannot pin down.
    align_to = (ROOT / loc["reference"]
                if loc.get("reference") and loc.get("auto_yaw") else None)

    yaw_by_year = {s["year"]: s.get("yaw_offset", 0) for s in loc["years"]}
    yaw_by_year.update({int(y): deg for y, deg in overrides.get("yaw_offset", {}).items()})

    if args.reprocess:
        done = []
        for raw_path in sorted(raw_dir.glob("*.png")):
            year = int(raw_path.stem)
            if args.only and year != args.only:
                continue
            size = to_equirect(raw_path, out_dir / f"{year}.jpg", align_to=align_to,
                               yaw_offset=yaw_by_year.get(year, 0),
                               centre_horizon=centre_horizon)
            extra = ""
            if align_to and getattr(to_equirect, "last_align", None):
                deg, score = to_equirect.last_align
                extra = f"  yaw {deg:5.1f}deg (fit {score:.2f})"
            print(f"[{year}] reprocessed -> {size[0]}x{size[1]}{extra}")
            done.append(year)
        manifest = {
            "id": loc["id"], "name": loc["name"], "anchor_year": loc["anchor_year"],
            "years": sorted(done),
            "notes": {str(s["year"]): s.get("caption", s["notes"].split(".")[0])
                      for s in loc["years"] if s["year"] in done},
        }
        if not args.only:
            (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
        print(f"\nReprocessed {len(done)} image(s).")
        return

    auth = load_auth()

    steps = sorted(loc["years"], key=lambda s: s["year"])
    anchor = loc["anchor_year"]

    # A location can supply a real 360 photo as a fixed geometry anchor. Every
    # year then references that one image, so the camera position and curvature
    # cannot drift -- unlike chaining, where each year inherits the last one's
    # errors. It also makes the years independent, so they can run in parallel.
    base_ref = None
    if loc.get("reference") and not args.no_ref:
        ref_path = ROOT / loc["reference"]
        if not ref_path.exists():
            sys.exit(f"reference image not found: {ref_path}")
        base_ref = ref_path.read_bytes()
        ref_sha = hashlib.sha256(base_ref).hexdigest()
        print(f"geometry reference: {loc['reference']}  "
              f"({len(base_ref)} bytes, sha256 {ref_sha[:16]})")

    generated = {}
    for s in steps:
        p = out_dir / f"{s['year']}.jpg"
        if p.exists():
            generated[s["year"]] = p

    todo = []
    for step in steps:
        year = step["year"]
        if args.only and year != args.only:
            continue
        if (out_dir / f"{year}.jpg").exists() and not args.force:
            print(f"[{year}] exists, skipping (use --force to redo)")
            continue
        todo.append(step)

    def render(step):
        year = step["year"]
        prompt = build_prompt(loc, step, with_ref=base_ref is not None,
                              base_ref=base_ref is not None)
        # Prove every year really is conditioned on the identical file.
        sent_sha = hashlib.sha256(base_ref).hexdigest()[:16] if base_ref else "none"
        print(f"[{year}] sending ref sha256 {sent_sha}, prompt {len(prompt)} chars")
        t0 = time.time()
        # A year may override the shared seed. Generation is deterministic for a
        # given (seed, prompt), so a year that lands badly cannot be improved by
        # re-running it -- only by drawing a different sample.
        img = call_gemini(args.model, auth, prompt, ref_image=base_ref,
                          image_size=args.size or None,
                          seed=step.get("seed", args.seed),
                          temperature=args.temperature)
        raw_path = raw_dir / f"{year}.png"
        raw_path.write_bytes(img)
        final_path = out_dir / f"{year}.jpg"
        to_equirect(raw_path, final_path, align_to=align_to,
                    yaw_offset=yaw_by_year.get(year, 0),
                    centre_horizon=centre_horizon)
        return year, final_path, time.time() - t0

    if todo:
        label = "base-ref" if base_ref else "text-only"
        print(f"generating {len(todo)} year(s) ({label}, model={args.model}, "
              f"{args.jobs} at a time) ...")
        failures = []
        with ThreadPoolExecutor(max_workers=max(1, args.jobs)) as pool:
            futures = {pool.submit(render, s): s["year"] for s in todo}
            for fut in as_completed(futures):
                year = futures[fut]
                try:
                    year, final_path, secs = fut.result()
                except Exception as e:
                    print(f"[{year}] FAILED: {e}")
                    failures.append((year, str(e).splitlines()[0]))
                    continue
                generated[year] = final_path
                kb = final_path.stat().st_size // 1024
                print(f"[{year}] done in {secs:.0f}s -> "
                      f"{final_path.relative_to(ROOT)} ({kb} KB)")

    manifest = {
        "id": loc["id"], "name": loc["name"], "anchor_year": anchor,
        "years": [s["year"] for s in steps if s["year"] in generated],
        "notes": {str(s["year"]): s.get("caption", s["notes"].split(".")[0])
                  for s in steps if s["year"] in generated},
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    # Never claim success while years failed: a swallowed error leaves stale
    # images on disk that look exactly like fresh ones.
    if todo and failures:
        print(f"\n{len(failures)} of {len(todo)} year(s) FAILED — the files on disk "
              f"for these are stale, not regenerated:")
        for year, msg in sorted(failures):
            print(f"  {year}: {msg}")
        sys.exit(1)

    print(f"\nAll {len(todo)} requested year(s) done." if todo else "Nothing to do.")
    print(f"View: python3 -m http.server 8747 --directory {ROOT}  ->  "
          f"http://localhost:8747/viewer.html?loc={loc['id']}")


if __name__ == "__main__":
    main()
