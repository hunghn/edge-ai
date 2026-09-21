"""Our wrappers (OrtBackend) vs goldens produced by the reference repo (make_goldens.py)."""
import os

import cv2
import numpy as np
import pytest

from tests.conftest import FIXTURES, ONNX_DIR

pytestmark = pytest.mark.ort
ort = pytest.importorskip("onnxruntime")

GOLDENS = os.path.join(FIXTURES, "goldens.npz")
NEEDED = ["det_500m", "2d106det", "w600k_mbf", "minifasnet_v2_2.7", "minifasnet_v1se_4.0"]
if not os.path.exists(GOLDENS) or not all(
        os.path.exists(os.path.join(ONNX_DIR, n + ".onnx")) for n in NEEDED):
    pytest.skip("models/onnx or goldens missing; run tools/convert/*", allow_module_level=True)

from edgeface.common.geometry import iou  # noqa: E402
from edgeface.models.arcface import ArcFace  # noqa: E402
from edgeface.models.landmark106 import Landmark106  # noqa: E402
from edgeface.models.minifasnet import MiniFASNet, crop_image  # noqa: E402
from edgeface.models.scrfd import SCRFD  # noqa: E402
from edgeface.pipeline.align import norm_crop  # noqa: E402
from edgeface.runtime import create_backend  # noqa: E402
from tests.parity.make_goldens import test_images as _images  # noqa: E402

NAMES = [n for n, _ in _images()]


@pytest.fixture(scope="module")
def gold():
    return dict(np.load(GOLDENS))


@pytest.fixture(scope="module")
def images():
    return dict(_images())


@pytest.fixture(scope="module")
def models():
    b = lambda stem: create_backend("ort", ONNX_DIR, stem)  # noqa: E731
    return {
        "det": SCRFD(b("det_500m")),
        "lmk": Landmark106(b("2d106det"), mean=0.0, std=1.0),
        "rec": ArcFace(b("w600k_mbf")),
        "fas27": MiniFASNet(b("minifasnet_v2_2.7"), 2.7),
        "fas40": MiniFASNet(b("minifasnet_v1se_4.0"), 4.0),
    }


def test_landmark_mean_std_matches_reference(gold):
    assert float(gold["lmk_mean"]) == 0.0 and float(gold["lmk_std"]) == 1.0


@pytest.mark.parametrize("name", NAMES)
def test_scrfd(gold, images, models, name):
    faces = models["det"].detect(images[name], score_min=float(gold["det_thresh"]))
    ref = gold[name + "/det"]
    assert len(faces) == len(ref)
    for f, r in zip(faces, ref):
        assert iou(f.bbox, r[:4]) > 0.99
        assert abs(f.score - r[4]) < 1e-4
    np.testing.assert_allclose(faces[0].kps, gold[name + "/kps"][0], atol=0.05)


@pytest.mark.parametrize("name", NAMES)
def test_landmark106(gold, images, models, name):
    pts = models["lmk"].predict(images[name], gold[name + "/det"][0, :4])
    np.testing.assert_allclose(pts, gold[name + "/lmk106"], atol=0.05)


@pytest.mark.parametrize("name", NAMES)
def test_align_and_arcface(gold, images, models, name):
    aligned = norm_crop(images[name], gold[name + "/kps"][0])
    diff = np.abs(aligned.astype(int) - gold[name + "/aligned"].astype(int))
    assert diff.max() <= 2  # skimage vs numpy Umeyama: sub-pixel interpolation noise only
    ours = models["rec"].embed_raw(gold[name + "/aligned"])
    ref = gold[name + "/emb_raw"]
    cos = float(ours.dot(ref) / (np.linalg.norm(ours) * np.linalg.norm(ref)))
    assert cos > 0.999
    emb = models["rec"].embed(aligned)
    assert abs(float(np.linalg.norm(emb)) - 1.0) < 1e-5


@pytest.mark.parametrize("name", NAMES)
def test_minifasnet(gold, images, models, name):
    bbox = gold[name + "/fas_bbox_xywh"]
    for key, model in (("fas_2.7", models["fas27"]), ("fas_4.0", models["fas40"])):
        np.testing.assert_allclose(model.predict(images[name], bbox), gold[name + "/" + key], atol=1e-4)


@pytest.mark.parametrize("name", NAMES)
def test_crop_image_matches_reference(gold, images, name):
    for box, ref in zip(gold[name + "/crop_boxes"], gold[name + "/crops"]):
        crop = crop_image(images[name], box[:4], float(box[4]), 80, 80)
        np.testing.assert_array_equal(crop, ref)
