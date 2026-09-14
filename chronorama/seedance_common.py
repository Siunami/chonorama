"""Shared Seedance request helper and panorama constraints."""
import json
import urllib.request
import gengen

ENDPOINT = "https://gengen.farm/api/gengen/v1/contents/generations/tasks"

def request(url, key, body=None):
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120, context=gengen._ctx()) as response:
        return json.load(response)

BASE = 'A full 360x180 equirectangular panoramic texture, complete 2:1 canvas. One fixed tripod viewpoint. ZERO camera translation, rotation, pan, tilt, zoom, roll, reframing or perspective changes. Keep the horizon, river banks, eye height, foreground and all completed landmarks at identical coordinates. The left/right boundary is a periodic wrap; every intermediate frame must join seamlessly, including clouds, building facades, ground and illumination. Animate ONLY the small historical difference between the supplied endpoints. Buildings grow upward from their anchored foundations, with cranes and incremental assembly, not elastic morphing. Never exceed the final landmark silhouette in height or width, never grow too large and shrink back, never slide sideways. Preserve completed portions. No cuts, text or montage. Ease construction motion gently into and out of the exact supplied endpoints; no unrelated dissolves. Daylight remains constant. '
MATTE = 'The supplied canvas has black top and bottom letterbox mattes around a complete 2:1 panorama. Preserve the exact mattes throughout; do not fill or remove them or zoom to fill the canvas. Keep the ENTIRE horizontal width. All panorama coordinates refer to the inner scene occupying y5.556% to94.444%. '


from contextlib import contextmanager
import fcntl

@contextmanager
def generation_lock(path):
    """Prevent concurrent local workers from submitting duplicate paid jobs."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit("Another generation worker is active; wait for it to finish.")
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)
