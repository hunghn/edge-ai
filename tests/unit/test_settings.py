# -*- coding: utf-8 -*-
"""Match settings saved from the kiosk admin screen, on top of the YAML config."""
import json
import os

import pytest

from edgeface import config as cfg_mod
from edgeface.storage import db, outbox
from edgeface.storage import settings

T0 = 1700000000.0


@pytest.fixture
def cfg(repo_root):
    return cfg_mod.load_config(os.path.join(repo_root, "configs", "dev.yaml"))


@pytest.fixture
def conn(tmp_path):
    c = db.open_db(str(tmp_path / "edge.db"))
    yield c
    c.close()


def events(conn):
    rows = conn.execute("SELECT type, payload FROM outbox ORDER BY created_at").fetchall()
    return [(row["type"], json.loads(row["payload"])) for row in rows]


def test_nothing_saved_means_the_yaml_values(conn, cfg):
    assert settings.overrides(conn, cfg) == {}
    assert settings.effective(cfg, conn) is cfg
    info = settings.describe(conn, cfg, "match.threshold")
    assert info["value"] == 0.80 and info["saved"] is False


def test_a_saved_value_overrides_the_yaml_for_the_engine(conn, cfg):
    settings.set_value(conn, cfg, "match.threshold", 0.85, operator_id=3, now=T0)
    effective = settings.effective(cfg, conn)
    assert effective["match"]["threshold"] == 0.85
    assert cfg["match"]["threshold"] == 0.80               # the loaded config is untouched
    info = settings.describe(conn, cfg, "match.threshold")
    assert info["saved"] and info["operator_id"] == 3 and info["updated_at"] == T0


def test_an_empty_margin_is_saved_as_no_check(conn, cfg):
    settings.set_value(conn, cfg, "match.margin_top1_top2", 0.10, now=T0)
    assert settings.effective(cfg, conn)["match"]["margin_top1_top2"] == 0.10
    settings.set_value(conn, cfg, "match.margin_top1_top2", None, now=T0 + 1)
    assert settings.overrides(conn, cfg) == {"match.margin_top1_top2": None}
    assert settings.effective(cfg, conn)["match"]["margin_top1_top2"] is None


@pytest.mark.parametrize("key,value", [
    ("match.threshold", 0.40), ("match.threshold", 0.99), ("match.threshold", None),
    ("match.margin_top1_top2", 0.50), ("match.vote_k", 2),
])
def test_values_outside_admin_settings_are_refused(conn, cfg, key, value):
    with pytest.raises(ValueError):
        settings.set_value(conn, cfg, key, value, now=T0)
    assert settings.overrides(conn, cfg) == {} and events(conn) == []


def test_every_change_goes_to_the_outbox_with_who_made_it(conn, cfg):
    settings.set_value(conn, cfg, "match.threshold", 0.90, operator_id=7, now=T0)
    settings.reset(conn, cfg, "match.threshold", operator_id=7, now=T0 + 5)
    (first_type, first), (second_type, second) = events(conn)
    assert first_type == second_type == "settings.changed"
    assert (first["key"], first["old"], first["new"], first["operator_id"]) == \
        ("match.threshold", 0.80, 0.90, 7)
    assert second["reset"] is True and second["new"] == 0.80
    assert "settings.changed" in outbox.TYPES


def test_reset_goes_back_to_the_yaml(conn, cfg):
    settings.set_value(conn, cfg, "match.threshold", 0.90, now=T0)
    assert settings.reset(conn, cfg, "match.threshold", now=T0) == 0.80
    assert settings.overrides(conn, cfg) == {}
    assert settings.describe(conn, cfg, "match.threshold")["operator_id"] is None


def test_a_value_the_config_no_longer_allows_is_ignored_not_fatal(conn, cfg):
    """The YAML range was narrowed after a value was saved: the engine must still run."""
    settings.set_value(conn, cfg, "match.threshold", 0.95, now=T0)
    data = cfg_mod.thaw(cfg)
    data["admin_settings"]["match.threshold"]["max"] = 0.90
    narrowed = cfg_mod.with_overrides(data, {})
    assert settings.effective(narrowed, conn)["match"]["threshold"] == 0.80
