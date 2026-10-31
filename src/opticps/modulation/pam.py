"""PAM alphabets and binary-reflected Gray labelling."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

SUPPORTED_ORDERS = (2, 4, 8, 16)
PREAMBLE_SYMBOLS = 512
# Training symbols per order: 512 at M = 2 and 4 (the v1.2 frame), then 192 per level at M = 8
# and 160 per level at M = 16, so that the per-level mean and sigma estimates keep a relative
# error near 1 / sqrt(2 (N - 1)) (5.6 % one sigma at N = 160; measured in tests/test_mpam_frame_rx).
TRAINING_SYMBOLS = {2: 512, 4: 512, 8: 1536, 16: 2560}
FRAME_ALIGNMENT = 1024  # the head (preamble plus training) is a multiple of this


def _check_order(order: int) -> int:
    if order not in SUPPORTED_ORDERS:
        raise ValueError(f"PAM order must be one of {SUPPORTED_ORDERS}, got {order}")
    return int(np.log2(order))


def pam_levels(order: int = 4) -> NDArray[np.float64]:
    """Return the odd-integer levels, e.g. [-3, -1, 1, 3] for PAM4."""
    _check_order(order)
    return np.arange(-(order - 1), order, 2, dtype=float)


def gray_labels(order: int = 4) -> NDArray[np.int64]:
    """Return the Gray integer label of each symbol index, lowest level first."""
    _check_order(order)
    indices = np.arange(order)
    return indices ^ (indices >> 1)


def label_bits(order: int = 4) -> NDArray[np.int8]:
    """Return an (order, m) array of Gray label bits, most significant first."""
    m = _check_order(order)
    labels = gray_labels(order)
    return np.array([[(lab >> (m - 1 - k)) & 1 for k in range(m)] for lab in labels], dtype=np.int8)


def indices_to_bits(indices: NDArray[np.integer], order: int = 4) -> NDArray[np.int8]:
    """Map symbol indices to a flat Gray label bit stream."""
    table = label_bits(order)
    return table[np.asarray(indices)].reshape(-1)


def bits_to_indices(bits: NDArray[np.integer], order: int = 4) -> NDArray[np.int64]:
    """Map a flat Gray label bit stream to symbol indices."""
    m = _check_order(order)
    bits = np.asarray(bits, dtype=np.int64)
    if bits.size % m:
        raise ValueError(f"Bit stream length {bits.size} is not a multiple of {m}")
    weights = 1 << np.arange(m - 1, -1, -1)
    labels = bits.reshape(-1, m) @ weights
    inverse = np.zeros(order, dtype=np.int64)
    inverse[gray_labels(order)] = np.arange(order)
    return inverse[labels]


@dataclass(frozen=True)
class ModulationSpec:
    """One PAM alphabet: its order and the quantities derived from it.

    Levels are the odd integers -(M-1), ..., M-1 (spacing 2, so the outer levels are at
    +-(M-1)); symbol index i has level 2 i - (M - 1). The module-level functions are the same
    maps for a given order, kept for the existing callers.
    """

    order: int = 4

    def __post_init__(self) -> None:
        _check_order(self.order)

    @property
    def name(self) -> str:
        return f"PAM{self.order}"

    @property
    def bits_per_symbol(self) -> int:
        return _check_order(self.order)

    @property
    def levels(self) -> NDArray[np.float64]:
        return pam_levels(self.order)

    @property
    def full_scale_levels(self) -> int:
        """The outer level, M - 1, in level units."""
        return self.order - 1

    @property
    def gray(self) -> NDArray[np.int64]:
        return gray_labels(self.order)

    @property
    def label_bits(self) -> NDArray[np.int8]:
        return label_bits(self.order)

    @property
    def preamble_symbols(self) -> int:
        return PREAMBLE_SYMBOLS

    @property
    def training_symbols(self) -> int:
        return TRAINING_SYMBOLS[self.order]

    @property
    def training_per_level(self) -> int:
        return self.training_symbols // self.order

    @property
    def head_symbols(self) -> int:
        return self.preamble_symbols + self.training_symbols

    def indices_to_bits(self, indices: NDArray[np.integer]) -> NDArray[np.int8]:
        return indices_to_bits(indices, self.order)

    def bits_to_indices(self, bits: NDArray[np.integer]) -> NDArray[np.int64]:
        return bits_to_indices(bits, self.order)
