"""Check that models on this device match models/manifest.yaml.

- ONNX files: sha256 must equal the manifest value.
- Engines: the sidecar <name>.engine.json written by build_engines.sh must reference the
  same ONNX sha256 and the TensorRT version currently installed. Engines are device- and
  version-specific, so a mismatch means "rebuild", not "maybe fine".

Usage: python3 scripts/verify_models.py [--engines] [--onnx]
Exit code 0 = everything checked is consistent.
"""
import argparse
import hashlib
import json
import os
import sys

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(REPO, "src"))


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def trt_version():
    try:
        import tensorrt
        return tensorrt.__version__
    except ImportError:
        return None


def main():
    import yaml

    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", action="store_true", help="check ONNX only")
    ap.add_argument("--engines", action="store_true", help="check engines only")
    args = ap.parse_args()
    check_onnx = args.onnx or not args.engines
    check_engines = args.engines or not args.onnx

    with open(os.path.join(REPO, "models", "manifest.yaml")) as f:
        manifest = yaml.safe_load(f)

    installed_trt = trt_version()
    problems = []
    for name, entry in sorted(manifest.items()):
        expected = entry.get("sha256")
        onnx_path = os.path.join(REPO, "models", "onnx", entry["file"])
        if check_onnx:
            if not os.path.exists(onnx_path):
                print("{:22s} ONNX  MISSING".format(name))
                problems.append(name + ": onnx missing")
            else:
                actual = sha256_file(onnx_path)
                ok = (expected is None) or (actual == expected)
                print("{:22s} ONNX  {}".format(name, "ok" if ok else "SHA MISMATCH"))
                if not ok:
                    problems.append("{}: onnx sha {} != manifest {}".format(
                        name, actual[:12], (expected or "")[:12]))

        if check_engines:
            engine = os.path.join(REPO, "models", "engines", name + ".engine")
            sidecar = engine + ".json"
            if not os.path.exists(engine):
                print("{:22s} ENGINE not built".format(name))
                continue
            if not os.path.exists(sidecar):
                print("{:22s} ENGINE no sidecar (built outside build_engines.sh)".format(name))
                problems.append(name + ": engine sidecar missing")
                continue
            with open(sidecar) as f:
                meta = json.load(f)
            notes = []
            if expected and meta.get("onnx_sha256") != expected:
                notes.append("built from a different ONNX")
            if installed_trt and meta.get("tensorrt") not in (None, "unknown", installed_trt):
                notes.append("built with TensorRT {} != {}".format(
                    meta.get("tensorrt"), installed_trt))
            print("{:22s} ENGINE {}".format(name, "ok" if not notes else "; ".join(notes)))
            problems.extend("{}: {}".format(name, n) for n in notes)

    if problems:
        print("\n{} problem(s):".format(len(problems)))
        for p in problems:
            print("  -", p)
        return 1
    print("\nAll checked models are consistent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
