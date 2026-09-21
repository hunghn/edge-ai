"""Load the five model wrappers for whichever backend the config selects.

On the device this also checks provenance: an engine built from a different ONNX than
the manifest describes is a silent accuracy bug, so it is refused at start-up.
"""
import json
import os

import yaml

from edgeface.common.log import get_logger
from edgeface.models.arcface import ArcFace
from edgeface.models.landmark106 import Landmark106
from edgeface.models.minifasnet import MiniFASNet
from edgeface.models.scrfd import SCRFD
from edgeface.runtime import create_backend

LOG = get_logger("models")

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
DEFAULT_MANIFEST = os.path.join(REPO, "models", "manifest.yaml")


def load_manifest(path=None):
    with open(path or DEFAULT_MANIFEST) as f:
        return yaml.safe_load(f) or {}


def _resolve_dir(cfg):
    model_dir = cfg["models"]["dir"]
    return model_dir if os.path.isabs(model_dir) else os.path.join(REPO, model_dir)


def check_engine_provenance(model_dir, stem, manifest_entry):
    """Compare an engine's sidecar with the manifest. Returns a warning string or None."""
    sidecar = os.path.join(model_dir, stem + ".engine.json")
    if not os.path.exists(sidecar):
        return "{}: engine has no sidecar; rebuild with scripts/build_engines.sh".format(stem)
    with open(sidecar) as f:
        meta = json.load(f)
    expected = (manifest_entry or {}).get("sha256")
    if expected and meta.get("onnx_sha256") != expected:
        return "{}: engine was built from a different ONNX than models/manifest.yaml".format(stem)
    return None


def load_models(cfg, manifest_path=None, strict=True):
    """{"detector", "landmark", "recognizer", "antispoof_v2", "antispoof_v1se"} + metadata.

    The returned dict also carries "recognizer_sha256", which every embedding is stored
    with so that templates from different models never get compared (see storage).
    """
    backend_kind = cfg["backend"]
    model_dir = _resolve_dir(cfg)
    manifest = load_manifest(manifest_path)
    stems = {key: cfg["models"][key] for key in
             ("detector", "landmark", "recognizer", "antispoof_v2", "antispoof_v1se")}

    if backend_kind == "trt":
        for key, stem in sorted(stems.items()):
            problem = check_engine_provenance(model_dir, stem, manifest.get(stem))
            if problem:
                if strict:
                    raise RuntimeError(problem)
                LOG.warning("%s", problem)

    backends = {key: create_backend(backend_kind, model_dir, stem)
                for key, stem in stems.items()}
    landmark_pre = (manifest.get(stems["landmark"], {}) or {}).get("preprocess", {}) or {}
    scales = {crop["model"]: crop["scale"] for crop in cfg["antispoof"]["crops"]}

    models = {
        "detector": SCRFD(backends["detector"],
                          input_size=tuple(cfg["detect"]["input_size"]),
                          nms_iou=cfg["detect"]["nms_iou"]),
        "landmark": Landmark106(backends["landmark"],
                                mean=landmark_pre.get("mean", 0.0),
                                std=landmark_pre.get("std", 1.0),
                                input_size=cfg["landmark"]["input_size"],
                                bbox_expand=cfg["landmark"]["bbox_expand"]),
        "recognizer": ArcFace(backends["recognizer"],
                              input_size=cfg.get("align", {}).get("image_size", 112)),
        "recognizer_sha256": (manifest.get(stems["recognizer"], {}) or {}).get("sha256"),
        "backend": backend_kind,
    }
    for key in ("antispoof_v2", "antispoof_v1se"):
        models[key] = MiniFASNet(backends[key], scale=scales[key],
                                 input_size=tuple(cfg["antispoof"]["input_size"]))
    LOG.info("loaded 5 models from %s using the %s backend", model_dir, backend_kind)
    return models


def close_models(models):
    for value in models.values():
        backend = getattr(value, "backend", None)
        if backend is not None and hasattr(backend, "close"):
            backend.close()
