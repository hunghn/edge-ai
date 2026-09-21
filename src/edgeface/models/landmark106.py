"""2d106det landmark wrapper.

Ported from ims_id_server face_backend/insightface/model_zoo/landmark.py::Landmark.get:
crop = bbox side x1.5 scaled to 192x192 around the bbox center, output in [-1, 1]
mapped back through the inverse crop transform.
"""
import cv2
import numpy as np

from edgeface.common.geometry import apply_affine, center_scale_matrix
from edgeface.common.imgproc import to_blob

NUM_POINTS = 106


class Landmark106(object):
    def __init__(self, backend, mean, std, input_size=192, bbox_expand=1.5):
        # mean/std come from models/manifest.yaml (checked once against the ONNX graph)
        self.backend = backend
        self.mean = float(mean)
        self.std = float(std)
        self.input_size = int(input_size)
        self.bbox_expand = float(bbox_expand)
        self._input_name = backend.inputs[0].name

    def crop_matrix(self, bbox):
        w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        center = ((bbox[2] + bbox[0]) / 2.0, (bbox[3] + bbox[1]) / 2.0)
        scale = self.input_size / (max(w, h) * self.bbox_expand)
        return center_scale_matrix(center, self.input_size, scale)

    def preprocess(self, img, bbox):
        m = self.crop_matrix(bbox)
        crop = cv2.warpAffine(img, m, (self.input_size, self.input_size), borderValue=0.0)
        return to_blob(crop, self.mean, self.std, swap_rb=True), m

    def postprocess(self, output, m):
        pred = np.asarray(output, dtype=np.float32).reshape((-1, 2))[-NUM_POINTS:].copy()
        pred += 1.0
        pred *= self.input_size // 2
        return apply_affine(pred, cv2.invertAffineTransform(m))

    def predict(self, img, bbox):
        """img: HxWx3 uint8 BGR; bbox: [x1, y1, x2, y2]. Returns (106, 2) float32 in img coords."""
        blob, m = self.preprocess(img, bbox)
        out = list(self.backend.infer({self._input_name: blob}).values())[0]
        return self.postprocess(out, m)
