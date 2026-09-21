"""ArcFace recognizer (w600k_mbf) wrapper.

Ported from ims_id_server face_backend/src_recognition/arcface_onnx.py::ArcFaceONNX.get_feat:
input is the 112x112 aligned crop, converted BGR -> RGB, (x - 127.5) / 127.5.
"""
import numpy as np

from edgeface.common.imgproc import l2_normalize, to_blob

MEAN = 127.5
STD = 127.5


class ArcFace(object):
    def __init__(self, backend, input_size=112):
        self.backend = backend
        self.input_size = int(input_size)
        self._input_name = backend.inputs[0].name

    def preprocess(self, aligned_bgr):
        if aligned_bgr.shape[:2] != (self.input_size, self.input_size):
            raise ValueError("ArcFace expects a {0}x{0} aligned crop".format(self.input_size))
        return to_blob(aligned_bgr, MEAN, STD, swap_rb=True)

    def embed(self, aligned_bgr):
        """aligned_bgr: 112x112x3 uint8 BGR from pipeline.align. Returns (512,) L2-normalized."""
        out = list(self.backend.infer({self._input_name: self.preprocess(aligned_bgr)}).values())[0]
        return l2_normalize(np.asarray(out, dtype=np.float32).reshape(-1))

    def embed_raw(self, aligned_bgr):
        """Un-normalized embedding (for parity tests against the reference)."""
        out = list(self.backend.infer({self._input_name: self.preprocess(aligned_bgr)}).values())[0]
        return np.asarray(out, dtype=np.float32).reshape(-1)
