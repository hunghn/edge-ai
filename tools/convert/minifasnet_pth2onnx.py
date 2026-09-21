"""Convert MiniFASNetV2 (scale 2.7) and MiniFASNetV1SE (scale 4.0) .pth -> ONNX (1x3x80x80).

Uses the model classes and parse_model_name/get_kernel from the reference repo, so the
architecture matches the trained weights exactly. Output is logits (softmax is applied by
edgeface.models.minifasnet). Verifies torch vs onnxruntime on random 0-255 inputs.

Usage: python tools/convert/minifasnet_pth2onnx.py [--ref-repo /path/to/ims_id_server]
"""
import argparse
import os
import sys
from collections import OrderedDict

import numpy as np

sys.path.insert(0, os.path.dirname(__file__))
from _common import DEFAULT_REF_REPO, RAW_DIR  # noqa: E402

MODELS = [
    ("2.7_80x80_MiniFASNetV2.pth", "minifasnet_v2_2.7.onnx"),
    ("4_0_0_80x80_MiniFASNetV1SE.pth", "minifasnet_v1se_4.0.onnx"),
]


def load_torch_model(ref_repo, pth_name):
    import torch

    sys.path.insert(0, os.path.join(ref_repo, "anti_spoofing", "src"))
    from model_lib.MiniFASNet import MiniFASNetV1SE, MiniFASNetV2  # noqa: E402
    from utility import get_kernel, parse_model_name  # noqa: E402

    mapping = {"MiniFASNetV2": MiniFASNetV2, "MiniFASNetV1SE": MiniFASNetV1SE}
    h, w, model_type, _ = parse_model_name(pth_name)
    model = mapping[model_type](conv6_kernel=get_kernel(h, w))
    path = os.path.join(ref_repo, "anti_spoofing", "resources", "anti_spoof_models", pth_name)
    state = torch.load(path, map_location="cpu")
    if next(iter(state)).startswith("module."):
        state = OrderedDict((k[len("module."):], v) for k, v in state.items())
    model.load_state_dict(state)
    model.eval()
    return model, (h, w)


def convert(ref_repo, pth_name, onnx_name, opset):
    import onnx
    import onnxruntime
    import torch
    from onnxsim import simplify

    model, (h, w) = load_torch_model(ref_repo, pth_name)
    dst = os.path.join(RAW_DIR, onnx_name)
    dummy = torch.rand(1, 3, h, w) * 255.0
    torch.onnx.export(model, dummy, dst, input_names=["input"], output_names=["logits"],
                      opset_version=opset, do_constant_folding=True, dynamo=False)
    simplified, ok = simplify(onnx.load(dst))
    if not ok:
        raise SystemExit("onnxsim check failed for " + dst)
    onnx.save(simplified, dst)

    sess = onnxruntime.InferenceSession(dst, providers=["CPUExecutionProvider"])
    rng = np.random.RandomState(0)
    worst = 0.0
    for _ in range(8):
        x = (rng.rand(1, 3, h, w) * 255.0).astype(np.float32)
        with torch.no_grad():
            ref = model(torch.from_numpy(x)).numpy()
        out = sess.run(None, {"input": x})[0]
        worst = max(worst, float(np.abs(ref - out).max()))
    print("{} -> {} max|torch-onnx| logits = {:.2e}".format(pth_name, dst, worst))
    if worst > 1e-3:
        raise SystemExit("parity failed for " + onnx_name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref-repo", default=DEFAULT_REF_REPO)
    ap.add_argument("--opset", type=int, default=11)
    args = ap.parse_args()
    os.makedirs(RAW_DIR, exist_ok=True)
    for pth_name, onnx_name in MODELS:
        convert(args.ref_repo, pth_name, onnx_name, args.opset)


if __name__ == "__main__":
    main()
