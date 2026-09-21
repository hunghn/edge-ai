"""Shared paths and manifest helpers for tools/convert (dev machine, Python >= 3.8)."""
import hashlib
import os
import re

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW_DIR = os.path.join(REPO, "models", "onnx", "raw")
ONNX_DIR = os.path.join(REPO, "models", "onnx")
MANIFEST = os.path.join(REPO, "models", "manifest.yaml")
DEFAULT_REF_REPO = os.environ.get("IMS_REF_REPO", "/home/hunghn/code/ims_id_server")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def set_manifest_field(model, field, value):
    """Rewrite `field:` inside the `model:` block of manifest.yaml in place (keeps comments)."""
    with open(MANIFEST) as f:
        lines = f.read().split("\n")
    in_block = False
    for i, line in enumerate(lines):
        if re.match(r"^\S", line):
            in_block = line.rstrip() == "{}:".format(model)
            continue
        if in_block and re.match(r"^  {}:".format(re.escape(field)), line):
            lines[i] = "  {}: {}".format(field, value)
            break
    else:
        raise KeyError("{}.{} not found in manifest".format(model, field))
    with open(MANIFEST, "w") as f:
        f.write("\n".join(lines))
