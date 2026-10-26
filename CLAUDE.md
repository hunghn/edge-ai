# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Plan-First Policy (MANDATORY)

> **Never write code before a plan has been reviewed.**

### Required workflow for every feature/task
- Any feature/task touching **more than 1 file** → **enter Plan mode first** (EnterPlanMode), present the plan, and wait for user approval (ExitPlanMode) before creating or editing any code file.
- **Write the plan's explanations in Vietnamese.** Keep code identifiers, file paths, and technical terms (e.g. TensorRT, SCRFD, FP16) as-is.
- A plan must state at minimum: goal, files to create/edit, approach, thresholds/values that need user confirmation (never invent them — see the §6 note below), and how it will be tested/measured.
- If the scope changes significantly from the approved plan mid-task → stop, update the plan, and ask for approval again.
- Plan mode may be skipped only for small, obvious changes confined to 1 file (typo, a constant the user already specified, a one-line fix).

## Project

Edge face recognition with RGB anti-spoofing for patient identification at an IVF clinic kiosk, running on **Jetson Nano 4GB**. Scope: 30–60 enrolled patients/day, no face masks, single RGB camera (no depth/IR). A nurse always makes the final confirmation — the system never auto-admits.

The design spec is `docs/pipeline_jetson_nano.docx` (Vietnamese). It is binary; extract text with:
`python3 -c "import zipfile,re;x=zipfile.ZipFile('docs/pipeline_jetson_nano.docx').read('word/document.xml').decode();[print(''.join(re.findall(r'<w:t[^>]*>([^<]*)</w:t>',p))) for p in re.findall(r'<w:p[ >].*?</w:p>',x,re.S)]"`
The spec cites decision thresholds in "§6 / §6.3" (S9 matching, S10 rule engine) that are **not written in the doc** — ask the user rather than inventing values.

## Reference code

`/home/hunghn/code/ims_id_server` is an existing server-side (x86, Flask + Milvus + PyTorch + onnxruntime) implementation of the same building blocks. Port logic from it; do not copy its stack.
- `face_backend/src_recognition/scrfd.py`, `arcface_onnx.py`, `face_align.py` — SCRFD decode/NMS, ArcFace embedding, 5-point similarity alignment (`arcface_src` template).
- `face_backend/insightface/model_zoo/landmark.py` — 2d106det pre/post-processing.
- `anti_spoofing/src/generate_patches.py` (`CropImage`), `model_lib/MiniFASNet.py`, `tools/tools.py::check_real_face` — MiniFASNet crops and fusion.
- Its `.onnx` files are Git LFS pointers (~130 bytes); run `git lfs pull` there before using them.
- It uses `det_2.5g` + `w600k_r50`, anti-spoof threshold 0.65 and Milvus — all differ from this project's spec below.
- Its ratio-based head pose (`tools/tools.py::face_analysis`) **is** used for the S5 gate, with its thresholds (C-25, 2026-10-08): solvePnP with a generic 3D model measures frontal faces at pitch −8°…−22° and rejected every frame.

## Target platform constraints (Jetson Nano, JetPack 4.6.x)

- Ubuntu 18.04, **Python 3.6**, TensorRT 8.2 Python API, OpenCV from JetPack. Verified on the actual device (2026-09-21): OpenCV 4.1.1 is built **without CUDA** (`cv2.cuda.getCudaEnabledDeviceCount() == 0`) but **with GStreamer 1.14.5**, numpy is 1.13.3 and SQLite is 3.22.0. Code that runs on the device must be 3.6-compatible: no dataclasses, walrus, `subprocess.run(capture_output=...)`, `from __future__ import annotations`, or modern-only wheels. Many pip wheels have no arm64/py3.6 build.
- **No PyTorch, onnxruntime, Milvus, or Flask on the device.** Inference is TensorRT only; vector search is numpy brute-force cosine.
- **FP16 only — no INT8** (Maxwell GPU lacks DP4A).
- Nano model choices: detector `det_500m.onnx`, recognizer `w600k_mbf.onnx` (not det_10g / w600k_r50, which are the non-Nano options in the spec).
- TensorRT engines are device/version-specific: export ONNX anywhere, but build `.engine` files **on the Nano** (e.g. `trtexec --onnx=... --fp16 --saveEngine=...`). Never commit engines.
- MiniFASNet weights are `.pth`; convert to ONNX on a dev machine using the model classes from the reference repo (`parse_model_name` gives input size/kernel).
- RAM budget ~4 GB shared CPU/GPU: engine process 2.0–2.6 GB, kiosk ~250 MB, sync ~80 MB.

## Pipeline (S0–S10)

| Stage | Implementation | Gate / on fail |
|---|---|---|
| S0 capture | GStreamer `nvarguscamerasrc`, 1080p → 640×640 BGR, ring buffer (latest frame) | 10–15 FPS |
| S1 detect | SCRFD, input (x−127.5)/128 | score ≥ 0.6; 0 faces → IDLE |
| S2 subject | ROI geometry, largest bbox | center ∈ ROI, side ≥ 110 px; else "step closer" |
| S3 coarse pose | yaw/roll from 5 kps | \|yaw\| ≤ 25°, \|roll\| ≤ 20°; else "look straight", skip S4 |
| S4 anti-spoof | MiniFASNetV2 (crop scale 2.7) + MiniFASNetV1SE (scale 4.0), 80×80 BGR, sum softmax | argmax = real and p_real ≥ 0.85; else `spoof_suspect`, save evidence image |
| S5 landmark + IQA | 2d106det on 192×192 crop (bbox ×1.5), landmark ratios from ims_id_server `face_analysis` (C-25; solvePnP only displayed), Laplacian var, luminance | UD ∈ (0.20, 0.85), RL ∈ [0.5, 2.2], eyes open (> 0.12), mouth closed (< 0.20), \|roll\| ≤ 10°, blur ≥ 60, 60 ≤ lum ≤ 200; else wait for better frame |
| S6 align | similarity transform to ArcFace 5-pt template | 112×112 RGB |
| S7 embed | ArcFace, (x−127.5)/127.5, RGB | 512-d, L2-normalized |
| S8 best-frame | buffer by quality_score | ≤ 5 embeddings in ≤ 1.5 s; < 3 good frames → `low_quality` |
| S9 match | cosine vs gallery, top1/top2, 3-of-5 vote | below threshold → manual confirmation |
| S10 decide | rule engine over S4+S5+S9 | always show nurse manual-confirm button |

Pre-processing gotchas carried over from the reference code:
- MiniFASNet input is **raw 0–255 float CHW BGR — not divided by 255** (its custom `to_tensor` skips `/255`). Classes: index 1 = real; 0 and 2 = spoof (print/replay).
- MiniFASNet crops use `CropImage` with bbox as `[x, y, w, h]`, not `[x1, y1, x2, y2]`.
- 2d106det output is normalized to [−1, 1]; map back through the crop transform.

## Runtime architecture

Processes on the Nano, communicating via **SQLite in WAL mode** (not sockets/queues), managed by systemd:
1. `capture` — thread inside engine; GStreamer → ring buffer.
2. `engine` — S1–S10 loop, loads the TRT engines, session state, writes events to outbox.
3. `kiosk` — separate process, lightweight native UI (Qt/GTK), pose guidance, nurse confirm button.
4. `sync` — separate process; pushes outbox to server in batches with retry/backoff; pulls gallery, model bundle, revocation list.

Offline-first: pipeline must keep working without network. The local gallery is a daily copy that auto-deletes after 24 h and honors the server's revocation list. Model bundles from the server are signed; verify SHA-256 before loading.

## Evaluation

Every stage must be instrumented for latency (per-stage, p50/p95 end-to-end), FPS, peak RAM, per-core CPU, and power. Accuracy metrics: TAR@FAR=1e-3/1e-4, FRR, Rank-1, ROC/DET; anti-spoof APCER/BPCER/ACER (ISO/IEC 30107-3). A Haar+LBPH baseline must run on the same device for comparison.
