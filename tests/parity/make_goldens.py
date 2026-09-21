"""Regenerate tests/fixtures/goldens.npz by running the REFERENCE implementation
(/home/hunghn/code/ims_id_server) on tests/fixtures/astronaut.jpg with our fixed-shape ONNX.

Dev machine only (needs torch, onnxruntime, skimage and the reference repo).
Usage: python tests/parity/make_goldens.py [--ref-repo PATH]
"""
import argparse
import os
import sys

import cv2
import numpy as np

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
# Reference classes run on the RAW insightface ONNX: their mean/std heuristic reads node
# names that onnxsim rewrites, and this also checks that fix_shapes.py kept numerics intact.
RAW_DIR = os.path.join(REPO, "models", "onnx", "raw")
FIXTURES = os.path.join(REPO, "tests", "fixtures")


def test_images():
    """(name, BGR image): the square fixture and a 16:9 canvas that exercises letterboxing."""
    img = cv2.imread(os.path.join(FIXTURES, "astronaut.jpg"))
    wide = np.zeros((720, 1280, 3), dtype=np.uint8)
    wide[100:612, 600:1112] = img
    return [("square", img), ("wide", wide)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref-repo", default=os.environ.get("IMS_REF_REPO", "/home/hunghn/code/ims_id_server"))
    args = ap.parse_args()
    os.chdir(args.ref_repo)
    sys.path.insert(0, args.ref_repo)
    sys.path.insert(0, os.path.join(args.ref_repo, "anti_spoofing", "src"))

    import torch
    import torch.nn.functional as F
    from face_backend.insightface.app.common import Face
    from face_backend.insightface.model_zoo.landmark import Landmark
    from face_backend.src_recognition import face_align
    from face_backend.src_recognition.arcface_onnx import ArcFaceONNX
    from face_backend.src_recognition.scrfd import SCRFD
    from anti_spoofing.src.generate_patches import CropImage

    sys.path.insert(0, os.path.join(REPO, "tools", "convert"))
    from minifasnet_pth2onnx import MODELS, load_torch_model

    det = SCRFD(os.path.join(RAW_DIR, "det_500m.onnx"))
    det.prepare(-1)
    lmk = Landmark(os.path.join(RAW_DIR, "2d106det.onnx"))
    rec = ArcFaceONNX(os.path.join(RAW_DIR, "w600k_mbf.onnx"))
    fas = [load_torch_model(args.ref_repo, pth)[0] for pth, _ in MODELS]
    fas_scales = [2.7, 4.0]

    out = {"det_thresh": np.float32(0.5), "nms_thresh": np.float32(det.nms_thresh),
           "lmk_mean": np.float32(lmk.input_mean), "lmk_std": np.float32(lmk.input_std)}
    rng = np.random.RandomState(0)
    for name, img in test_images():
        dets, kpss = det.detect(img, input_size=(640, 640), thresh=0.5)
        assert len(dets) >= 1, "reference found no face in " + name
        out[name + "/det"] = dets.astype(np.float32)
        out[name + "/kps"] = kpss.astype(np.float32)

        face = Face(bbox=dets[0, :4], kps=kpss[0], det_score=dets[0, 4])
        lmk.get(img, face)
        out[name + "/lmk106"] = face["landmark_2d_106"].astype(np.float32)

        aligned = face_align.norm_crop(img, kpss[0], image_size=112)
        out[name + "/aligned"] = aligned
        out[name + "/emb_raw"] = rec.get_feat(aligned).reshape(-1).astype(np.float32)

        x1, y1, x2, y2 = [float(v) for v in dets[0, :4]]
        bbox_xywh = [x1, y1, x2 - x1, y2 - y1]
        out[name + "/fas_bbox_xywh"] = np.float32(bbox_xywh)
        for model, scale in zip(fas, fas_scales):
            crop = CropImage().crop(img, bbox_xywh, scale, 80, 80, True)
            x = torch.from_numpy(crop.transpose((2, 0, 1))).float().unsqueeze(0)
            with torch.no_grad():
                prob = F.softmax(model(x), dim=1).numpy()[0]
            out["{}/fas_{}".format(name, scale)] = prob.astype(np.float32)

        # CropImage parity on random boxes, including ones that hit the image border
        h, w = img.shape[:2]
        boxes, crops = [], []
        for _ in range(20):
            bw, bh = rng.uniform(20, w * 0.6), rng.uniform(20, h * 0.6)
            bx, by = rng.uniform(-bw * 0.3, w - bw * 0.7), rng.uniform(-bh * 0.3, h - bh * 0.7)
            scale = float(rng.choice([1.0, 2.7, 4.0]))
            boxes.append([bx, by, bw, bh, scale])
            crops.append(CropImage().crop(img, [bx, by, bw, bh], scale, 80, 80, True))
        out[name + "/crop_boxes"] = np.float64(boxes)
        out[name + "/crops"] = np.stack(crops)

    dst = os.path.join(FIXTURES, "goldens.npz")
    np.savez_compressed(dst, **out)
    print("wrote", dst, "keys:", sorted(out))
    for name, _ in test_images():
        print(name, "det", out[name + "/det"][:, 4], "fas2.7", out[name + "/fas_2.7"],
              "fas4.0", out[name + "/fas_4.0"])


if __name__ == "__main__":
    main()
