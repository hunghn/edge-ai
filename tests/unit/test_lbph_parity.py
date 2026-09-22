# -*- coding: utf-8 -*-
"""Our numpy LBPH against cv2.face, the implementation it replaces (D-27).

cv2.face only exists where opencv-contrib is installed (a dev machine), so these tests
skip on the Nano — which is the whole point: the Nano cannot have it, and that is why
the algorithm was reimplemented.
"""
import numpy as np
import pytest

from baselines.haar_lbph.lbph import LBPHRecognizer, chi_square, lbp_image, spatial_histogram

cv2 = pytest.importorskip("cv2")
if not hasattr(cv2, "face"):
    pytest.skip("opencv-contrib (cv2.face) not installed", allow_module_level=True)


def faces(count=6, size=64, seed=0):
    """Synthetic 'faces': a blob pattern per identity, plus per-sample noise."""
    rng = np.random.RandomState(seed)
    images, labels = [], []
    for label in range(count // 2):
        base = rng.randint(40, 210, size=(size, size)).astype(np.uint8)
        for _ in range(2):
            noisy = np.clip(base.astype(np.int16)
                            + rng.randint(-12, 13, size=(size, size)), 0, 255)
            images.append(noisy.astype(np.uint8))
            labels.append(label)
    return images, labels


def opencv_model(images, labels, radius=1, neighbors=8, grid=8):
    model = cv2.face.LBPHFaceRecognizer_create(radius=radius, neighbors=neighbors,
                                               grid_x=grid, grid_y=grid)
    model.train(images, np.asarray(labels, dtype=np.int32))
    return model


def test_histograms_match_opencv():
    images, labels = faces()
    theirs = opencv_model(images, labels).getHistograms()
    ours = LBPHRecognizer()
    for image, reference in zip(images, theirs):
        mine = ours.describe(image)
        assert mine.shape[0] == np.asarray(reference).size
        # float32 division rounds differently in C++ and numpy; 1e-6 is far below the
        # smallest bin value that could change a prediction.
        np.testing.assert_allclose(mine, np.asarray(reference).ravel(), rtol=1e-6, atol=1e-7)


@pytest.mark.parametrize("radius,neighbors,grid", [(1, 8, 8), (2, 8, 4), (1, 8, 6)])
def test_histograms_match_for_other_parameters(radius, neighbors, grid):
    images, labels = faces(seed=3)
    theirs = opencv_model(images, labels, radius, neighbors, grid).getHistograms()
    ours = LBPHRecognizer(radius=radius, neighbors=neighbors, grid_x=grid, grid_y=grid)
    np.testing.assert_allclose(ours.describe(images[0]),
                               np.asarray(theirs[0]).ravel(), rtol=1e-6, atol=1e-7)


def test_predictions_match_opencv():
    images, labels = faces(count=8, seed=1)
    probes, _ = faces(count=8, seed=1)          # same identities, regenerated
    theirs = opencv_model(images, labels)
    ours = LBPHRecognizer().train(images, labels)
    for probe in probes:
        their_label, their_distance = theirs.predict(probe)
        our_label, our_distance = ours.predict(probe)
        assert our_label == their_label
        assert our_distance == pytest.approx(their_distance, rel=1e-6, abs=1e-6)


def test_chi_square_matches_opencv_compare():
    rng = np.random.RandomState(0)
    a = rng.randint(0, 50, size=256).astype(np.float32)
    b = rng.randint(0, 50, size=256).astype(np.float32)
    theirs = cv2.compareHist(a, b, cv2.HISTCMP_CHISQR)
    assert chi_square(a, b) == pytest.approx(theirs, rel=1e-6)
    # Asymmetric: swapping the arguments gives a different number, in both libraries.
    assert chi_square(b, a) == pytest.approx(cv2.compareHist(b, a, cv2.HISTCMP_CHISQR),
                                             rel=1e-6)


def test_lbp_image_shape_and_border():
    gray = np.arange(64, dtype=np.uint8).reshape(8, 8)
    codes = lbp_image(gray, radius=1)
    assert codes.shape == (6, 6)                # border has no full neighbourhood
    assert codes.min() >= 0 and codes.max() <= 255
    assert spatial_histogram(codes, grid_x=2, grid_y=2).shape == (4 * 256,)


def test_model_round_trip(tmp_path):
    images, labels = faces()
    model = LBPHRecognizer().train(images, labels)
    path = str(tmp_path / "lbph.npz")
    model.save(path)
    loaded = LBPHRecognizer.load(path)
    assert loaded.predict(images[0]) == model.predict(images[0])
    assert loaded.labels.tolist() == model.labels.tolist()


def test_predict_all_returns_every_distance():
    images, labels = faces(count=6)
    model = LBPHRecognizer().train(images, labels)
    all_labels, distances = model.predict_all(images[0])
    assert len(all_labels) == len(images) and len(distances) == len(images)
    assert distances[0] == pytest.approx(0.0, abs=1e-6)   # identical to itself


def test_empty_model_is_not_a_crash():
    assert LBPHRecognizer().predict(np.zeros((64, 64), np.uint8)) == (-1, float("inf"))
