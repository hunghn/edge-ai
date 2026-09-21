"""TensorRT backend (Jetson Nano, TensorRT 8.2 + pycuda, Python 3.6).

Uses the binding API (get_binding_*, execute_async_v2) on purpose: the tensor API
(set_tensor_address / execute_async_v3) only exists from TensorRT 8.5, which JetPack
4.6 does not ship.

Engines must have static shapes — build them with tools/convert/fix_shapes.py output
and scripts/build_engines.sh. A dynamic dimension raises at load time.

All engines in one process share a single CUDA context (pycuda.autoinit), so the
engine process can hold the 5 models at once.
"""
from collections import OrderedDict

import numpy as np

from edgeface.runtime.base import Backend, TensorSpec

_TRT_LOGGER = None


def _lazy_imports():
    # Imported lazily so `import edgeface` works on a dev machine without TensorRT.
    global _TRT_LOGGER
    import pycuda.autoinit  # noqa: F401  (creates and keeps the process-wide context)
    import pycuda.driver as cuda
    import tensorrt as trt

    if _TRT_LOGGER is None:
        _TRT_LOGGER = trt.Logger(trt.Logger.WARNING)
    return trt, cuda


class TrtBackend(Backend):
    def __init__(self, path):
        super(TrtBackend, self).__init__(path)
        trt, cuda = _lazy_imports()
        self._cuda = cuda

        with open(path, "rb") as f:
            engine_bytes = f.read()
        runtime = trt.Runtime(_TRT_LOGGER)
        self._engine = runtime.deserialize_cuda_engine(engine_bytes)
        if self._engine is None:
            raise RuntimeError(
                "failed to deserialize {} — engines are specific to the device and the "
                "TensorRT version; rebuild with scripts/build_engines.sh".format(path))
        self._context = self._engine.create_execution_context()
        self._stream = cuda.Stream()

        self._inputs, self._outputs = [], []
        self._host, self._device, self._shapes = {}, {}, {}
        self._bindings = [0] * self._engine.num_bindings
        for idx in range(self._engine.num_bindings):
            name = self._engine.get_binding_name(idx)
            shape = tuple(int(d) for d in self._engine.get_binding_shape(idx))
            if any(d < 0 for d in shape):
                raise RuntimeError(
                    "{}: binding {} has dynamic shape {}; rebuild the engine with static "
                    "shapes".format(path, name, shape))
            dtype = np.dtype(trt.nptype(self._engine.get_binding_dtype(idx)))
            host = cuda.pagelocked_empty(int(np.prod(shape)), dtype)
            device = cuda.mem_alloc(host.nbytes)
            self._host[name] = host
            self._device[name] = device
            self._shapes[name] = shape
            self._bindings[idx] = int(device)
            spec = TensorSpec(name, shape, dtype.type)
            (self._inputs if self._engine.binding_is_input(idx) else self._outputs).append(spec)

    @property
    def inputs(self):
        return list(self._inputs)

    @property
    def outputs(self):
        return list(self._outputs)

    def infer(self, feeds):
        cuda = self._cuda
        if len(feeds) != len(self._inputs):
            raise ValueError("expected inputs {}, got {}".format(
                [s.name for s in self._inputs], sorted(feeds)))
        for spec in self._inputs:
            arr = np.ascontiguousarray(feeds[spec.name], dtype=spec.dtype)
            if arr.shape != spec.shape:
                raise ValueError("{}: expected shape {}, got {}".format(
                    spec.name, spec.shape, arr.shape))
            np.copyto(self._host[spec.name], arr.ravel())
            cuda.memcpy_htod_async(self._device[spec.name], self._host[spec.name], self._stream)

        self._context.execute_async_v2(bindings=self._bindings,
                                       stream_handle=self._stream.handle)

        for spec in self._outputs:
            cuda.memcpy_dtoh_async(self._host[spec.name], self._device[spec.name], self._stream)
        self._stream.synchronize()

        return OrderedDict(
            (spec.name, self._host[spec.name].reshape(self._shapes[spec.name]).copy())
            for spec in self._outputs)

    def close(self):
        # Free in reverse order of creation; pycuda frees the context at interpreter exit.
        for name in list(self._device):
            try:
                self._device.pop(name).free()
            except Exception:  # pragma: no cover - best effort on shutdown
                pass
        self._host.clear()
        self._context = None
        self._engine = None

    def __del__(self):  # pragma: no cover
        try:
            self.close()
        except Exception:
            pass
