"""All five engines must fit in the engine process budget (2.0-2.6 GB) — M2-T12."""
import os

import pytest

from tests.conftest import REPO

pytestmark = pytest.mark.nano
pytest.importorskip("tensorrt")
pytest.importorskip("pycuda")

ENGINE_DIR = os.path.join(REPO, "models", "engines")
STEMS = ["det_500m", "2d106det", "w600k_mbf", "minifasnet_v2_2.7", "minifasnet_v1se_4.0"]
BUDGET_MB = 2600

if not all(os.path.exists(os.path.join(ENGINE_DIR, s + ".engine")) for s in STEMS):
    pytest.skip("engines missing", allow_module_level=True)

from edgeface.runtime import create_backend  # noqa: E402


def rss_mb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmHWM:"):
                return int(line.split()[1]) / 1024.0
    return float("nan")


def test_all_engines_fit_in_budget():
    backends = [create_backend("trt", ENGINE_DIR, stem) for stem in STEMS]
    peak = rss_mb()
    print("\npeak RSS with {} engines loaded: {:.0f} MB".format(len(backends), peak))
    for b in backends:
        b.close()
    assert peak < BUDGET_MB, "peak RSS {:.0f} MB exceeds budget {} MB".format(peak, BUDGET_MB)
