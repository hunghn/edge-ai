import os

import pytest

from edgeface import config


def test_default_and_overrides_merge(repo_root):
    cfg = config.load_config(os.path.join(repo_root, "configs", "nano.yaml"))
    assert config.get(cfg, "backend") == "trt"
    assert config.get(cfg, "models.dir") == "models/engines"
    assert config.get(cfg, "models.detector") == "det_500m"      # kept from default
    assert config.get(cfg, "detect.score_min") == 0.6
    assert config.get(cfg, "match.threshold") is None             # §6 TBD stays null


def test_frozen(repo_root):
    cfg = config.load_config(os.path.join(repo_root, "configs", "dev.yaml"))
    with pytest.raises(TypeError):
        cfg["backend"] = "trt"


def test_validation_rejects_bad_range(tmp_path, repo_root):
    bad = tmp_path / "bad.yaml"
    bad.write_text("detect:\n  score_min: 1.5\n")
    with pytest.raises(ValueError):
        config.load_config(str(bad), default_path=os.path.join(repo_root, "configs", "default.yaml"))
