import os

import pytest

from edgeface import config


def test_default_and_overrides_merge(repo_root):
    cfg = config.load_config(os.path.join(repo_root, "configs", "nano.yaml"))
    assert config.get(cfg, "backend") == "trt"
    assert config.get(cfg, "models.dir") == "models/engines"
    assert config.get(cfg, "models.detector") == "det_500m"      # kept from default
    assert config.get(cfg, "detect.score_min") == 0.6
    assert config.get(cfg, "match.threshold") == 0.80              # D-01, set 2026-10-08
    assert config.get(cfg, "match.margin_top1_top2") is None      # D-02: no margin check


def test_frozen(repo_root):
    cfg = config.load_config(os.path.join(repo_root, "configs", "dev.yaml"))
    with pytest.raises(TypeError):
        cfg["backend"] = "trt"


def test_validation_rejects_bad_range(tmp_path, repo_root):
    bad = tmp_path / "bad.yaml"
    bad.write_text("detect:\n  score_min: 1.5\n")
    with pytest.raises(ValueError):
        config.load_config(str(bad), default_path=os.path.join(repo_root, "configs", "default.yaml"))


@pytest.mark.parametrize("body", [
    "pose_fine:\n  method: euler\n",
    "pose_fine:\n  ud_min: 0.9\n  ud_max: 0.85\n",
    "pose_fine:\n  rl_min: 0.0\n",
    "pose_fine:\n  eye_closed_max: null\n",
])
def test_validation_rejects_a_bad_s5_ratio_gate(tmp_path, repo_root, body):
    bad = tmp_path / "bad.yaml"
    bad.write_text(body)
    with pytest.raises(ValueError):
        config.load_config(str(bad), default_path=os.path.join(repo_root, "configs", "default.yaml"))


def test_pnp_method_does_not_need_the_ratio_thresholds(tmp_path, repo_root):
    good = tmp_path / "pnp.yaml"
    good.write_text("pose_fine:\n  method: pnp\n  eye_closed_max: null\n")
    cfg = config.load_config(str(good),
                             default_path=os.path.join(repo_root, "configs", "default.yaml"))
    assert config.get(cfg, "pose_fine.method") == "pnp"


def test_with_overrides_returns_a_new_validated_frozen_config(repo_root):
    cfg = config.load_config(os.path.join(repo_root, "configs", "dev.yaml"))
    changed = config.with_overrides(cfg, {"match.threshold": 0.9,
                                          "match.margin_top1_top2": None})
    assert changed["match"]["threshold"] == 0.9 and cfg["match"]["threshold"] == 0.80
    with pytest.raises(TypeError):
        changed["match"]["threshold"] = 0.5
    with pytest.raises(ValueError):
        config.with_overrides(cfg, {"match.vote_k": 9})      # vote_k > vote_n


@pytest.mark.parametrize("body", [
    "admin_settings:\n  match.threshold: {min: 0.9, max: 0.5, step: 0.05}\n",
    "admin_settings:\n  match.threshold: {min: 0.5, max: 0.9, step: 0}\n",
    "admin_settings:\n  match.nonsense: {min: 0.5, max: 0.9, step: 0.05}\n",
])
def test_validation_rejects_bad_admin_settings(tmp_path, repo_root, body):
    bad = tmp_path / "bad.yaml"
    bad.write_text(body)
    with pytest.raises(ValueError):
        config.load_config(str(bad), default_path=os.path.join(repo_root, "configs", "default.yaml"))


def test_admin_value_check_follows_the_range(repo_root):
    cfg = config.load_config(os.path.join(repo_root, "configs", "dev.yaml"))
    config.check_admin_value(cfg, "match.threshold", 0.5)
    config.check_admin_value(cfg, "match.margin_top1_top2", None)     # nullable
    for key, value in (("match.threshold", 0.45), ("match.threshold", None),
                       ("detect.score_min", 0.5)):
        with pytest.raises(ValueError):
            config.check_admin_value(cfg, key, value)


@pytest.mark.parametrize("body", [
    "kiosk:\n  preview_format: png\n",
    "kiosk:\n  preview_jpeg_quality: 0\n",
    "kiosk:\n  preview_width: 4\n",
])
def test_validation_rejects_a_bad_preview_setting(tmp_path, repo_root, body):
    bad = tmp_path / "bad.yaml"
    bad.write_text(body)
    with pytest.raises(ValueError):
        config.load_config(str(bad), default_path=os.path.join(repo_root, "configs", "default.yaml"))
