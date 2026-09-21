"""SCRFD face detector (det_500m) wrapper.

Ported from ims_id_server face_backend/src_recognition/scrfd.py (SCRFD.forward/detect,
distance2bbox, distance2kps). Differences: backend-agnostic, outputs identified by shape
instead of position, returns Detection namedtuples.
"""
import numpy as np

from edgeface.common.geometry import nms
from edgeface.common.imgproc import letterbox, to_blob
from edgeface.types import Detection

MEAN = 127.5
STD = 128.0


def distance2bbox(points, distance):
    x1 = points[:, 0] - distance[:, 0]
    y1 = points[:, 1] - distance[:, 1]
    x2 = points[:, 0] + distance[:, 2]
    y2 = points[:, 1] + distance[:, 3]
    return np.stack([x1, y1, x2, y2], axis=-1)


def distance2kps(points, distance):
    preds = []
    for i in range(0, distance.shape[1], 2):
        preds.append(points[:, 0] + distance[:, i])
        preds.append(points[:, 1] + distance[:, i + 1])
    return np.stack(preds, axis=-1)


def anchor_centers(height, width, stride, num_anchors):
    centers = np.stack(np.mgrid[:height, :width][::-1], axis=-1).astype(np.float32)
    centers = (centers * stride).reshape((-1, 2))
    if num_anchors > 1:
        centers = np.stack([centers] * num_anchors, axis=1).reshape((-1, 2))
    return centers


def group_outputs(outputs, input_size, strides, num_anchors):
    """Map raw outputs to {stride: (scores (N,), bbox (N,4), kps (N,10) or None)}.

    Outputs are matched by anchor count (which fixes the stride) and last dim (1/4/10),
    so the result does not depend on the backend's binding order. A leading batch dim
    of 1 is dropped.
    """
    in_w, in_h = input_size
    by_count = {}
    for stride in strides:
        n = (in_h // stride) * (in_w // stride) * num_anchors
        by_count[n] = stride
    grouped = {s: [None, None, None] for s in strides}
    for arr in outputs:
        a = np.asarray(arr)
        if a.ndim == 3 and a.shape[0] == 1:
            a = a[0]
        if a.ndim != 2 or a.shape[0] not in by_count:
            raise ValueError("unexpected SCRFD output shape {}".format(np.shape(arr)))
        slot = {1: 0, 4: 1, 10: 2}.get(a.shape[1])
        if slot is None:
            raise ValueError("unexpected SCRFD output shape {}".format(np.shape(arr)))
        grouped[by_count[a.shape[0]]][slot] = a
    result = {}
    for stride, (scores, bbox, kps) in grouped.items():
        if scores is None or bbox is None:
            raise ValueError("missing SCRFD outputs for stride {}".format(stride))
        result[stride] = (scores.reshape(-1), bbox, kps)
    return result


class SCRFD(object):
    def __init__(self, backend, input_size=(640, 640), nms_iou=0.4,
                 strides=(8, 16, 32), num_anchors=2):
        self.backend = backend
        self.input_size = tuple(input_size)  # (width, height)
        self.nms_iou = nms_iou
        self.strides = tuple(strides)
        self.num_anchors = num_anchors
        self._input_name = backend.inputs[0].name
        in_w, in_h = self.input_size
        self._centers = {
            s: anchor_centers(in_h // s, in_w // s, s, num_anchors) for s in self.strides
        }

    def preprocess(self, img):
        det_img, scale = letterbox(img, self.input_size)
        return to_blob(det_img, MEAN, STD, swap_rb=True), scale

    def postprocess(self, outputs, scale, score_min):
        grouped = group_outputs(outputs, self.input_size, self.strides, self.num_anchors)
        scores_all, boxes_all, kps_all = [], [], []
        has_kps = True
        for stride in self.strides:
            scores, bbox_pred, kps_pred = grouped[stride]
            centers = self._centers[stride]
            pos = np.where(scores >= score_min)[0]
            scores_all.append(scores[pos])
            boxes_all.append(distance2bbox(centers[pos], bbox_pred[pos] * stride))
            if kps_pred is None:
                has_kps = False
            else:
                kps = distance2kps(centers[pos], kps_pred[pos] * stride)
                kps_all.append(kps.reshape((-1, 5, 2)))
        scores = np.concatenate(scores_all).astype(np.float32)
        if scores.size == 0:
            return []
        boxes = (np.concatenate(boxes_all) / scale).astype(np.float32)
        kpss = (np.concatenate(kps_all) / scale).astype(np.float32) if has_kps else None
        keep = nms(boxes, scores, self.nms_iou)
        return [
            Detection(boxes[i], float(scores[i]), kpss[i] if kpss is not None else None)
            for i in keep
        ]

    def detect(self, img, score_min):
        """img: HxWx3 uint8 BGR (any size). Returns [Detection] sorted by score, in img coords."""
        blob, scale = self.preprocess(img)
        outputs = self.backend.infer({self._input_name: blob})
        return self.postprocess(list(outputs.values()), scale, score_min)
