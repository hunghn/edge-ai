"""Download det_500m, w600k_mbf (buffalo_sc) and 2d106det (buffalo_l) into models/onnx/raw/.

Usage: python tools/convert/fetch_insightface.py [--cache models/cache]
"""
import argparse
import os
import sys
import urllib.request
import zipfile

sys.path.insert(0, os.path.dirname(__file__))
from _common import RAW_DIR, REPO, sha256_file  # noqa: E402

RELEASE = "https://github.com/deepinsight/insightface/releases/download/v0.7/"
PACKS = {
    "buffalo_sc.zip": ["det_500m.onnx", "w600k_mbf.onnx"],
    "buffalo_l.zip": ["2d106det.onnx"],
}


def download(url, dst):
    if os.path.exists(dst):
        print("cached", dst)
        return
    print("downloading", url)
    tmp = dst + ".part"
    urllib.request.urlretrieve(url, tmp)
    os.replace(tmp, dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=os.path.join(REPO, "models", "cache"))
    args = ap.parse_args()
    os.makedirs(args.cache, exist_ok=True)
    os.makedirs(RAW_DIR, exist_ok=True)
    for pack, members in PACKS.items():
        zpath = os.path.join(args.cache, pack)
        download(RELEASE + pack, zpath)
        with zipfile.ZipFile(zpath) as z:
            names = z.namelist()
            for member in members:
                src = next((n for n in names if n.endswith("/" + member) or n == member), None)
                if src is None:
                    raise SystemExit("{} not found in {}".format(member, pack))
                dst = os.path.join(RAW_DIR, member)
                with z.open(src) as fin, open(dst, "wb") as fout:
                    fout.write(fin.read())
                print("extracted {} sha256={}".format(dst, sha256_file(dst)))


if __name__ == "__main__":
    main()
