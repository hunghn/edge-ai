"""onnxruntime backend. Dev machine only: onnxruntime is never installed on the Nano."""
from collections import OrderedDict

import numpy as np

from edgeface.runtime.base import Backend, TensorSpec

_ORT_DTYPES = {
    "tensor(float)": np.float32,
    "tensor(float16)": np.float16,
    "tensor(int64)": np.int64,
    "tensor(int32)": np.int32,
}


def _static_shape(shape):
    return tuple(d if isinstance(d, int) else -1 for d in shape)


class OrtBackend(Backend):
    def __init__(self, path, providers=None):
        super(OrtBackend, self).__init__(path)
        import onnxruntime  # lazy: keeps edgeface importable without onnxruntime

        opts = onnxruntime.SessionOptions()
        opts.log_severity_level = 3
        self._session = onnxruntime.InferenceSession(
            path, sess_options=opts, providers=providers or ["CPUExecutionProvider"])
        self._inputs = [
            TensorSpec(i.name, _static_shape(i.shape), _ORT_DTYPES.get(i.type, np.float32))
            for i in self._session.get_inputs()
        ]
        self._outputs = [
            TensorSpec(o.name, _static_shape(o.shape), _ORT_DTYPES.get(o.type, np.float32))
            for o in self._session.get_outputs()
        ]

    @property
    def inputs(self):
        return list(self._inputs)

    @property
    def outputs(self):
        return list(self._outputs)

    def infer(self, feeds):
        names = [o.name for o in self._outputs]
        results = self._session.run(names, feeds)
        return OrderedDict(zip(names, results))
