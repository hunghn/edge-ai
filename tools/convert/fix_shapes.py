"""Fix every model to a static 1xCxHxW input (TensorRT 8.2 on the Nano needs static shapes),
simplify with onnxsim, write models/onnx/<name>.onnx, and record sha256 in the manifest.

Also reports whether a graph normalizes its own input (Sub + Mul near the start), which is
how the reference repo picks mean/std for 2d106det and ArcFace. Use it to fill preprocess
mean/std in models/manifest.yaml.

Usage: python tools/convert/fix_shapes.py
"""
import os
import sys

import onnx
from onnxsim import simplify

sys.path.insert(0, os.path.dirname(__file__))
from _common import ONNX_DIR, RAW_DIR, set_manifest_field, sha256_file  # noqa: E402

SHAPES = {
    "det_500m": [1, 3, 640, 640],
    "2d106det": [1, 3, 192, 192],
    "w600k_mbf": [1, 3, 112, 112],
    "minifasnet_v2_2.7": [1, 3, 80, 80],
    "minifasnet_v1se_4.0": [1, 3, 80, 80],
}


def graph_normalizes_input(model):
    # Same heuristic as ims_id_server insightface/model_zoo/landmark.py::Landmark.__init__
    find_sub = find_mul = False
    for nid, node in enumerate(model.graph.node[:8]):
        if node.name.startswith("Sub") or node.name.startswith("_minus"):
            find_sub = True
        if node.name.startswith("Mul") or node.name.startswith("_mul"):
            find_mul = True
        if nid < 3 and node.name == "bn_data":
            find_sub = find_mul = True
    return find_sub and find_mul


def dims(value_info):
    return [d.dim_value if d.HasField("dim_value") else (d.dim_param or "?")
            for d in value_info.type.tensor_type.shape.dim]


def process(name, shape):
    src = os.path.join(RAW_DIR, name + ".onnx")
    dst = os.path.join(ONNX_DIR, name + ".onnx")
    model = onnx.load(src)
    initializers = {i.name for i in model.graph.initializer}
    inputs = [i for i in model.graph.input if i.name not in initializers]
    if len(inputs) != 1:
        raise SystemExit("{}: expected 1 input, got {}".format(name, [i.name for i in inputs]))
    in_name = inputs[0].name
    print("{}: raw input {} {}".format(name, in_name, dims(inputs[0])))
    self_norm = graph_normalizes_input(model)

    fixed, ok = simplify(model, overwrite_input_shapes={in_name: shape})
    if not ok:
        raise SystemExit(name + ": onnxsim check failed")
    fixed = onnx.shape_inference.infer_shapes(fixed)
    for vi in list(fixed.graph.input) + list(fixed.graph.output):
        if vi.name in initializers:
            continue
        d = dims(vi)
        if any(not isinstance(v, int) or v <= 0 for v in d):
            raise SystemExit("{}: non-static shape {} {}".format(name, vi.name, d))
    onnx.save(fixed, dst)

    opsets = [o.version for o in fixed.opset_import if o.domain in ("", "ai.onnx")]
    print("  -> {} opset={} self_normalizing_input={}".format(dst, opsets, self_norm))
    for vi in fixed.graph.output:
        print("     output {} {}".format(vi.name, dims(vi)))
    digest = sha256_file(dst)
    set_manifest_field(name, "sha256", digest)
    print("     sha256", digest)


def main():
    os.makedirs(ONNX_DIR, exist_ok=True)
    for name, shape in SHAPES.items():
        process(name, shape)


if __name__ == "__main__":
    main()
