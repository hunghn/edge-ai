"""Load YAML config: configs/default.yaml deep-merged with an override file, then frozen."""
import copy
import os
from types import MappingProxyType

import yaml

_MISSING = object()


def _deep_merge(base, override):
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _freeze(obj):
    if isinstance(obj, dict):
        return MappingProxyType({k: _freeze(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return tuple(_freeze(v) for v in obj)
    return obj


def _read_yaml(path):
    with open(path, "r") as f:
        data = yaml.safe_load(f)
    return data or {}


def get(cfg, dotted, default=_MISSING):
    """get(cfg, "detect.score_min") -> value. Raises KeyError if missing and no default."""
    node = cfg
    for part in dotted.split("."):
        try:
            node = node[part]
        except (KeyError, TypeError):
            if default is _MISSING:
                raise KeyError(dotted)
            return default
    return node


def _check_range(cfg, key, lo, hi):
    value = get(cfg, key, None)
    if value is None:
        return
    if not (lo <= value <= hi):
        raise ValueError("config {} = {} outside [{}, {}]".format(key, value, lo, hi))


def validate(cfg):
    if get(cfg, "backend") not in ("ort", "trt"):
        raise ValueError("config backend must be 'ort' or 'trt'")
    for key in ("detect.score_min", "detect.nms_iou", "antispoof.p_real_min"):
        _check_range(cfg, key, 0.0, 1.0)
    for key in ("pose_coarse.yaw_max_deg", "pose_coarse.roll_max_deg",
                "pose_fine.yaw_max_deg", "pose_fine.pitch_max_deg", "pose_fine.roll_max_deg"):
        _check_range(cfg, key, 0.0, 90.0)
    _check_range(cfg, "iqa.lum_min", 0, 255)
    _check_range(cfg, "iqa.lum_max", 0, 255)
    if get(cfg, "iqa.lum_min") >= get(cfg, "iqa.lum_max"):
        raise ValueError("config iqa.lum_min must be < iqa.lum_max")
    if get(cfg, "best_frame.min_good") > get(cfg, "best_frame.k_max"):
        raise ValueError("config best_frame.min_good must be <= best_frame.k_max")
    if get(cfg, "match.vote_k") > get(cfg, "match.vote_n"):
        raise ValueError("config match.vote_k must be <= match.vote_n")


def load_config(path=None, default_path=None):
    """Load default.yaml (next to `path` unless given) and deep-merge `path` on top."""
    if default_path is None:
        base_dir = os.path.dirname(os.path.abspath(path)) if path else os.path.join(
            os.path.dirname(__file__), "..", "..", "configs")
        default_path = os.path.join(base_dir, "default.yaml")
    data = _read_yaml(default_path)
    if path and os.path.abspath(path) != os.path.abspath(default_path):
        data = _deep_merge(data, _read_yaml(path))
    validate(data)
    return _freeze(data)
