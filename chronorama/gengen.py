"""GENGEN API backend: OpenAI GPT Image 2.5 for panorama generation.

Two things differ from the Vertex/Gemini backend and shape how this is used:

1. It renders a TRUE 2:1 canvas natively (3840x1920), which the Gemini path
   could not -- that API rejected `aspectRatio: "2:1"`, so we rendered 21:9 and
   padded. Here the equirectangular frame is what the model actually composes
   into, so no synthetic padding is needed to reach 2:1.

2. There is no seed. Generation is not reproducible, so the per-year seed
   sweep that tuned the Gemini set is meaningless here. The replacement is
   `outputCount`: ask for several candidates in ONE call and keep the best one
   by measured horizon, which costs a single request instead of N.
"""

import base64
import json
import ssl
import time
import urllib.error
import urllib.request

BASE_URL = "https://gengen.farm/api/gengen/v1/images/generations"
FILES_URL = "https://gengen.farm/api/gengen/v1/files"
BLOB_URL = "https://blob.vercel-storage.com"
DEFAULT_MODEL = "gpt-image-2.5-sunburst"   # tuned for precise reference-image editing
NATIVE_SIZE = "3840x1920"                  # exact 2:1; edges /16; 7.37MP within the 8.29MP cap


def _ctx():
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context(cafile="/etc/ssl/cert.pem")


def _post(body, api_key, timeout=900):
    req = urllib.request.Request(
        BASE_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    last = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            detail = e.read().decode(errors="replace")[:400]
            last = f"HTTP {e.code}: {detail}"
            # A timeout is not proof the request was unprocessed, and a repeat may
            # be charged again -- so only retry codes that are definitely safe.
            if e.code in (429, 500, 502, 503) and attempt < 2:
                wait = 20 * (attempt + 1)
                print(f"    {last.splitlines()[0][:90]} — retrying in {wait}s")
                time.sleep(wait)
                continue
            raise RuntimeError(last) from None
        except (urllib.error.URLError, TimeoutError) as e:
            raise RuntimeError(f"network: {e}") from None
    raise RuntimeError(last)


_upload_cache = {}


def upload(blob, api_key, name="reference.jpg", content_type="image/jpeg"):
    """Upload bytes to GENGEN-managed storage and return their public HTTPS URL.

    As of 2026-09-12 the images endpoint rejects Base64 reference images with a
    400 (it accepted them two days earlier), so references must be hosted. This
    uses GENGEN's own /files route, which authorises a Vercel Blob client upload:
    one call for a token, then a direct PUT of the bytes. Identical bytes are
    uploaded once per process and the URL reused.
    """
    import hashlib
    key = hashlib.sha256(blob).hexdigest()
    if key in _upload_cache:
        return _upload_cache[key]
    pathname = f"gengen/client-uploads/chronorama/{key[:16]}-{name}"
    tok_req = urllib.request.Request(
        FILES_URL,
        data=json.dumps({"type": "blob.generate-client-token",
                         "payload": {"pathname": pathname, "multipart": False,
                                     "clientPayload": json.dumps({"contentType": content_type,
                                                                  "size": len(blob)})}}).encode(),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"})
    with urllib.request.urlopen(tok_req, timeout=60, context=_ctx()) as r:
        token = json.load(r)["clientToken"]
    put = urllib.request.Request(
        f"{BLOB_URL}/{pathname}", data=blob, method="PUT",
        headers={"Authorization": f"Bearer {token}", "x-api-version": "7",
                 "x-content-type": content_type, "Content-Type": content_type})
    with urllib.request.urlopen(put, timeout=300, context=_ctx()) as r:
        url = json.load(r)["url"]
    _upload_cache[key] = url
    return url


def _fetch(url, timeout=300):
    req = urllib.request.Request(url)
    with urllib.request.urlopen(req, timeout=timeout, context=_ctx()) as r:
        return r.read()


def generate(prompt, api_key, ref_image=None, model=DEFAULT_MODEL,
             size=NATIVE_SIZE, quality="high", count=1, extra_refs=()):
    """Return a list of PNG byte blobs (one per candidate).

    `ref_image` is the fixed geometry anchor; `extra_refs` are additional images
    (this API takes up to 16). Chaining to the previous year alone would let each
    year inherit the last one's drift -- the failure that made the series wander
    before -- so the anchor is always sent first and the neighbour second.
    """
    body = {
        "model": model,
        "prompt": prompt,
        "controls": {"size": size, "quality": quality,
                     "outputCount": count, "outputFormat": "png"},
    }
    refs = []
    for i, blob in enumerate(([ref_image] if ref_image is not None else []) + list(extra_refs)):
        refs.append(upload(blob, api_key, name=f"ref{i}.jpg"))
    if refs:
        body["mode"] = "image_edit"
        body["assets"] = {"referenceImages": refs}

    d = _post(body, api_key)
    if d.get("status") != "succeeded":
        raise RuntimeError(f"status={d.get('status')} body={json.dumps(d)[:300]}")
    urls = (d.get("outputs") or {}).get("images") or []
    if not urls:
        raise RuntimeError(f"no images in response: {json.dumps(d)[:300]}")
    return [_fetch(u) for u in urls]
