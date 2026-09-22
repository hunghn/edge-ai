"""The in-memory gallery: today's patients as a matrix S9 can multiply against.

Reloading is deliberately coarse. The engine checks the version between sessions only,
never in the middle of one, so a sync pulling new patients cannot change the answer
half-way through an identification.
"""
import numpy as np

from edgeface.common.log import get_logger
from edgeface.storage import templates

LOG = get_logger("gallery")


class Gallery(object):
    """codes (N), matrix (M, 512) float32, owner (M,) int32 -> index into codes."""

    def __init__(self, recognizer_sha256):
        self.recognizer_sha256 = recognizer_sha256
        self.codes = []
        self.matrix = np.zeros((0, templates.EMBEDDING_DIM), dtype=np.float32)
        self.owner = np.zeros((0,), dtype=np.int32)
        self.version = None
        self.loaded_at = None

    @property
    def n_patients(self):
        return len(self.codes)

    @property
    def n_templates(self):
        return int(self.matrix.shape[0])

    def is_empty(self):
        return self.n_templates == 0

    def load(self, conn, now=None):
        self.codes, self.matrix, self.owner = templates.load_gallery(
            conn, self.recognizer_sha256, now)
        self.version = templates.gallery_version(conn)
        self.loaded_at = now
        LOG.info("gallery v%s: %d patients, %d templates",
                 self.version, self.n_patients, self.n_templates)
        return self

    def refresh_if_changed(self, conn, now=None):
        """Reload only when the stored version moved. Call between sessions."""
        current = templates.gallery_version(conn)
        if current == self.version:
            return False
        self.load(conn, now)
        return True

    def group_offsets(self):
        """Start index of each patient's block, for np.maximum.reduceat."""
        if self.n_templates == 0:
            return np.zeros((0,), dtype=np.int64)
        boundaries = np.flatnonzero(np.diff(self.owner)) + 1
        return np.concatenate([[0], boundaries]).astype(np.int64)
