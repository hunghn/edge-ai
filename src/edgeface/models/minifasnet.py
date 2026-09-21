"""MiniFASNet anti-spoofing wrapper (one model; S4 fuses two of them).

Crop ported from ims_id_server anti_spoofing/src/generate_patches.py::CropImage;
pre-processing from anti_spoofing/src/data_io/functional.py::to_tensor, which does
NOT divide by 255: input is raw 0-255 float CHW BGR.
"""
import cv2
import numpy as np

from edgeface.common.imgproc import softmax, to_blob

REAL_CLASS = 1  # 0 = print, 1 = real, 2 = replay


def _new_box(src_w, src_h, bbox_xywh, scale):
    x, y, box_w, box_h = [float(v) for v in bbox_xywh]
    scale = min((src_h - 1) / box_h, min((src_w - 1) / box_w, scale))
    new_w = box_w * scale
    new_h = box_h * scale
    cx, cy = box_w / 2 + x, box_h / 2 + y
    x1, y1 = cx - new_w / 2, cy - new_h / 2
    x2, y2 = cx + new_w / 2, cy + new_h / 2
    if x1 < 0:
        x2 -= x1
        x1 = 0
    if y1 < 0:
        y2 -= y1
        y1 = 0
    if x2 > src_w - 1:
        x1 -= x2 - src_w + 1
        x2 = src_w - 1
    if y2 > src_h - 1:
        y1 -= y2 - src_h + 1
        y2 = src_h - 1
    return int(x1), int(y1), int(x2), int(y2)


def crop_image(img, bbox_xywh, scale, out_w, out_h):
    """bbox_xywh is [x, y, w, h] (NOT x1, y1, x2, y2)."""
    src_h, src_w = img.shape[:2]
    x1, y1, x2, y2 = _new_box(src_w, src_h, bbox_xywh, scale)
    return cv2.resize(img[y1:y2 + 1, x1:x2 + 1], (out_w, out_h))


class MiniFASNet(object):
    def __init__(self, backend, scale, input_size=(80, 80)):
        self.backend = backend
        self.scale = float(scale)
        self.input_size = tuple(input_size)  # (width, height)
        self._input_name = backend.inputs[0].name

    def preprocess(self, img, bbox_xywh):
        crop = crop_image(img, bbox_xywh, self.scale, self.input_size[0], self.input_size[1])
        return to_blob(crop, 0.0, 1.0, swap_rb=False)

    def predict(self, img, bbox_xywh):
        """img: full HxWx3 uint8 BGR frame. Returns (3,) float32 softmax probabilities."""
        blob = self.preprocess(img, bbox_xywh)
        logits = list(self.backend.infer({self._input_name: blob}).values())[0]
        return softmax(np.asarray(logits).reshape(1, -1))[0]
