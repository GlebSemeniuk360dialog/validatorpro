"""
dma_writer.py — real WRITE calls to DMA / 360dialog (media upload + template create).

Separate module so the write surface is small and auditable. Two functions:

  upload_media(dma_token, file_bytes, filename, mime) -> {"url", "unique_id"}
      POST https://dma.360dialog.io/api/v2/media  (multipart 'document', Bearer)

  create_waba_template(waba_key, template_body) -> {"status_code", "ok", "json"}
      POST https://waba-v2.360dialog.io/v1/configs/templates  (D360-API-KEY)

These actually write. Callers must gate them behind explicit user confirmation.
"""

import logging
import requests

logger = logging.getLogger(__name__)

HTTP_TIMEOUT = 60
_MEDIA_URL = "https://dma.360dialog.io/api/v2/media"
_TEMPLATE_URL = "https://waba-v2.360dialog.io/v1/configs/templates"


def upload_media(dma_token: str, file_bytes: bytes, filename: str, mime: str = "image/jpeg") -> dict:
    """Upload a file to DMA media storage. Returns {'url', 'unique_id'} or raises."""
    files = {"document": (filename, file_bytes, mime)}
    r = requests.post(
        _MEDIA_URL,
        headers={"Authorization": f"Bearer {dma_token.strip()}"},
        files=files,
        timeout=HTTP_TIMEOUT,
    )
    if r.status_code not in (200, 201):
        raise RuntimeError(f"media upload failed ({r.status_code}): {r.text[:300]}")
    data = r.json()
    url = data.get("url") or data.get("document")
    if not url:
        raise RuntimeError(f"media upload returned no url: {data}")
    logger.info("DMA media upload ok: %s", url)
    return {"url": url, "unique_id": data.get("unique_id", "")}


def create_waba_template(waba_key: str, template_body: dict) -> dict:
    """
    Create a WhatsApp template via the 360dialog WABA API. The template is
    submitted to Meta for approval. Returns {status_code, ok, json}.
    """
    r = requests.post(
        _TEMPLATE_URL,
        headers={"D360-API-KEY": waba_key, "Content-Type": "application/json"},
        json=template_body,
        timeout=HTTP_TIMEOUT,
    )
    ok = r.status_code in (200, 201)
    try:
        body = r.json()
    except Exception:
        body = {"raw": r.text[:500]}
    logger.info("WABA template create -> %s (%s)", r.status_code, "ok" if ok else "fail")
    return {"status_code": r.status_code, "ok": ok, "json": body}
