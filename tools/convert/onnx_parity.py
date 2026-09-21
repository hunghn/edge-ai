"""Numerical parity of the final models/onnx/*.onnx against their sources:
  - insightface models: raw (dynamic-shape) ONNX vs fixed-shape + onnxsim ONNX
  - MiniFASNet: PyTorch .pth (reference repo classes) vs ONNX
Random inputs in each model's real value range. Engine (FP16) parity is tests/device (M2).

Usage: python tools/convert/onnx_parity.py [--ref-repo PATH] [--n 16]
"""
import argparse
import os
import sys

import numpy as np
import onnxruntime

sys.path.insert(0, os.path.dirname(__file__))
from _common import DEFAULT_REF_REPO, ONNX_DIR, RAW_DIR  # noqa: E402
from minifasnet_pth2onnx import MODELS, load_torch_model  # noqa: E402

# name -> (shape, low, high) of the raw input tensor
INSIGHTFACE = {
    "det_500m": ([1, 3, 640, 640], -1.0, 1.0),
    "2d106det": ([1, 3, 192, 192], 0.0, 255.0),
    "w600k_mbf": ([1, 3, 112, 112], -1.0, 1.0),
}
TOL = 1e-3


def session(path):
    return onnxruntime.InferenceSession(path, providers=["CPUExecutionProvider"])


def run(sess, x):
    return sess.run(None, {sess.get_inputs()[0].name: x})


def max_diff(a_list, b_list):
    # outputs may be reordered by onnxsim; match by name-independent shape+order
    assert len(a_list) == len(b_list)
    return max(float(np.abs(a - b).max()) for a, b in zip(a_list, b_list))


def main():
    import torch

    ap = argparse.ArgumentParser()
    ap.add_argument("--ref-repo", default=DEFAULT_REF_REPO)
    ap.add_argument("--n", type=int, default=16)
    args = ap.parse_args()
    rng = np.random.RandomState(0)
    failed = False

    for name, (shape, lo, hi) in INSIGHTFACE.items():
        raw, fixed = session(os.path.join(RAW_DIR, name + ".onnx")), session(os.path.join(ONNX_DIR, name + ".onnx"))
        worst = 0.0
        for _ in range(args.n):
            x = rng.uniform(lo, hi, size=shape).astype(np.float32)
            worst = max(worst, max_diff(run(raw, x), run(fixed, x)))
        failed |= worst > TOL
        print("{:24s} raw vs fixed  max|diff| = {:.2e}".format(name, worst))

    for pth_name, onnx_name in MODELS:
        model, (h, w) = load_torch_model(args.ref_repo, pth_name)
        sess = session(os.path.join(ONNX_DIR, onnx_name))
        worst = 0.0
        for _ in range(args.n):
            x = rng.uniform(0, 255, size=(1, 3, h, w)).astype(np.float32)
            with torch.no_grad():
                ref = model(torch.from_numpy(x)).numpy()
            worst = max(worst, float(np.abs(ref - run(sess, x)[0]).max()))
        failed |= worst > TOL
        print("{:24s} pth vs onnx   max|diff| = {:.2e}".format(onnx_name[:-5], worst))

    if failed:
        raise SystemExit("parity FAILED (tol {})".format(TOL))
    print("parity OK (tol {})".format(TOL))


if __name__ == "__main__":
    main()
