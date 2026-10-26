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


def thaw(obj):
    """A frozen config back into plain dicts and lists, for merging."""
    if isinstance(obj, (dict, MappingProxyType)):
        return {k: thaw(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [thaw(v) for v in obj]
    return obj


def with_overrides(cfg, overrides):
    """A new frozen config with {"match.threshold": 0.8, ...} applied and validated."""
    data = thaw(cfg)
    for dotted, value in (overrides or {}).items():
        node = data
        parts = dotted.split(".")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    validate(data)
    return _freeze(data)


def admin_range(cfg, key):
    """{'min', 'max', 'step', 'nullable'} for a key the admin screen may edit, or None."""
    spec = (get(cfg, "admin_settings", None) or {}).get(key)
    if not spec:
        return None
    return {"min": float(spec["min"]), "max": float(spec["max"]),
            "step": float(spec["step"]), "nullable": bool(spec.get("nullable", False))}


def check_admin_value(cfg, key, value):
    """Raise ValueError unless `value` is allowed for `key` by admin_settings."""
    spec = admin_range(cfg, key)
    if spec is None:
        raise ValueError("{} cannot be changed from the admin screen".format(key))
    if value is None:
        if not spec["nullable"]:
            raise ValueError("{} cannot be empty".format(key))
        return
    if not spec["min"] - 1e-9 <= float(value) <= spec["max"] + 1e-9:
        raise ValueError("{} = {} outside [{}, {}]".format(
            key, value, spec["min"], spec["max"]))


def _check_admin_settings(cfg):
    for key, spec in (get(cfg, "admin_settings", None) or {}).items():
        try:
            get(cfg, key)
        except KeyError:
            raise ValueError("config admin_settings names an unknown key: {}".format(key))
        if spec.get("min") is None or spec.get("max") is None or not spec.get("step"):
            raise ValueError("config admin_settings.{} needs min, max and step".format(key))
        if not spec["min"] < spec["max"] or spec["step"] <= 0:
            raise ValueError("config admin_settings.{}: min < max and step > 0".format(key))


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


def _check_enabled_outcomes(cfg):
    """decision.enabled_outcomes may only name outcomes the Decision enum can express.

    The spec defers the full outcome list to §6.3 (D-04). Enabling a name the code does
    not know would silently do nothing, so it is refused here instead.
    """
    from edgeface.types import Decision

    known = set(member.value for member in Decision)
    configured = set(get(cfg, "decision.enabled_outcomes", ()) or ())
    unknown = configured - known
    if unknown:
        raise ValueError(
            "decision.enabled_outcomes has values the Decision enum does not define: {}. "
            "Add them to edgeface.types.Decision once D-04 is decided.".format(
                sorted(unknown)))


def _check_pose_fine(cfg):
    method = get(cfg, "pose_fine.method", "ratio")
    if method not in ("ratio", "pnp"):
        raise ValueError("config pose_fine.method must be 'ratio' or 'pnp'")
    if method != "ratio":
        return
    for low, high in (("ud_min", "ud_max"), ("rl_min", "rl_max")):
        low_v = get(cfg, "pose_fine." + low, None)
        high_v = get(cfg, "pose_fine." + high, None)
        if low_v is None or high_v is None or not 0.0 < low_v < high_v:
            raise ValueError("config pose_fine.{} must be > 0 and < pose_fine.{}".format(
                low, high))
    for key in ("eye_closed_max", "mouth_open_min"):
        value = get(cfg, "pose_fine." + key, None)
        if value is None or value <= 0.0:
            raise ValueError("config pose_fine.{} must be > 0".format(key))


def validate(cfg):
    if get(cfg, "backend") not in ("ort", "trt"):
        raise ValueError("config backend must be 'ort' or 'trt'")
    for key in ("detect.score_min", "detect.nms_iou", "antispoof.p_real_min"):
        _check_range(cfg, key, 0.0, 1.0)
    for key in ("pose_coarse.yaw_max_deg", "pose_coarse.roll_max_deg",
                "pose_fine.yaw_max_deg", "pose_fine.pitch_max_deg", "pose_fine.roll_max_deg"):
        _check_range(cfg, key, 0.0, 90.0)
    _check_pose_fine(cfg)
    _check_range(cfg, "iqa.lum_min", 0, 255)
    _check_range(cfg, "iqa.lum_max", 0, 255)
    if get(cfg, "iqa.lum_min") >= get(cfg, "iqa.lum_max"):
        raise ValueError("config iqa.lum_min must be < iqa.lum_max")
    if get(cfg, "best_frame.min_good") > get(cfg, "best_frame.k_max"):
        raise ValueError("config best_frame.min_good must be <= best_frame.k_max")
    if get(cfg, "match.vote_k") > get(cfg, "match.vote_n"):
        raise ValueError("config match.vote_k must be <= match.vote_n")
    if get(cfg, "match.template_agg", "max") not in ("max", "mean"):
        raise ValueError("config match.template_agg must be 'max' or 'mean'")
    _check_range(cfg, "match.threshold", -1.0, 1.0)
    _check_range(cfg, "match.margin_top1_top2", 0.0, 2.0)
    _check_enabled_outcomes(cfg)
    _check_admin_settings(cfg)
    if get(cfg, "kiosk.preview_format", "raw") not in ("raw", "jpeg"):     # publisher.FORMATS
        raise ValueError("config kiosk.preview_format must be 'raw' or 'jpeg'")
    _check_range(cfg, "kiosk.preview_jpeg_quality", 1, 100)
    width = get(cfg, "kiosk.preview_width", None)
    if width is not None and int(width) < 16:
        raise ValueError("config kiosk.preview_width must be null or >= 16")


PACKAGED_CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "..", "..", "configs")


def default_config_path(path=None):
    """default.yaml next to `path`, falling back to the project's configs/default.yaml.

    An override file may live anywhere (a scratch directory, /etc), and it still has to
    merge on top of the project defaults rather than stand alone.
    """
    if path:
        sibling = os.path.join(os.path.dirname(os.path.abspath(path)), "default.yaml")
        if os.path.exists(sibling):
            return sibling
    return os.path.abspath(os.path.join(PACKAGED_CONFIG_DIR, "default.yaml"))


def load_config(path=None, default_path=None):
    """Load default.yaml (next to `path` unless given) and deep-merge `path` on top."""
    if default_path is None:
        default_path = default_config_path(path)
    data = _read_yaml(default_path)
    if path and os.path.abspath(path) != os.path.abspath(default_path):
        data = _deep_merge(data, _read_yaml(path))
    validate(data)
    return _freeze(data)
