"""PAM alphabets and binary-reflected Gray labelling."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import numpy as np
from numpy.typing import NDArray

SUPPORTED_ORDERS = (2, 4, 8, 16)


def _check_order(order: int) -> int:
    if order not in SUPPORTED_ORDERS:
        raise ValueError(f"PAM order must be one of {SUPPORTED_ORDERS}, got {order}")
    return int(np.log2(order))


def pam_levels(order: int) -> NDArray[np.float64]:
    """Return the odd-integer levels, e.g. [-3, -1, 1, 3] for PAM4."""
    _check_order(order)
    return np.arange(-(order - 1), order, 2, dtype=float)


def gray_labels(order: int) -> NDArray[np.int64]:
    """Return the Gray integer label of each symbol index, lowest level first."""
    _check_order(order)
    indices = np.arange(order)
    return indices ^ (indices >> 1)


def label_bits(order: int) -> NDArray[np.int8]:
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
