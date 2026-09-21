"""FP16 TensorRT engines vs the ONNX goldens produced on a dev machine (M2-T11).

Runs only on the Nano: needs tensorrt + pycuda and models/engines/*.engine.
Tolerances are the ones proposed in docs/plans/M2_tensorrt_nano.md §6.
"""
import os

import numpy as np
import pytest

from tests.conftest import FIXTURES, REPO

pytestmark = pytest.mark.nano
pytest.importorskip("tensorrt")
pytest.importorskip("pycuda")

ENGINE_DIR = os.path.join(REPO, "models", "engines")
GOLDENS = os.path.join(FIXTURES, "goldens.npz")
NEEDED = ["det_500m", "2d106det", "w600k_mbf", "minifasnet_v2_2.7", "minifasnet_v1se_4.0"]
if not os.path.exists(GOLDENS) or not all(
        os.path.exists(os.path.join(ENGINE_DIR, n + ".engine")) for n in NEEDED):
    pytest.skip("engines or goldens missing; run scripts/build_engines.sh",
                allow_module_level=True)

from edgeface.common.geometry import iou  # noqa: E402
from edgeface.models.arcface import ArcFace  # noqa: E402
from edgeface.models.landmark106 import Landmark106  # noqa: E402
from edgeface.models.minifasnet import MiniFASNet  # noqa: E402
from edgeface.models.scrfd import SCRFD  # noqa: E402
from edgeface.runtime import create_backend  # noqa: E402
from tests.parity.make_goldens import test_images as _images  # noqa: E402

NAMES = [n for n, _ in _images()]

IOU_MIN = 0.95          # SCRFD boxes
KPS_ATOL_PX = 2.0       # SCRFD keypoints
LMK_ATOL_PX = 1.0       # 2d106det
EMB_COS_MIN = 0.99      # ArcFace
SPOOF_ATOL = 0.02       # MiniFASNet softmax


@pytest.fixture(scope="module")
def gold():
    return dict(np.load(GOLDENS))


@pytest.fixture(scope="module")
def images():
    return dict(_images())


@pytest.fixture(scope="module")
def models():
    make = lambda stem: create_backend("trt", ENGINE_DIR, stem)  # noqa: E731
    return {
        "det": SCRFD(make("det_500m")),
        "lmk": Landmark106(make("2d106det"), mean=0.0, std=1.0),
        "rec": ArcFace(make("w600k_mbf")),
        "fas27": MiniFASNet(make("minifasnet_v2_2.7"), 2.7),
        "fas40": MiniFASNet(make("minifasnet_v1se_4.0"), 4.0),
    }


@pytest.mark.parametrize("name", NAMES)
def test_scrfd_fp16(gold, images, models, name):
    ref = gold[name + "/det"]
    faces = models["det"].detect(images[name], score_min=float(gold["det_thresh"]))
    assert len(faces) == len(ref), "FP16 engine found a different number of faces"
    for face, row in zip(faces, ref):
        assert iou(face.bbox, row[:4]) >= IOU_MIN
        assert abs(face.score - row[4]) < 0.05
    np.testing.assert_allclose(faces[0].kps, gold[name + "/kps"][0], atol=KPS_ATOL_PX)


@pytest.mark.parametrize("name", NAMES)
def test_landmark_fp16(gold, images, models, name):
    pts = models["lmk"].predict(images[name], gold[name + "/det"][0, :4])
    np.testing.assert_allclose(pts, gold[name + "/lmk106"], atol=LMK_ATOL_PX)


@pytest.mark.parametrize("name", NAMES)
def test_arcface_fp16(gold, models, name):
    ours = models["rec"].embed(gold[name + "/aligned"])
    ref = gold[name + "/emb_raw"]
    ref = ref / np.linalg.norm(ref)
    assert float(ours.dot(ref)) >= EMB_COS_MIN


@pytest.mark.parametrize("name", NAMES)
def test_minifasnet_fp16(gold, images, models, name):
    bbox = gold[name + "/fas_bbox_xywh"]
    for key, model in (("fas_2.7", models["fas27"]), ("fas_4.0", models["fas40"])):
        probs = model.predict(images[name], bbox)
        ref = gold[name + "/" + key]
        assert int(np.argmax(probs)) == int(np.argmax(ref)), "FP16 flipped the class"
        np.testing.assert_allclose(probs, ref, atol=SPOOF_ATOL)
