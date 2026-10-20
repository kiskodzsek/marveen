"""The two local detectors behind check.py (Viktor 9018 F1: NudeNet + one ViT).

Both load from a local directory only, offline, with no pickle formats:
  nudenet/  model.onnx + labels.json + config.json  (ONNX, run by OpenCV's dnn
            module, so no onnxruntime and no nudenet package install)
  vit/      a transformers image-classification checkpoint as safetensors
            (use_safetensors=True, trust_remote_code=False, local_files_only=True)

A loader raises if anything is missing or in a forbidden format; check.py then
touches nothing and exits 3 (fail-closed without moving files).
"""
from __future__ import annotations

import json
from pathlib import Path

from check import Detector, DetectorError

PICKLE_SUFFIXES = {".bin", ".pt", ".pth", ".ckpt", ".pkl", ".pickle"}

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


def load_nudenet_cv(d: Path) -> Detector:
    import cv2
    import numpy as np

    _refuse_pickles(d)
    labels = json.loads((d / "labels.json").read_text(encoding="utf-8"))
    cfg = json.loads((d / "config.json").read_text(encoding="utf-8"))
    size = int(cfg["input_size"])
    flag_ids = [i for i, n in enumerate(labels) if n.endswith("_EXPOSED") and n not in NUDENET_IGNORE]
    if not flag_ids:
        raise DetectorError("no flaggable labels in labels.json")
    net = cv2.dnn.readNetFromONNX(str(d / "model.onnx"))

    def score(path) -> float:
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None:
            raise DetectorError("unreadable image")
        h, w = img.shape[:2]
        side = max(h, w)
        canvas = np.zeros((side, side, 3), dtype=img.dtype)  # pad bottom/right to square
        canvas[:h, :w] = img
        blob = cv2.dnn.blobFromImage(canvas, 1 / 255.0, (size, size), swapRB=True, crop=False)
        net.setInput(blob)
        out = net.forward()  # YOLOv8 head: (1, 4 + classes, anchors)
        out = np.squeeze(out, 0)
        if out.ndim != 2 or out.shape[0] != 4 + len(labels):
            raise DetectorError(f"unexpected output shape {tuple(out.shape)}")
        cls = out[4:, :]
        return float(cls[flag_ids, :].max())

    return Detector("nudenet", NUDENET_THRESHOLD, score)


def load_vit(d: Path) -> Detector:
    import torch
    from PIL import Image
    from transformers import AutoImageProcessor, AutoModelForImageClassification

    _refuse_pickles(d)
    if not (d / "model.safetensors").is_file():
        raise DetectorError("model.safetensors missing")
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

    return Detector("vit-nsfw", VIT_THRESHOLD, score)
