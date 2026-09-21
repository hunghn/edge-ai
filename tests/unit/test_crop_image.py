import numpy as np

from edgeface.models.minifasnet import _new_box, crop_image


def test_box_inside_image_scales_about_center():
    # 100x100 box at (400, 300) in 1280x720, scale 2 -> 200x200 about center (450, 350)
    assert _new_box(1280, 720, [400, 300, 100, 100], 2.0) == (350, 250, 550, 450)


def test_scale_capped_by_image_size():
    x1, y1, x2, y2 = _new_box(200, 100, [50, 25, 100, 50], 4.0)
    assert (x2 - x1) <= 199 and (y2 - y1) <= 99


def test_box_shifted_inside_at_borders():
    assert _new_box(640, 480, [-20, -10, 80, 80], 2.7)[:2] == (0, 0)
    x1, y1, x2, y2 = _new_box(640, 480, [600, 440, 60, 60], 2.7)
    assert x2 == 639 and y2 == 479 and x1 >= 0 and y1 >= 0


def test_crop_output_is_raw_bgr_80x80():
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    img[..., 0] = 200
    crop = crop_image(img, [300, 200, 50, 60], 2.7, 80, 80)
    assert crop.shape == (80, 80, 3) and crop.dtype == np.uint8
    assert int(crop[40, 40, 0]) == 200 and int(crop[40, 40, 2]) == 0
