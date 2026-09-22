# -*- coding: utf-8 -*-
"""LBPH face recognition in numpy, for the classical baseline the spec asks for.

Why not cv2.face: JetPack's OpenCV 4.1.1 has no contrib modules, and pip offers only a
154 MB source tarball of opencv-contrib-python 5.x for aarch64 — which does not build for
Python 3.6 and would take hours on a Nano anyway (D-27). Building it would also risk
shadowing the JetPack OpenCV the rest of the pipeline depends on.

So the algorithm is reimplemented here, matching OpenCV's `cv2.face.LBPHFaceRecognizer`
detail for detail: the same circular sampling with bilinear interpolation, the same
epsilon comparison, the same unnormalised spatial histograms and the same chi-square
distance. tests/unit/test_lbph_parity.py checks the histograms and the predictions
against cv2.face on a dev machine, so "reimplemented" does not mean "different".
"""
import math

import numpy as np

DEFAULT_RADIUS = 1
DEFAULT_NEIGHBORS = 8
DEFAULT_GRID = 8
EPS = np.finfo(np.float32).eps


def lbp_image(gray, radius=DEFAULT_RADIUS, neighbors=DEFAULT_NEIGHBORS):
    """Circular LBP codes, mirroring OpenCV's elbp().

    The result is (rows - 2*radius, cols - 2*radius): the border has no full circle of
    neighbours, exactly as in OpenCV.
    """
    gray = np.asarray(gray, dtype=np.float32)
    rows, cols = gray.shape
    out_rows, out_cols = rows - 2 * radius, cols - 2 * radius
    if out_rows <= 0 or out_cols <= 0:
        raise ValueError("image {}x{} is too small for radius {}".format(rows, cols, radius))

    center = gray[radius:radius + out_rows, radius:radius + out_cols]
    codes = np.zeros((out_rows, out_cols), dtype=np.int32)

    for n in range(neighbors):
        # Sample point on the circle; OpenCV negates the sine, so bit 0 sits to the right.
        x = radius * math.cos(2.0 * math.pi * n / neighbors)
        y = -radius * math.sin(2.0 * math.pi * n / neighbors)
        fx, fy = int(math.floor(x)), int(math.floor(y))
        cx, cy = int(math.ceil(x)), int(math.ceil(y))
        ty, tx = y - fy, x - fx          # fractional parts

        w1 = (1 - tx) * (1 - ty)
        w2 = tx * (1 - ty)
        w3 = (1 - tx) * ty
        w4 = tx * ty

        top_left = gray[radius + fy:radius + fy + out_rows, radius + fx:radius + fx + out_cols]
        top_right = gray[radius + fy:radius + fy + out_rows, radius + cx:radius + cx + out_cols]
        bottom_left = gray[radius + cy:radius + cy + out_rows, radius + fx:radius + fx + out_cols]
        bottom_right = gray[radius + cy:radius + cy + out_rows, radius + cx:radius + cx + out_cols]
        sampled = (w1 * top_left + w2 * top_right + w3 * bottom_left + w4 * bottom_right)

        # OpenCV treats "equal within one float epsilon" as set, not clear.
        hit = (sampled > center) | (np.abs(sampled - center) < EPS)
        codes |= hit.astype(np.int32) << n
    return codes


def spatial_histogram(codes, grid_x=DEFAULT_GRID, grid_y=DEFAULT_GRID,
                      neighbors=DEFAULT_NEIGHBORS, normed=True):
    """Concatenated per-cell histograms, like OpenCV's spatial_histogram().

    OpenCV normalises each cell by its own pixel count (LBPH::train passes normed=true),
    so every cell sums to 1 and cells of different sizes stay comparable.
    """
    bins = 1 << neighbors
    rows, cols = codes.shape
    cell_h, cell_w = rows // grid_y, cols // grid_x
    if cell_h == 0 or cell_w == 0:
        raise ValueError("LBP image {}x{} is smaller than the {}x{} grid".format(
            rows, cols, grid_x, grid_y))
    histogram = np.zeros(grid_x * grid_y * bins, dtype=np.float32)
    index = 0
    for row in range(grid_y):
        for col in range(grid_x):
            cell = codes[row * cell_h:(row + 1) * cell_h, col * cell_w:(col + 1) * cell_w]
            counts = np.bincount(cell.ravel(), minlength=bins)[:bins].astype(np.float32)
            if normed:
                total = counts.sum()
                if total > 0:
                    counts = counts / total
            histogram[index:index + bins] = counts
            index += bins
    return histogram


def chi_square(reference, query):
    """OpenCV's HISTCMP_CHISQR: sum((reference - query)^2 / reference).

    Asymmetric on purpose — the stored histogram is the denominator, exactly as in
    LBPH::predict, where compareHist is called with the enrolled sample first. Bins where
    the reference is zero are skipped, like OpenCV does.
    """
    reference = np.asarray(reference, dtype=np.float64)
    query = np.asarray(query, dtype=np.float64)
    difference = reference - query
    mask = np.abs(reference) > EPS
    return float(np.sum(difference[mask] ** 2 / reference[mask]))


class LBPHRecognizer(object):
    """train() / predict(), the two calls the baseline needs.

    predict() returns (label, distance); LOWER distance means more similar, which is the
    opposite of the cosine score the main pipeline uses. run.py flips the sign so both
    feed the same ROC/DET code in M9.
    """

    def __init__(self, radius=DEFAULT_RADIUS, neighbors=DEFAULT_NEIGHBORS,
                 grid_x=DEFAULT_GRID, grid_y=DEFAULT_GRID, threshold=None):
        self.radius = radius
        self.neighbors = neighbors
        self.grid_x = grid_x
        self.grid_y = grid_y
        self.threshold = threshold
        self.histograms = np.zeros((0, 0), dtype=np.float32)
        self.labels = np.zeros((0,), dtype=np.int32)

    def describe(self, gray):
        codes = lbp_image(gray, self.radius, self.neighbors)
        return spatial_histogram(codes, self.grid_x, self.grid_y, self.neighbors)

    def train(self, images, labels):
        self.histograms = np.vstack([self.describe(image) for image in images])
        self.labels = np.asarray(labels, dtype=np.int32)
        return self

    def update(self, images, labels):
        new = np.vstack([self.describe(image) for image in images])
        self.histograms = new if self.histograms.size == 0 else np.vstack(
            [self.histograms, new])
        self.labels = np.concatenate([self.labels, np.asarray(labels, dtype=np.int32)])
        return self

    def predict(self, gray):
        """(label, distance), or (-1, inf) when nothing was trained or nothing is close."""
        if self.histograms.size == 0:
            return -1, float("inf")
        query = self.describe(gray)
        # Stored histogram first: chi_square is asymmetric, and OpenCV compares that way.
        distances = np.array([chi_square(row, query) for row in self.histograms])
        best = int(np.argmin(distances))
        distance = float(distances[best])
        if self.threshold is not None and distance > self.threshold:
            return -1, distance
        return int(self.labels[best]), distance

    def predict_all(self, gray):
        """Distance to every enrolled sample: needed to score impostor pairs in M9."""
        query = self.describe(gray)
        return self.labels.copy(), np.array([chi_square(row, query)
                                             for row in self.histograms])

    def save(self, path):
        np.savez_compressed(path, histograms=self.histograms, labels=self.labels,
                            params=np.array([self.radius, self.neighbors,
                                             self.grid_x, self.grid_y], dtype=np.int32))
        return path

    @classmethod
    def load(cls, path):
        data = np.load(path)
        radius, neighbors, grid_x, grid_y = [int(v) for v in data["params"]]
        model = cls(radius, neighbors, grid_x, grid_y)
        model.histograms = data["histograms"]
        model.labels = data["labels"]
        return model
