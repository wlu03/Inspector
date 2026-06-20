from __future__ import annotations

import ast
import base64
import io
import json
import re
from typing import Protocol

from ..config import Config
from ..models import Element


class Detector(Protocol):
    def detect(self, image_bytes: bytes) -> list[Element]: ...


class OmniParserDetector:
    """Element detector backed by OmniParser V2.

    Backends (config.detector_backend):
      - "replicate": calls the pinned microsoft/omniparser-v2 (needs REPLICATE_API_TOKEN)
      - "http":      POSTs to a self-hosted OmniParser FastAPI server

    Returns elements; the Set-of-Mark index == the element's position in the list.

    Replicate output is `{img: <uri>, elements: <string>}` where `elements` is a
    serialized list of element dicts (confirmed via the model schema; the exact
    string serialization is parsed defensively in `_parse_elements`). [VERIFY: once
    Replicate credit is available, confirm the elements string format + whether
    bbox is ratio (0..1) or pixels — see _to_elements.]
    """

    def __init__(self, config: Config):
        self.config = config

    def detect(self, image_bytes: bytes) -> list[Element]:
        backend = self.config.detector_backend
        if backend == "replicate":
            raw = self._detect_replicate(image_bytes)
        elif backend == "http":
            raw = self._detect_http(image_bytes)
        else:
            raise NotImplementedError(
                f"detector backend {backend!r} not implemented (see docs/11 Part D)"
            )
        return self._to_elements(raw, image_bytes)

    def _detect_replicate(self, image_bytes: bytes) -> list[dict]:
        import replicate  # lazy

        out = replicate.run(
            self.config.omniparser_ref,
            input={
                "image": io.BytesIO(image_bytes),
                "imgsz": 640,
                "box_threshold": 0.05,
                "iou_threshold": 0.1,
            },
            use_file_output=False,
        )
        if isinstance(out, dict):
            return self._parse_elements(out.get("elements"))
        if isinstance(out, (list, tuple)):
            return list(out)
        return []

    def _detect_http(self, image_bytes: bytes) -> list[dict]:
        import httpx  # lazy

        b64 = base64.b64encode(image_bytes).decode()
        resp = httpx.post(
            f"{self.config.omniparser_endpoint}/parse",
            json={"base64_image": b64},
            timeout=60,
        )
        resp.raise_for_status()
        return resp.json().get("parsed_content_list", [])

    @staticmethod
    def _parse_elements(elements) -> list[dict]:
        """Parse OmniParser's `elements` output into a list of dicts, defensively.

        Handles: already-a-list; a JSON string; or a newline-delimited string of
        "icon N: {python-dict}" lines (OmniParser's common text serialization).
        """
        if elements is None:
            return []
        if isinstance(elements, list):
            return [e for e in elements if isinstance(e, dict)]
        text = str(elements)

        # whole-string JSON
        try:
            data = json.loads(text)
            if isinstance(data, list):
                return [e for e in data if isinstance(e, dict)]
            if isinstance(data, dict):
                return [data]
        except Exception:
            pass

        # line-by-line: optional "label N:" prefix, then a dict literal
        items: list[dict] = []
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            m = re.match(r"^\s*\w+\s*\d+\s*:\s*(\{.*\})\s*$", line)
            payload = m.group(1) if m else line
            for parser in (json.loads, ast.literal_eval):
                try:
                    obj = parser(payload)
                    if isinstance(obj, dict):
                        items.append(obj)
                        break
                except Exception:
                    continue
        return items

    @staticmethod
    def _to_elements(raw: list[dict], image_bytes: bytes | None = None) -> list[Element]:
        # 1) parse each bbox safely (pad/truncate to 4, tolerate non-numeric)
        parsed: list[tuple[dict, list[float]]] = []
        for el in raw:
            try:
                bbox = [float(v) for v in (el.get("bbox") or [])][:4]
            except (TypeError, ValueError):
                bbox = []
            bbox = (bbox + [0.0, 0.0, 0.0, 0.0])[:4]
            parsed.append((el, bbox))

        # 2) decide the coordinate unit ONCE for the whole detection (not per element).
        #    If any coord exceeds 1.5 the model emitted pixels — normalize to ratios.
        all_max = max((max(b) for _, b in parsed), default=0.0)
        w = h = None
        if all_max > 1.5 and image_bytes:
            try:
                import io as _io

                from PIL import Image

                w, h = Image.open(_io.BytesIO(image_bytes)).size
            except Exception:
                w = h = None

        elements: list[Element] = []
        for i, (el, bbox) in enumerate(parsed):
            if w and h:
                bbox = [bbox[0] / w, bbox[1] / h, bbox[2] / w, bbox[3] / h]
            el_type = str(el.get("type") or "")
            elements.append(
                Element(
                    id=i,
                    label=str(el.get("content") or ""),
                    role=el_type,
                    bbox=bbox,
                    interactivity=bool(el.get("interactivity", el_type == "icon")),
                    source=str(el.get("source") or ""),
                )
            )
        return elements
