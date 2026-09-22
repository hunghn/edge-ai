# edge-ai

Edge face recognition with RGB anti-spoofing for patient identification at an IVF clinic kiosk, running on a **Jetson Nano 4GB** (JetPack 4.6.x, Python 3.6, TensorRT 8.2, FP16).
The system only **suggests** an identity. A nurse always makes the final confirmation.

- Design spec: `docs/pipeline_jetson_nano.docx` (Vietnamese)
- Contributor and agent guidance: `CLAUDE.md`
- Detailed plans per milestone and per stage (Vietnamese): `docs/plans/` — start at `docs/plans/README.md`; open decisions in `docs/plans/decisions.md`

> **Status:** M1 done — project skeleton, config, onnxruntime backend, model wrappers (SCRFD, MiniFASNet, 2d106det, ArcFace), S6 alignment and ONNX conversion tools, with parity tests against the reference repo. The rest of the layout below is still a proposal; directories get created as each stage is built.

---

## 1. Design principles behind the layout

1. **Split by where code runs, because the Python versions differ.**
   - `src/edgeface/` and `scripts/` run **on the Nano**: Python 3.6, no PyTorch, no onnxruntime, no Flask or Milvus, and no dataclasses, walrus operator or `from __future__ import annotations`.
   - `tools/` runs on a **dev machine** (Python ≥ 3.8). It handles `.pth → ONNX` conversion, threshold calibration, metrics and plots. Code in `tools/` may import `edgeface`, but `edgeface` never imports from `tools/`.
2. **Keep model pre/post-processing separate from the inference runtime.**
   Each model wrapper (`models/`) is pure numpy/OpenCV: `preprocess → backend.infer → postprocess`. The backend can be swapped:
   - `TrtBackend` on the Nano
   - `OrtBackend` on a dev machine, imported lazily and never installed on the device

   This lets the SCRFD decode, MiniFASNet crops, 106-point mapping, alignment and matching be unit-tested on x86 against the reference repo. A separate parity test then checks the FP16 engines against FP32 ONNX outputs.
3. **One module per pipeline stage, all with the same result shape.**
   Every stage returns a `StageResult(ok, reason, data)`, and a timing decorator records its latency. `engine/loop.py` only orchestrates the stages and holds no thresholds or math.
4. **All gates and thresholds live in `configs/`, never in code.**
   Values that the spec defers to "§6 / §6.3" (S9 match and S10 rule engine) stay `null` until they are calibrated and confirmed. While they are `null`, the engine routes every result to `review_required`.
5. **Processes share only SQLite (WAL mode).**
   The schema and migrations live in one place (`storage/schema/`). `engine`, `kiosk` and `sync` import the same `storage` access layer, so no process writes raw SQL against another process's tables.
6. **Offline-first and privacy by default.**
   - The gallery has a 24 h TTL and honors the server's revocation list.
   - Model bundles are verified with SHA-256 before loading.
   - No face images are persisted except spoof evidence, which has its own retention policy.
   - Runtime state lives outside the repo in `/var/lib/edgeface/`.

---

## 2. Directory tree

```
edge-ai/
├── README.md
├── CLAUDE.md
├── setup.py                     # setuptools (py3.6-safe); installs package `edgeface`
├── requirements/
│   ├── device.txt               # Nano pins: PyYAML, requests, pycuda (numpy/cv2/tensorrt come from JetPack apt)
│   └── dev.txt                  # torch, onnx, onnxruntime, onnxsim, pytest, matplotlib, scikit-learn, vermin
│
├── configs/
│   ├── default.yaml             # every gate/threshold from the S0–S10 table; S9/S10 = null (TBD)
│   ├── nano.yaml                # overrides: GStreamer string, engine paths, backend: trt, db path
│   └── dev.yaml                 # overrides: backend: ort, video-file/USB source, local db path
│
├── models/                      # NOT committed except the manifest
│   ├── manifest.yaml            # name, file, sha256, input shape, preprocessing, upstream source
│   ├── onnx/                    # det_500m, 2d106det, w600k_mbf, minifasnet_v2_2.7, minifasnet_v1se_4.0
│   └── engines/                 # *.engine built ON the Nano (gitignored, device/TRT-version specific)
│
├── src/edgeface/                # ── ON-DEVICE PACKAGE (Python 3.6) ─────────────────────
│   ├── __init__.py
│   ├── config.py                # load + deep-merge YAML, validate ranges, expose read-only config
│   ├── types.py                 # namedtuples: Frame, Detection, FaceObs, StageResult, Embedding; Decision enum
│   │
│   ├── common/
│   │   ├── geometry.py          # xyxy<->xywh, IoU, NMS, ROI containment, bbox expand/clip
│   │   ├── imgproc.py           # resize/letterbox 1080p→640×640, normalize, HWC→CHW, BGR↔RGB
│   │   ├── timing.py            # @timed(stage) decorator, monotonic clock, per-stage histograms
│   │   └── log.py               # structured logging (journald-friendly)
│   │
│   ├── runtime/                 # inference backends — identical interface
│   │   ├── base.py              # Backend: infer({name: ndarray}) -> {name: ndarray}; input/output specs
│   │   ├── trt_backend.py       # TensorRT 8.2 + pycuda: deserialize engine, pinned host buffers, FP16
│   │   └── ort_backend.py       # onnxruntime (dev only; lazy import, never required on device)
│   │
│   ├── models/                  # model wrappers: pre → backend → post (ported logic, own code)
│   │   ├── scrfd.py             # (x−127.5)/128, anchor decode strides 8/16/32, NMS, 5 kps
│   │   ├── minifasnet.py        # CropImage port (bbox as [x,y,w,h]), raw 0–255 CHW BGR, softmax
│   │   ├── landmark106.py       # 2d106det: bbox×1.5 → 192×192, map [−1,1] back through crop transform
│   │   └── arcface.py           # 112×112 RGB, (x−127.5)/127.5, 512-d, L2-normalize
│   │
│   ├── pipeline/                # S0–S10 stage logic (one module per stage)
│   │   ├── base.py              # ok()/fail() so every stage returns StageResult
│   │   ├── landmark_index.py    # verified 106-landmark index map (see tools/viz)
│   │   ├── capture.py           # S0  GStreamer nvarguscamerasrc → RingBuffer thread; file/USB sources for dev
│   │   ├── detect.py            # S1  score gate; 0 faces → IDLE
│   │   ├── subject.py           # S2  largest bbox, center ∈ ROI, side ≥ min px
│   │   ├── pose.py              # S3  coarse yaw/roll from 5 kps; S5 solvePnP (EPNP seed, tz > 0)
│   │   ├── antispoof.py         # S4  fuse V2(2.7)+V1SE(4.0) softmax sums; p_real + argmax gate
│   │   ├── quality.py           # S5  Laplacian variance, luminance, quality_score
│   │   ├── align.py             # S6  similarity transform to ArcFace 5-pt template (arcface_src)
│   │   ├── embed.py             # S7  thin wrapper over models.arcface
│   │   ├── best_frame.py        # S8  top-K by quality_score in time window; < min good → low_quality
│   │   ├── matcher.py           # S9  numpy cosine (K×N), top1/top2, per-frame vote
│   │   └── decision.py          # S10 ordered rules R1–R6; every outcome needs the nurse
│   │
│   ├── engine/                  # process 2: engine
│   │   ├── __main__.py          # (M5) `python3 -m edgeface.engine --config configs/nano.yaml`
│   │   ├── models.py            # load the five wrappers; refuse engines built from other ONNX
│   │   ├── loop.py              # per-frame orchestration S1→S10, early-exit on failed gates
│   │   ├── session.py           # pure state machine: (state, event) → (state, actions)
│   │   ├── enroll.py            # capture 5 templates, duplicate + consistency checks
│   │   └── publisher.py         # debounced kiosk_state, /dev/shm preview, nurse commands
│   │
│   ├── gallery/
│   │   ├── gallery.py           # (N,512) matrix + ids; reloaded only between sessions
│   │   └── retention.py         # 24 h TTL purge, revocations, evidence/log TTL, clock guard
│   │
│   ├── storage/                 # shared by engine / kiosk / sync — the only SQL in the project
│   │   ├── db.py                # connect (WAL, busy_timeout, FK), transaction(), migrations
│   │   ├── clock.py             # epoch-seconds clock, replaceable in tests
│   │   ├── schema/
│   │   │   └── 001_init.sql     # 13 tables; SQLite 3.22-compatible syntax only
│   │   ├── patients.py          # patients + appointments, accent-insensitive search
│   │   ├── templates.py         # embeddings BLOB <-> (M,512) gallery matrix, version bump
│   │   ├── sessions.py          # audit trail of every attempt (no images)
│   │   ├── outbox.py            # enqueue / claim batch / mark sent / exponential backoff
│   │   ├── kiosk_ipc.py         # kiosk_state (engine→kiosk), kiosk_commands (kiosk→engine)
│   │   ├── operators.py         # nurse PIN: PBKDF2-HMAC-SHA256, lockout
│   │   ├── evidence.py          # spoof evidence images + retention
│   │   ├── metrics.py           # per-stage latency samples, written in batches
│   │   └── models_registry.py   # model bundles staged by sync
│   │
│   ├── kiosk/                   # process 3: kiosk UI (PyQt5 from apt; measured 59 MB)
│   │   ├── __main__.py
│   │   ├── strings.py           # every Vietnamese string, one place
│   │   ├── view_model.py        # engine state → screen, words, buttons (no Qt)
│   │   ├── controller.py        # polls kiosk_state, writes commands, PIN gate (no Qt)
│   │   ├── auth.py              # admin PIN + inactivity lock
│   │   ├── window.py            # QStackedWidget over the pages; draws only
│   │   ├── style.qss
│   │   └── widgets/             # numpad, camera preview with ROI outline
│   │
│   ├── sync/                    # process 4: sync (~80 MB budget)
│   │   ├── __main__.py
│   │   ├── client.py            # requests session, bearer token, timeouts, CA pinning
│   │   ├── uploader.py          # outbox batches with exponential backoff + jitter
│   │   ├── puller.py            # gallery + revocations; local enrollments are preserved
│   │   └── bundle.py            # sha256 + HMAC signature + manifest + path-traversal checks
│   │
│   └── metrics/
│       ├── recorder.py          # per-stage latency, e2e p50/p95, FPS → SQLite/CSV
│       └── tegrastats.py        # parse tegrastats: RAM, per-core CPU, GPU, power rails
│
├── baselines/
│   └── haar_lbph/               # Haar cascade + LBPH on the same device, same capture + metrics
│       ├── enroll.py
│       └── run.py               # needs cv2.face (opencv-contrib) — see open questions
│
├── scripts/                     # ── ON-DEVICE shell/py3.6 helpers ──────────────────────
│   ├── setup_nano.sh            # apt deps, pycuda build, swap/zram, power mode (nvpmodel), jetson_clocks
│   ├── build_engines.sh         # trtexec --onnx=... --fp16 --saveEngine=models/engines/...
│   ├── bench_model.py           # single-model latency on TRT (week 1–2 deliverable)
│   ├── db_admin.py              # init / create-operator / stats / purge / export-sessions
│   ├── enroll_from_video.py     # build a gallery from recorded clips (M8/M9)
│   └── run_pipeline_offline.py  # run S0–S8 over a recorded video for repeatable benchmarks
│
├── tools/                       # ── DEV MACHINE ONLY (Python ≥ 3.8) ────────────────────
│   ├── convert/
│   │   ├── minifasnet_pth2onnx.py   # uses MiniFASNet classes + parse_model_name from reference repo
│   │   ├── fetch_insightface.py     # download det_500m / 2d106det / w600k_mbf, write sha256 to manifest
│   │   └── onnx_parity.py           # pth vs onnx, onnx(FP32) vs engine(FP16) dumps
│   ├── dataset/
│   │   ├── record.py            # capture sessions, consent id tagging
│   │   └── build_gallery.py     # enroll images → embeddings → gallery DB for local testing
│   └── eval/
│       ├── recognition.py       # TAR@FAR=1e-3/1e-4, FRR, Rank-1, ROC/DET
│       ├── antispoof.py         # APCER / BPCER / ACER (ISO/IEC 30107-3)
│       ├── calibrate.py         # propose S4/S9/S10 thresholds from score dumps (for user sign-off)
│       ├── ops_report.py        # review_required rate, low_quality rate, attempts per success
│       └── perf_report.py       # latency/FPS/RAM/CPU/power tables from metrics DB + tegrastats
│
├── deploy/
│   └── systemd/
│       ├── edgeface-engine.service
│       ├── edgeface-kiosk.service   # After=graphical session; Requires engine DB present
│       └── edgeface-sync.service
│
├── tests/
│   ├── conftest.py              # markers: `nano` (needs TRT), `ort` (needs onnxruntime)
│   ├── fixtures/                # small face images, golden .npz outputs from reference repo
│   ├── unit/                    # pure numpy — runs on dev AND on device
│   │   ├── test_geometry.py  test_scrfd_decode.py  test_crop_image.py  test_align.py
│   │   ├── test_quality.py   test_best_frame.py    test_matcher.py     test_decision.py
│   │   └── test_session.py   test_outbox.py        test_retention.py   test_bundle_verify.py
│   ├── parity/                  # `ort`: our wrappers vs reference-repo goldens
│   └── device/                  # `nano`: TRT FP16 vs ONNX goldens (cosine ≥ tol), memory budget smoke test
│
├── server/                      # DEV MACHINE / clinic PC (Python >= 3.8), never on the Nano
│   ├── app.py                   # FastAPI: /api/v1 for devices, /admin for people
│   ├── models.py, db.py, auth.py, schemas.py, settings.py, cli.py
│   ├── api/{events,gallery,devices}.py
│   ├── web/{views,csrf}.py + web/templates/
│   └── tests/
│
└── docs/
    ├── plans/                   # one plan per milestone and per stage (Vietnamese)
    ├── results/                 # measurements: M2 latency, M3 pipeline, M6 kiosk, M7 sync
    ├── figures/                 # landmark index map, kiosk screenshots
    └── pipeline_jetson_nano.docx
```

---

## 3. Stage → module map

| Stage | Module | Model wrapper | Config keys (in `default.yaml`) |
|---|---|---|---|
| S0 capture | `pipeline/capture.py` | – | `capture.pipeline`, `capture.fps` |
| S1 detect | `pipeline/detect.py` | `models/scrfd.py` | `detect.score_min` |
| S2 subject | `pipeline/subject.py` | – | `subject.roi`, `subject.min_side_px` |
| S3 coarse pose | `pipeline/pose.py` | – | `pose_coarse.yaw_max`, `.roll_max` |
| S4 anti-spoof | `pipeline/antispoof.py` | `models/minifasnet.py` | `antispoof.p_real_min`, `.crops` |
| S5 landmark + IQA | `pipeline/pose.py`, `pipeline/quality.py` | `models/landmark106.py` | `pose_fine.*`, `iqa.blur_min`, `iqa.lum_range` |
| S6 align | `pipeline/align.py` | – | – |
| S7 embed | `pipeline/embed.py` | `models/arcface.py` | – |
| S8 best-frame | `pipeline/best_frame.py` | – | `best_frame.k_max`, `.window_s`, `.min_good` |
| S9 match | `pipeline/matcher.py` | – | `match.*` — **TBD (§6)** |
| S10 decide | `pipeline/decision.py` | – | `decision.*` — **TBD (§6.3)** |

Known `Decision` values from the spec are `spoof_suspect`, `low_quality` and `review_required`. The remaining values (for example, a "candidate suggested" outcome) depend on the §6.3 rules, which have not been decided yet.

---

## 4. Runtime data flow

```
          ┌──────────────────────── engine process (systemd) ────────────────────────┐
 camera → │ capture thread → RingBuffer(latest) → loop.py: S1 → S2 → S3 → S4 → S5 →  │
          │                                     S6 → S7 → S8 → S9 → S10 → session.py │
          │  TRT engines: scrfd · minifasnet_v2 · minifasnet_v1se · 2d106 · arcface  │
          └───────────────┬───────────────────────────────▲──────────────┬──────────┘
                          │ kiosk_state                   │ commands     │ outbox
                          ▼                               │              ▼
        ┌─────────────────────────── SQLite (WAL) /var/lib/edgeface/edge.db ─────────┐
        │ kiosk_state · kiosk_commands · outbox · gallery · gallery_meta ·           │
        │ revocations · model_bundles · metrics · evidence_index · schema_version    │
        └───────▲───────────────────────────┬──────────────────────────▲─────────────┘
                │ poll ~10 Hz               │ claim batch / mark sent  │ write gallery,
        ┌───────┴────────┐          ┌───────▼────────────────────────────┴──┐
        │ kiosk process  │          │ sync process  ⇄  server (HTTPS)       │
        │ guidance, nurse│          │ push outbox · pull gallery/revocation │
        │ confirm button │          │ pull model bundle → verify SHA-256    │
        └────────────────┘          └───────────────────────────────────────┘
```

- **Gallery reload:** `sync` writes new rows and bumps `gallery_meta.version`. `engine` checks the version between sessions and reloads the numpy matrix. It never reloads mid-session.
- **Model swap:** `sync` verifies a bundle and stages it. Engines are rebuilt or loaded only when the engine process restarts, never while it is running.
- **Nurse action:** `kiosk` inserts a command into `kiosk_commands`. `engine` consumes it, closes the session and writes the final event to `outbox`.

---

## 5. Conventions

- **Python 3.6 on the device:** use `typing` type comments or plain annotations, `collections.namedtuple` or plain classes, `subprocess.Popen` / `check_output` and f-strings (which 3.6 supports). CI runs `vermin --target=3.6 src/ scripts/ tests/unit/` and `pytest tests/unit` on a Python 3.6 interpreter.
- **Entry points:** `python3 -m edgeface.engine | edgeface.kiosk | edgeface.sync --config configs/nano.yaml`.
- **Never commit** anything under `models/onnx/` or `models/engines/`, datasets, SQLite files or evidence images. `models/manifest.yaml` is the source of truth for model hashes.
- **Reference repo** (`/home/hunghn/code/ims_id_server`): port its logic into `models/` and `pipeline/` and cite the source function in a comment. Don't copy its Flask, Milvus or PyTorch stack.
- **Adding a stage or gate:**
  1. Add the config key to `default.yaml`.
  2. Implement the stage as a pure function in `pipeline/`.
  3. Add a unit test.
  4. Wire the stage into `engine/loop.py` with `@timed`.

---

## 6. Build and run (target workflow)

```bash
# Dev machine
python3 -m venv .venv && . .venv/bin/activate
pip install --index-url https://download.pytorch.org/whl/cpu torch
pip install -r requirements/dev.txt && pip install -e .
python tools/convert/fetch_insightface.py      # det_500m, w600k_mbf (buffalo_sc), 2d106det (buffalo_l) -> models/onnx/raw
python tools/convert/minifasnet_pth2onnx.py    # .pth from the reference repo -> models/onnx/raw
python tools/convert/fix_shapes.py             # static 1x3xHxW + onnxsim -> models/onnx, sha256 -> manifest
python tools/convert/onnx_parity.py            # raw/pth vs final ONNX
python tests/parity/make_goldens.py            # only when goldens must be regenerated
vermin --target=3.6- --violations src/ tests/unit/
pytest tests/unit tests/parity

# Jetson Nano (JetPack 4.6.x, Python 3.6) — verified on the device, see docs/device_inventory.md
sudo scripts/setup_nano.sh                     # apt deps, pycuda, swap, power mode, /var/lib/edgeface
python3 -m pip install --user --no-deps -e .   # numpy/cv2/yaml come from apt, not pip
python3 scripts/verify_models.py               # ONNX sha256 vs manifest, engine sidecars
scripts/build_engines.sh                       # models/engines/*.engine, FP16, never committed
python3 scripts/bench_model.py --all --tegrastats   # per-model latency, RAM, power
python3 -m pytest tests/unit tests/device      # parity tests skip without engines
sudo cp deploy/systemd/*.service /etc/systemd/system && sudo systemctl enable --now edgeface-{engine,kiosk,sync}
```

---

## 7. Open questions (need a decision before implementation)

1. **S9 / S10 thresholds (§6, §6.3):** the match threshold, top1–top2 margin, vote rule details and full Decision enum. These are not in the spec.
2. **Kiosk camera preview:** SQLite can't carry a live preview. The proposal is that `engine` writes a downscaled JPEG to `/dev/shm/edgeface/preview.jpg` (atomic rename) and `kiosk` reads it. This needs confirmation, and the alternative is no preview.
3. **Server contract for `sync`:** endpoints, auth, gallery payload format and the bundle signing algorithm. The spec states SHA-256 but not the signature scheme.
4. **Haar+LBPH baseline:** `cv2.face` needs opencv-contrib, which JetPack's OpenCV doesn't include. The options are building contrib from source or running the baseline in a separate OpenCV build.
5. **Engine count:** the spec says "4 TensorRT engines", but the pipeline uses 5 models (the 2 MiniFASNets count separately). The question is whether to merge the two MiniFASNets into one dual-input ONNX or keep them separate.
