# chronorama

Generate a time series of 360° equirectangular panoramas of one place with
Gemini (Nano Banana Pro), then scrub through time in a panoramic viewer.
First step toward "Street View for Rome in the 1500s".

## Generate

```bash
python3 generate.py locations/shanghai-bund.json
```

- Auth: `VERTEX_PROJECT=` in `.env` uses Vertex AI with ADC (`gcloud auth
  application-default login`; region via `VERTEX_LOCATION`, default `global`).
  Without it, falls back to an API key (`GEMINI_API_KEY=`/`GOOGLE_API_KEY=`) on the
  generativelanguage endpoint — note that route is geo-blocked from some networks.
- Default model is Nano Banana Pro, `gemini-3-pro-image`, at 4K (~90s per image).

### Model ids on Vertex, the short version

Two things make Gemini 3 image models look unavailable when they are not:

- the id is **`gemini-3-pro-image`**, with no `-preview` suffix, and
- it is served **only from the `global` endpoint** — every regional host
  (`us-central1`, `us-east4`, …) returns 404 for it.

Both mistakes produce the same misleading error: *"was not found or your project
does not have access to it"*. To see what a project can really reach, probe
`:generateContent` per (model, location) pair rather than trusting one 404 —
and do it in Python, not zsh, where `$model:generateContent` is silently eaten
as a zsh modifier and mangles the URL.
- The anchor year (2020 for Shanghai) is generated first from text. Every other
  year is generated outward from it, feeding the nearest finished year's image
  back in as a reference so the viewpoint stays locked while the era changes.
- Output: `output/<id>/<year>.jpg` at 4096x2048 (2:1), raw model output in
  `output/<id>/raw/`, and a `manifest.json` the viewer reads.
- Re-running skips years that already exist; `--force` redoes them,
  `--only 1994` does one year, `--no-ref` disables reference chaining.

## Keeping the geometry identical across years

Set `"reference"` in the location file to a real 360 photo of the place. Every
year is then generated against that same image, instead of against the previous
year — chaining makes each year inherit the last one's drift, which is what
makes a scrub feel unstable. It also makes the years independent, so `--jobs N`
renders them concurrently.

Attaching the reference is necessary but **not sufficient**: the model copies
framing far more reliably than orientation, and will happily render the right
viewpoint facing a different direction. What fixed that was describing the
orientation in words. Set `"framing"` in the location file to spell out:

- what the exact horizontal centre of the frame looks at,
- what sits at the far left and far right edges (in an equirectangular image
  that is one direction split by the wrap, so say so),
- where the mid-ground landmark (here the balustrade) crosses the frame,
- the camera's eye height above the ground.

`build_prompt` wraps that in explicit HORIZON/ELEVATION and ALIGNMENT sections,
including an overlay test — *lay your image on the attached one and the
shoreline, horizon and railing line up*. With that, all 13 Bund years came out
correctly oriented with no post-hoc rotation at all.

The remaining correction is geometric: **horizon** is pinned to the equator in
`_pad_to_2to1` by padding *or cropping* each side independently. A fixed padding
budget is not enough — when the model puts the horizon well off centre the
budget runs out and the correction silently clamps (1865 wanted 584 rows of top
padding but only 385 existed, landing at 0.430 instead of 0.5).

### If a location still comes out rotated

`"auto_yaw": true` enables correlation-based yaw alignment against the
reference, and per-year `"yaw_offset"` (degrees, positive rotates content left)
pins individual years. Both are off by default because the prompt now handles
it, and because that path is genuinely unreliable — two traps if you turn it on:

1. *Edge symmetry cannot validate orientation.* A panorama rotated exactly 180°
   still has matching left and right edges, so it scores well while facing
   completely the wrong way. Do not use it as a success metric.
2. *No image statistic reliably breaks that 180° tie here*, because both banks
   are built up — skyline roughness, brightness, saturation, full-2D
   correlation and even asking a vision model each pick the wrong peak on some
   years. Diagnose by building a labelled contact sheet with a centre line and
   reading all years in one pass.

### Per-library corrections: alignment.json

An `output/<dir>/alignment.json` holds corrections measured against that one
rendered batch and overrides the location file, both when generating and under
`--reprocess`. Either key can be left out.

```json
{ "centre_horizon": true, "yaw_offset": { "1865": -7 } }
```

These live with the library rather than in the location file because every
generation run drifts its own way, so a number measured on one batch is wrong
for every other library rendered from the same location. Regenerating a year
replaces the raw its correction was measured on, which invalidates that entry.
The `__pro` and `__flash31` Bund libraries both set `"centre_horizon": true`,
because some of their years landed with the horizon well off the equator (1865
at 0.398 of image height) and recentring pins all six years to 0.5 so a
cross-fade no longer bobs.

## Making the panoramas true 360

The models never emit exactly 2:1 (the API rejects `aspectRatio: "2:1"`), and
their top and bottom edges are the weakest part of the frame. `equirect.py`
therefore renders the widest ratio on offer (21:9) and then, in `--reprocess`:

1. trims any smeared dark band off the bottom,
2. pads top and bottom to a true 2:1 — never cropping width, which would eat
   into the 360° of yaw coverage and break the wrap,
3. converges both poles by progressively blurring a band that reaches *into*
   the image, so the nadir smears to a point like a real 360 camera instead of
   showing a hard disc,
4. makes the wrap genuinely tileable: these models render a wide photo, not a
   sphere, so the two edges are usually different scenes (measured mean
   difference on the Bund renders: ~70/255). Nudging their colours together
   just paints an obvious band, so instead the right overlap is cross-faded
   onto the left and dropped. Costs ~11° of yaw and leaves a soft dissolve in
   that wedge; tune with `frac` in `_wrap_seam`.

`python3 generate.py <location.json> --reprocess` re-runs all of that on the
saved raws without spending a single API call — use it whenever you tune the
post-processing.

## View

```bash
python3 -m http.server 8747
```

Then open <http://localhost:8747/viewer.html>.
Drag to look around, scroll to zoom, arrow keys or the timeline to move through time.
Press anywhere on the timeline to select a year immediately. Hold and drag to
blend continuously between adjacent images; release to select the nearest year.

The default library is `shanghai-bund__gpt25aligned`, with 52 panoramas from
1865 through 2020. It was copied from the matching folder in `Archive`, with
the original JPGs preserved. The archive contains three variants:

| Folder suffix | Contents |
| --- | --- |
| `__gpt25` | Five-year test set |
| `__gpt25wide` | Complete 52-year wide panorama set |
| `__gpt25aligned` | Complete 52-year set with tower alignment corrections, used by the site |

Archive and the older generated libraries stay local. Only the selected
library's finished JPGs, manifest, and alignment data are tracked in Git.

### Landmark alignment

The selected library also includes `landmarks.json`: reviewed coordinates for
all 52 frames, using the far shoreline, the foreground handrail, and completed
Oriental Pearl, SWFC, and Shanghai towers. The 2020 frame is the reference.
The viewer uses a smooth displacement map for each image before blending it
with its neighbor. The JPGs stay unchanged, and corrections fade to zero at
the panorama seam, poles, and rear view.

To update a frame's measurements, edit its entry in `landmarks.json` and run:

```bash
python3 -m pip install numpy scipy
python3 register.py output/shanghai-bund__gpt25aligned
```

This compiles `registration.json` and rejects maps that fold, strongly compress,
or leave the image. Each frame's annotation and map are tied to its JPG's SHA-256;
after replacing an image, review its measurements and update the annotation's
hash before compiling. The site build rejects stale maps. The compiler's pixel
error measures agreement with annotations, not independent image accuracy.

Append `?alignment=off` to the viewer URL to compare the original geometry.
Some generated buildings change shape or even swap relative positions; Jin Mao
is excluded from the control points for that reason. Moving people, boats,
clouds, and changing architecture still dissolve between frames.

## Deploy

```bash
node build.mjs                  # preview build in dist/
./deploy.sh                     # publish the aligned 52-year library
./deploy.sh shanghai-bund__pro   # or publish another local library
```

Live at <https://chronorama.vercel.app>. `build.mjs` validates the manifest and
reads every listed image before replacing a previous build. It stages
`viewer.html` as `index.html` and copies the published images, manifest, and
compiled alignment maps. Landmark annotations stay in the source repository.
Each published image has a content hash in its filename, so replacing a photo
also changes its URL. This allows long browser caching without showing an old
photo after a deployment.

The root `vercel.json` builds the same static site from GitHub. `deploy.sh`
uses the existing Vercel project link in `../.context/chronorama/.vercel` for a
manual production deployment. On a new checkout, run
`vercel link --cwd ../.context/chronorama --project chronorama` from this
directory after building that directory with
`node build.mjs --out ../.context/chronorama`.

The whole timeline is preloaded before the first frame so scrubbing can blend
between resident images. The aligned set contains about 89 MiB of JPGs.

## Adding a place

Copy `locations/shanghai-bund.json`. The interesting part is `years[].notes`:
concrete, era-specific facts (which buildings exist, what's under construction,
vehicles, clothing, what the far shore looks like). The model's historical
accuracy is only as good as these notes.

Picking the time steps — the heuristic is *equal amounts of visible change per
step*, not equal years: dense steps when the skyline is changing fast (Shanghai
1988–2014: every ~6 years), sparse when it isn't (1865–1905: every ~20 years).
A step earns its place if someone scrubbing past it would notice the jump; if
two neighbors look nearly identical, delete one.
