import io
from pathlib import Path

import pytest

from inspector.config import Config
from inspector.perception.detector import SUPPORTED_BACKENDS, OmniParserDetector


def _png(w, h):
    from PIL import Image

    b = io.BytesIO()
    Image.new("RGB", (w, h), (255, 255, 255)).save(b, format="PNG")
    return b.getvalue()


def test_ratio_bboxes_pass_through():
    raw = [{"type": "icon", "bbox": [0.1, 0.1, 0.3, 0.2], "content": "Save", "interactivity": True}]
    els = OmniParserDetector._to_elements(raw)
    assert els[0].bbox == [0.1, 0.1, 0.3, 0.2]
    assert els[0].interactivity is True
    assert els[0].label == "Save"


def test_pixel_bboxes_normalized_to_ratios():
    raw = [{"type": "icon", "bbox": [80, 40, 160, 80], "content": "Save"}]
    els = OmniParserDetector._to_elements(raw, _png(800, 400))
    assert abs(els[0].bbox[0] - 0.1) < 1e-6
    assert abs(els[0].bbox[1] - 0.1) < 1e-6
    assert abs(els[0].bbox[2] - 0.2) < 1e-6
    assert abs(els[0].bbox[3] - 0.2) < 1e-6


def test_malformed_bbox_does_not_crash():
    raw = [{"type": "text", "bbox": [1, 2]}, {"type": "text", "bbox": "oops"}, {"type": "text"}]
    els = OmniParserDetector._to_elements(raw)
    assert len(els) == 3
    for e in els:
        assert len(e.bbox) == 4


def test_unsupported_backend_error_names_the_supported_ones():
    # A user who mis-set INSPECTOR_DETECTOR must learn what IS on offer from the
    # exception alone — the message is the only feedback they get.
    det = OmniParserDetector(Config(detector_backend="local"))
    with pytest.raises(NotImplementedError) as exc:
        det.detect(_png(8, 8))
    message = str(exc.value)
    assert "local" in message
    for backend in SUPPORTED_BACKENDS:
        assert backend in message


@pytest.mark.parametrize("backend", SUPPORTED_BACKENDS)
def test_supported_backends_pass_the_guard(backend):
    # A non-image short-circuits to [] before any network call, so this proves the
    # backend got past the NotImplementedError guard without touching Replicate/HTTP.
    det = OmniParserDetector(Config(detector_backend=backend))
    assert det.detect(b"not a png") == []


def test_env_example_only_advertises_supported_backends():
    # .env.example is the first thing a user copies; a backend documented there but
    # missing from the dispatch is a guaranteed crash on their first run.
    lines = (Path(__file__).resolve().parents[1] / ".env.example").read_text().splitlines()
    idx = next(i for i, line in enumerate(lines) if line.startswith("INSPECTOR_DETECTOR="))
    assert lines[idx].split("=", 1)[1].strip() in SUPPORTED_BACKENDS
    comments = []
    for line in reversed(lines[:idx]):
        if not line.startswith("#"):
            break
        comments.append(line)
    assert comments, "the INSPECTOR_DETECTOR setting should stay documented"
    assert "local" not in " ".join(comments)
