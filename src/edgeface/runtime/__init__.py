"""Inference backends with an identical interface (see base.Backend)."""
import os


def create_backend(kind, model_dir, stem):
    """kind: "ort" -> <model_dir>/<stem>.onnx, "trt" -> <model_dir>/<stem>.engine."""
    if kind == "ort":
        from edgeface.runtime.ort_backend import OrtBackend
        return OrtBackend(os.path.join(model_dir, stem + ".onnx"))
    if kind == "trt":
        from edgeface.runtime.trt_backend import TrtBackend
        return TrtBackend(os.path.join(model_dir, stem + ".engine"))
    raise ValueError("unknown backend: {}".format(kind))
