"""Backend interface shared by TensorRT (device) and onnxruntime (dev)."""
from collections import namedtuple

# shape: tuple of ints; dtype: numpy dtype
TensorSpec = namedtuple("TensorSpec", ["name", "shape", "dtype"])


class Backend(object):
    """infer({input_name: ndarray}) -> OrderedDict{output_name: ndarray}.

    Output order follows the model's declared output order. Model wrappers must not rely
    on that order when a backend may reorder bindings; they should identify outputs by
    name or shape.
    """

    def __init__(self, path):
        self.path = path

    @property
    def inputs(self):
        raise NotImplementedError

    @property
    def outputs(self):
        raise NotImplementedError

    def infer(self, feeds):
        raise NotImplementedError

    def close(self):
        pass
