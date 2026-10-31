"""Frame construction: preamble, common training and payload blocks."""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import zlib
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from opticps.distribution_matching.ccdm import ConstantCompositionMatcher
from opticps.modulation.pam import (
    FRAME_ALIGNMENT,
    ModulationSpec,
    bits_to_indices,
    indices_to_bits,
)

PREAMBLE_LENGTH = 512
TRAINING_LENGTH = 512  # the PAM2 and PAM4 training length; see ModulationSpec for M = 8, 16
TRAINING_STREAM_KEY = 0x7A11  # SeedSequence key of the training permutation
IntArray = NDArray[np.int64]


def m_sequence(degree: int = 9, taps: tuple[int, ...] = (9, 5)) -> NDArray[np.int8]:
    """Return a maximal-length binary sequence from a Fibonacci LFSR."""
    state = [1] * degree
    output = np.empty(2**degree - 1, dtype=np.int8)
    for i in range(output.size):
        output[i] = state[-1]
        feedback = 0
        for tap in taps:
            feedback ^= state[tap - 1]
        state = [feedback] + state[:-1]
    return output


def preamble_indices(order: int = 4) -> IntArray:
    """Return the DC-balanced outer-level preamble (symbol indices 0 and M - 1)."""
    ModulationSpec(order)
    chips = m_sequence().astype(np.int64)
    balanced = np.append(chips, 0 if chips.sum() * 2 > chips.size else 1)
    return balanced * (order - 1)


def training_indices(seed: int, order: int = 4) -> IntArray:
    """Return common, exactly balanced training symbols, the same for all waveforms."""
    spec = ModulationSpec(order)
    rng = np.random.default_rng([seed, TRAINING_STREAM_KEY])
    return rng.permutation(np.repeat(np.arange(order, dtype=np.int64), spec.training_per_level))


@dataclass(frozen=True)
class Frame:
    """Everything the receiver needs to reconstruct what was transmitted."""

    indices: IntArray
    info_bits: NDArray[np.int8]
    label_bits: NDArray[np.int8]
    payload_start: int
    block_length: int
    n_blocks: int
    bits_per_block: int
    matcher_counts: tuple[int, ...] | None
    order: int = 4

    @property
    def payload_indices(self) -> IntArray:
        return self.indices[self.payload_start :]

    @property
    def distribution_matcher_rate(self) -> float:
        return self.bits_per_block / self.block_length


def make_matcher(
    probabilities: object, block_length: int, order: int = 4
) -> ConstantCompositionMatcher:
    """Return the CCDM matcher a shaped frame of this order uses.

    PAM4 keeps the original quantiser (pinned byte for byte); other orders use the symmetric
    one, which never splits a +-x pair.
    """
    if order == 4:
        return ConstantCompositionMatcher.from_probabilities(probabilities, block_length)
    return ConstantCompositionMatcher.from_symmetric_probabilities(probabilities, block_length)


def payload_rng(seed: int, name: str) -> np.random.Generator:
    """Return the deterministic generator of one waveform's information bits."""
    return np.random.default_rng([seed, zlib.crc32(name.encode())])


def build_frame(
    name: str,
    probabilities: object,
    total_symbols: int,
    seed: int,
    block_length: int = 1024,
    direct_uniform: bool = False,
    order: int = 4,
) -> Frame:
    """Build a frame of exactly total_symbols symbols.

    direct_uniform maps information bits straight onto Gray labels, the unshaped baseline at
    exactly log2 M bits per symbol (2 at M = 4, byte for byte the v1.2 frame). Otherwise each
    block passes through CCDM. The head (preamble plus training) is a multiple of 1024 for every
    order, and the payload a multiple of the block length.
    """
    spec = ModulationSpec(order)
    m = spec.bits_per_symbol
    head = np.concatenate([preamble_indices(order), training_indices(seed, order)])
    if head.size % FRAME_ALIGNMENT:
        raise ValueError(f"Head of {head.size} symbols is not a multiple of {FRAME_ALIGNMENT}")
    payload_length = total_symbols - head.size
    if payload_length <= 0 or payload_length % block_length:
        raise ValueError(
            f"Payload of {payload_length} symbols is not a positive multiple of {block_length}"
        )
    n_blocks = payload_length // block_length
    rng = payload_rng(seed, name)
    if direct_uniform:
        bits = rng.integers(0, 2, m * payload_length, dtype=np.int8)
        payload = bits_to_indices(bits, order)
        bits_per_block = m * block_length
        counts = None
    else:
        matcher = make_matcher(probabilities, block_length, order)
        bits = rng.integers(0, 2, matcher.k * n_blocks, dtype=np.int8)
        payload = np.concatenate(
            [matcher.encode(block) for block in bits.reshape(n_blocks, matcher.k)]
        )
        bits_per_block = matcher.k
        counts = matcher.counts
    indices = np.concatenate([head, payload])
    return Frame(
        indices=indices,
        info_bits=bits,
        label_bits=indices_to_bits(indices, order),
        payload_start=head.size,
        block_length=block_length,
        n_blocks=n_blocks,
        bits_per_block=bits_per_block,
        matcher_counts=counts,
        order=order,
    )
