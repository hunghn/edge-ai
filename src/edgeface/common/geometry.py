"""Box and point geometry. Pure numpy."""
import numpy as np


def xyxy_to_xywh(bbox):
    x1, y1, x2, y2 = [float(v) for v in bbox[:4]]
    return [x1, y1, x2 - x1, y2 - y1]


def xywh_to_xyxy(bbox):
    x, y, w, h = [float(v) for v in bbox[:4]]
    return [x, y, x + w, y + h]


def bbox_center(bbox):
    return (float(bbox[0] + bbox[2]) / 2.0, float(bbox[1] + bbox[3]) / 2.0)


def bbox_min_side(bbox):
    return float(min(bbox[2] - bbox[0], bbox[3] - bbox[1]))


def bbox_area(bbox):
    return float(max(0.0, bbox[2] - bbox[0]) * max(0.0, bbox[3] - bbox[1]))


def point_in_rect(point, rect):
    """rect = [x1, y1, x2, y2]; inclusive bounds."""
    return rect[0] <= point[0] <= rect[2] and rect[1] <= point[1] <= rect[3]


def iou(a, b):
    ix1, iy1 = max(a[0], b[0]), max(a[1], b[1])
    ix2, iy2 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = bbox_area(a) + bbox_area(b) - inter
    return float(inter / union) if union > 0 else 0.0


def nms(boxes, scores, iou_thresh):
    """Greedy NMS; returns kept indices in descending score order.

    Ported from ims_id_server face_backend/src_recognition/scrfd.py::SCRFD.nms,
    including its "+1" pixel area convention.
    """
    boxes = np.asarray(boxes, dtype=np.float32)
    scores = np.asarray(scores, dtype=np.float32).reshape(-1)
    if boxes.shape[0] == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1 + 1) * (y2 - y1 + 1)
    order = scores.argsort(kind="mergesort")[::-1]
    keep = []
    while order.size > 0:
        i = order[0]
        keep.append(int(i))
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        w = np.maximum(0.0, xx2 - xx1 + 1)
        h = np.maximum(0.0, yy2 - yy1 + 1)
        inter = w * h
        ovr = inter / (areas[i] + areas[order[1:]] - inter)
        order = order[np.where(ovr <= iou_thresh)[0] + 1]
    return keep


def expand_bbox(bbox, factor):
    cx, cy = bbox_center(bbox)
    hw = (bbox[2] - bbox[0]) * factor / 2.0
    hh = (bbox[3] - bbox[1]) * factor / 2.0
    return [cx - hw, cy - hh, cx + hw, cy + hh]


def clip_bbox(bbox, width, height):
    return [
        float(np.clip(bbox[0], 0, width - 1)),
        float(np.clip(bbox[1], 0, height - 1)),
        float(np.clip(bbox[2], 0, width - 1)),
        float(np.clip(bbox[3], 0, height - 1)),
    ]


def umeyama_similarity(src, dst):
    """Least-squares similarity transform (rotation, uniform scale, translation) src -> dst.

    Returns a 2x3 float64 matrix. Equivalent to skimage.transform.SimilarityTransform.estimate
    (Umeyama 1991), which the reference repo uses but which is not available on the Nano.
    """
    src = np.asarray(src, dtype=np.float64)
    dst = np.asarray(dst, dtype=np.float64)
    n, dim = src.shape
    src_mean = src.mean(axis=0)
    dst_mean = dst.mean(axis=0)
    src_c = src - src_mean
    dst_c = dst - dst_mean
    cov = dst_c.T.dot(src_c) / n
    d = np.ones((dim,), dtype=np.float64)
    if np.linalg.det(cov) < 0:
        d[dim - 1] = -1
    u, s, vt = np.linalg.svd(cov)
    rank = np.linalg.matrix_rank(cov)
    if rank == 0:
        raise ValueError("degenerate point set")
    if rank == dim - 1:
        if np.linalg.det(u) * np.linalg.det(vt) > 0:
            r = u.dot(vt)
        else:
            sign = d[dim - 1]
            d[dim - 1] = -1
            r = u.dot(np.diag(d)).dot(vt)
            d[dim - 1] = sign
    else:
        r = u.dot(np.diag(d)).dot(vt)
    src_var = src_c.var(axis=0).sum()
    scale = 1.0 / src_var * s.dot(d)
    t = dst_mean - scale * r.dot(src_mean)
    m = np.zeros((2, 3), dtype=np.float64)
    m[:, :2] = scale * r
    m[:, 2] = t
    return m


def center_scale_matrix(center, output_size, scale):
    """2x3 affine: scale about the origin, move `center` to the middle of an output_size square.

    Same matrix as reference face_align.transform(..., rotation=0).
    """
    s = float(scale)
    half = output_size / 2.0
    return np.array(
        [[s, 0.0, half - center[0] * s],
         [0.0, s, half - center[1] * s]],
        dtype=np.float64,
    )


def apply_affine(points, m):
    pts = np.asarray(points, dtype=np.float64)
    return (pts.dot(np.asarray(m)[:, :2].T) + np.asarray(m)[:, 2]).astype(np.float32)
