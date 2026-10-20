"""The two local detectors behind check.py (Viktor 9018 F1: NudeNet + one ViT).

Both load from a local directory only, offline, with no pickle formats:
  nudenet/  model.onnx + labels.json + config.json  (ONNX, run by onnxruntime on
            the CPU provider only; no nudenet package install. OpenCV's dnn
            module cannot import this graph: its input axes are dynamic)
  vit/      a transformers image-classification checkpoint as safetensors
            (use_safetensors=True, trust_remote_code=False, local_files_only=True)

Every file is pinned by sha256 and checked BEFORE it is loaded (Viktor 9018 P1,
#5205 O5); the sources and versions are in ATTRIBUTIONS.md. A loader raises if
anything is missing, unpinned, mismatched or in a forbidden format; check.py
then touches nothing and exits 3 (fail-closed without moving files).
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from check import Detector, DetectorError

PICKLE_SUFFIXES = {".bin", ".pt", ".pth", ".ckpt", ".pkl", ".pickle"}

# Byte sha256 of the weight files: nudenet 3.4.2 wheel (nudenet/320n.onnx) and
# Falconsai/nsfw_image_detection @ 96cb0d0342c7afb80cab76ecc58b265fa44da256.
# labels.json and config.json of nudenet are written locally from the pinned
# source, so they are pinned by content (canonical JSON), not by formatting.
NUDENET_PINS = {
    "model.onnx": "c15d8273adad2d0a92f014cc69ab2d6c311a06777a55545f2c4eb46f51911f0f",
}
NUDENET_JSON_PINS = {
    "labels.json": "eb333fdc50b6e3fc0a1612d6a82759f6233e460345ee89a58eecb2a3cf342a57",
    "config.json": "f6f955bce8ac3eab53f94f3c66328b5e07294107fc892ec962efddb037349319",
}
VIT_PINS = {
    "model.safetensors": "97b2ce64ec146884b37f98ee7944ca4891aa72f6827dc0cb10684a1cbecd5830",
    "config.json": "cd8c0a19566f199b5c64da402f1d6a9daf80d094fe6536befb060a2cc59449c2",
    "preprocessor_config.json": "a34861a24e781942424ad790b82bc99348404a2e64ea882de88c40905851698d",
}
CPU_ONLY = ["CPUExecutionProvider"]

# NudeNet labels that flag. Strict on purpose (Lex 9016: bare chest/shoulders on
# a baby is already a problem): every *_EXPOSED label except feet. The label
# names themselves come from labels.json, written from the NudeNet source at the
# pinned version -- they are not hardcoded here.
NUDENET_IGNORE = {"FEET_EXPOSED"}
NUDENET_THRESHOLD = 0.25
VIT_THRESHOLD = 0.20


def _refuse_pickles(d: Path) -> None:
    bad = sorted(p.name for p in d.iterdir() if p.suffix.lower() in PICKLE_SUFFIXES)
    if bad:
        raise DetectorError(f"pickle-format files present in {d.name}: {bad}")


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify_pins(d: Path, pins: dict[str, str]) -> None:
    for name, want in pins.items():
        p = d / name
        if not p.is_file() or p.is_symlink():
            raise DetectorError(f"{d.name}/{name} missing")
        if _sha256_file(p) != want:
            raise DetectorError(f"{d.name}/{name} sha256 mismatch")


def _pinned_bytes(p: Path, want: str) -> bytes:
    """Read once, hash that same buffer, hand that buffer on: no re-read window."""
    if not p.is_file() or p.is_symlink():
        raise DetectorError(f"{p.name} missing")
    data = p.read_bytes()
    if hashlib.sha256(data).hexdigest() != want:
        raise DetectorError(f"{p.name} sha256 mismatch")
    return data


def _pinned_json(p: Path, want: str):
    if not p.is_file() or p.is_symlink():
        raise DetectorError(f"{p.name} missing")
    obj = json.loads(p.read_text(encoding="utf-8"))
    canon = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    if hashlib.sha256(canon).hexdigest() != want:
        raise DetectorError(f"{p.name} content does not match the pin")
    return obj


def _only_pinned_files(d: Path, *pin_sets: dict[str, str]) -> None:
    """Nothing but the pinned files may sit next to a model: an extra index or
    config file could steer the loader to bytes nobody checked."""
    allowed = set().union(*pin_sets)
    extra = sorted(p.name for p in d.iterdir() if p.name not in allowed)
    if extra:
        raise DetectorError(f"unpinned files in {d.name}: {extra}")


def load_nudenet(d: Path) -> Detector:
    _refuse_pickles(d)
    _only_pinned_files(d, NUDENET_PINS, NUDENET_JSON_PINS)
    onnx_bytes = _pinned_bytes(d / "model.onnx", NUDENET_PINS["model.onnx"])
    labels = _pinned_json(d / "labels.json", NUDENET_JSON_PINS["labels.json"])
    cfg = _pinned_json(d / "config.json", NUDENET_JSON_PINS["config.json"])
    size = int(cfg["input_size"])
    flag_ids = [i for i, n in enumerate(labels) if n.endswith("_EXPOSED") and n not in NUDENET_IGNORE]
    if not flag_ids:
        raise DetectorError("no flaggable labels in labels.json")

    import cv2
    import numpy as np
    import onnxruntime as ort  # the inference session only, never .tools or .quantization

    # Explicit CPU provider, no custom-op library (Viktor #5205 O5). The Azure
    # and CoreML providers are available in the wheel; neither may be on the path.
    sess = ort.InferenceSession(onnx_bytes, providers=CPU_ONLY)
    if sess.get_providers() != CPU_ONLY:
        raise DetectorError(f"unexpected providers {sess.get_providers()}")
    input_name = sess.get_inputs()[0].name

    def score(path) -> float:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise DetectorError("unreadable image")
        h, w = img.shape[:2]
        side = max(h, w)
        canvas = np.zeros((side, side, 3), dtype=img.dtype)  # pad bottom/right to square
        canvas[:h, :w] = img
        blob = cv2.dnn.blobFromImage(canvas, 1 / 255.0, (size, size), swapRB=True, crop=False)
        out = sess.run(None, {input_name: blob})[0]  # YOLOv8 head: (1, 4 + classes, anchors)
        out = np.squeeze(out, 0)
        if out.ndim != 2 or out.shape[0] != 4 + len(labels):
            raise DetectorError(f"unexpected output shape {tuple(out.shape)}")
        cls = out[4:, :]
        if not np.isfinite(cls).all():
            raise DetectorError("non-finite scores")
        return float(cls[flag_ids, :].max())

    # The pin prefix is part of the name, so a model change re-screens (check.py ident).
    return Detector(f"nudenet:{NUDENET_PINS['model.onnx'][:8]}", NUDENET_THRESHOLD, score)


def load_vit(d: Path) -> Detector:
    import torch
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModelForImageClassification

    _refuse_pickles(d)
    _only_pinned_files(d, VIT_PINS)
    _verify_pins(d, VIT_PINS)
    proc = AutoImageProcessor.from_pretrained(d, local_files_only=True, trust_remote_code=False)
    model = AutoModelForImageClassification.from_pretrained(
        d, local_files_only=True, trust_remote_code=False, use_safetensors=True)
    model.eval()
    id2label = {int(k): str(v).lower() for k, v in model.config.id2label.items()}
    nsfw = [i for i, n in id2label.items() if n == "nsfw"]
    if len(nsfw) != 1:
        raise DetectorError(f"expected exactly one 'nsfw' label, got {sorted(id2label.values())}")

    def score(path) -> float:
        with Image.open(path) as im:
            inputs = proc(images=im.convert("RGB"), return_tensors="pt")
        with torch.no_grad():
            logits = model(**inputs).logits
        return float(torch.softmax(logits, dim=-1)[0, nsfw[0]])

    return Detector(f"vit-nsfw:{VIT_PINS['model.safetensors'][:8]}", VIT_THRESHOLD, score)
