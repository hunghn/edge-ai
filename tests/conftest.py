"""Markers:
  ort  - needs onnxruntime and the ONNX files in models/onnx (dev machine)
  nano - needs TensorRT engines in models/engines (Jetson Nano)
tests/unit must stay pure numpy/OpenCV and Python 3.6-compatible.
"""
import os

import pytest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
FIXTURES = os.path.join(REPO, "tests", "fixtures")
ONNX_DIR = os.path.join(REPO, "models", "onnx")


def pytest_configure(config):
    config.addinivalue_line("markers", "ort: needs onnxruntime + models/onnx")
    config.addinivalue_line("markers", "nano: needs TensorRT engines on a Jetson Nano")


@pytest.fixture(scope="session")
def repo_root():
    return REPO


@pytest.fixture(scope="session")
def fixtures_dir():
    return FIXTURES
