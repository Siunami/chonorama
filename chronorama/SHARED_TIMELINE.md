# Shanghai daytime timelapse pilot

This experiment connects 46 reference panoramas using Seedance 2.0 first/last-frame animation. It adds a separate local viewer; the existing website and image-scrubbing viewer are unchanged.

## Calendar and output

| Period | Calendar gap | Clips | Playback |
| --- | --- | --- | --- |
| 1750–1850 | 25 years | 4 | 16 seconds |
| 1850–1900 | 10 years | 5 | 20 seconds |
| 1900–1990 | 5 years | 18 | 72 seconds |
| 1990–2026 | 2 years | 18 | 72 seconds |

Total: 46 images, 45 clips, 180 seconds. The calendar advances at different rates across these periods. The same schedule can later be reused for other cities; this implementation submits Shanghai daytime jobs only.

Requests use `dreamina-seedance-2-0-260128`, `image_first_last_frame`, four seconds, 4K, adaptive ratio, no audio. The same image file is used at both sides of each shared chapter boundary; SHA-256 hashes are saved for verification.

The reviewed run returned 3840×2160 video at 24fps. Input panoramas are padded with black mattes to preserve their horizontal extent. Removing those mattes produces 3840×1920, without horizontal stretching. Each ordinary clip retains 96 frames; the last retains 97, giving 4321 frames and a 180.041667-second file, including the final endpoint sample. The viewer's clock ends at 180 seconds. Explicit constant-frame-rate encoding prevents cumulative chapter timing drift.

A 2:1 canvas does not guarantee correct spherical geometry. The source stills in this run were 1774×887, not native 4K.

## Set up

Requires Python 3.10+, Pillow, NumPy, FFmpeg/ffprobe, curl, and macOS/Linux (`fcntl` is used for process locking). The panorama viewer loads Three.js from a CDN.

Run these commands from `chronorama/`:

```bash
python3 -m pip install Pillow numpy
python3 shared_timeline.py
```

The second command creates `output/shanghai-shared-day/timeline.json` and lists missing years. It may reuse exact-date stills from the earlier local `output/seedance-history-4k/frames` experiment if present. It does not generate stills or call an API.

Supply a reviewed 2:1 image for every listed year at:

```text
output/shanghai-shared-day/frames/day-YEAR.png
```

The original pilot used 35 newly generated GPT images and 11 exact-date reused candidates. New stills were generated separately with the previous image plus fixed early/modern references. This PR includes the timeline descriptions and video prompts, but not an automated still-generation workflow or the local images, video, credentials, private requests, or signed URLs. New users must supply their own reviewed images. Check geometry, landmark height and historical state before spending on animation.

For generation, set `GENGEN_API_KEY` in the project's ignored `.env`, as used by the existing GenGen backend.

## Generate or resume (paid API calls)

```bash
python3 run_shared_pipeline.py
```

This submits missing clips, with at most three active generation jobs. It requires all 46 images and the timeline before starting. Process locks prevent concurrent local workers from submitting duplicate jobs. Existing tasks are polled rather than resubmitted. Failed or uncertain submissions stop expansion; reconcile a submission marker without a task ID before retrying. A stopped download does not trigger a new generation.

Completed videos download in verified byte ranges, with successful chunks retained for resumption. Raw clips are validated, cropped and encoded for seeking, then joined after all 45 are present. Inputs, upload caches, task IDs, private requests and progress remain under the ignored output directory. Keep that directory when resuming, and do not change inputs midway through a run.

## View existing results without generating

```bash
python3 prepare_shared_preview.py --videos
python3 serve_shared_preview.py
```

Open <http://127.0.0.1:8749/> after assembly, or `/frames.html` to review the image gallery. Only the isolated `preview/` directory is served. HTTP byte ranges support large-video seeking.

The viewer offers panoramic/flat views, scrubbing, year jumps, half speed, rear view, seam softening, and tower-review shortcuts. Seam softening is a display effect; exported footage is unchanged. The full pilot video is approximately 938 MiB and is not checked into Git.

## Validation and known failures

The completed local pilot was checked for 45 requests, 44 shared input boundaries, all 44 decoded video joins, final export timing/dimensions, and browser playback, seeking, replay, flat/360 modes, half speed and seam controls. These technical checks do not establish visual or historical accuracy.

- Pearl Tower 1990–1994 quarter-second samples show progressive construction without the prior extreme height overshoot; details still morph.
- **Shanghai Tower 2012–2014 fails:** it grows too tall and shrinks near the end. This is at **2:32–2:36** in the full film, accessible through the review button.
- The 2014/2016 reference candidates retain unfinished construction details and need historical correction.
- The rear wrap has mismatched architecture, and some anchors differ in exposure/color. Blur cannot repair geometry.

Do not treat this result as approved for expansion to other cities or nighttime. Correct the anchors and failing transition, then review again.

With local outputs present:

```bash
python3 audit_shared_inputs.py
python3 check_shared_joins.py
python3 inspect_shared_video.py
```

The audit checks actual input hashes and export metadata. The other scripts produce contact sheets and frame-difference measurements; pixel differences are review aids, not perceptual pass/fail tests.

Offline integration checks (local loopback server only; no generation):

```bash
python3 -m unittest -v test_shared_pilot
```
