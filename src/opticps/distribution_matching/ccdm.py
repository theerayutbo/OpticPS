"""Constant composition distribution matching, exact enumerative implementation.

CCDM is an invertible fixed-to-fixed map from k uniform bits into the set of
length-n sequences that have one fixed symbol composition (Schulte and Boecherer,
2016, who realise it with arithmetic coding). Here the map is the lexicographic
rank of a multiset permutation, an enumerative code in the sense of Cover (1973),
computed with exact integers. It uses k = floor(log2(multinomial)).
"""

# SPDX-License-Identifier: MIT
from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray

from opticps.shaping.distributions import entropy_bits, validate_probabilities


class DistributionMatcherError(ValueError):
    """Base class for matcher failures."""


class CompositionError(DistributionMatcherError):
    """The received block does not have the matcher's composition."""


class RankOverflowError(DistributionMatcherError):
    """The block has the right composition but no bit sequence maps to it."""


def quantize_composition(probabilities: object, n: int) -> tuple[int, ...]:
    """Return integer symbol counts summing to n, by the largest-remainder rule.

    Equal remainders are resolved symmetrically where the leftover allows it.
    """
    if n <= 0:
        raise ValueError(f"Block length must be positive, got {n}")
    p = validate_probabilities(probabilities)
    scaled = p * n
    counts = np.floor(scaled + 1e-12).astype(int)
    remainders = np.round(scaled - counts, 9)
    leftover = n - int(counts.sum())
    order = np.lexsort((np.arange(p.size), -remainders))
    for index in order[:leftover]:
        counts[index] += 1
    if np.any((p > 0) & (counts == 0)):
        raise DistributionMatcherError(
            f"Block length {n} cannot represent distribution {p.tolist()}"
        )
    return tuple(int(c) for c in counts)


def multinomial(counts: Sequence[int]) -> int:
    """Return the exact multinomial coefficient n! / prod(c_i!)."""
    total = math.factorial(sum(counts))
    for count in counts:
        total //= math.factorial(count)
    return total


@dataclass(frozen=True)
class CcdmBlockResult:
    """Outcome of decoding one possibly corrupted block."""

    bits: NDArray[np.int8] | None
    error: str | None


class ConstantCompositionMatcher:
    """Reversible matcher for one composition."""

    def __init__(self, counts: Sequence[int]):
        if any(c < 0 for c in counts) or sum(counts) == 0:
            raise ValueError(f"Invalid composition {tuple(counts)}")
        self.counts = tuple(int(c) for c in counts)
        self.n = sum(self.counts)
        self.alphabet_size = len(self.counts)
        self.size = multinomial(self.counts)
        self.k = self.size.bit_length() - 1

    @classmethod
    def from_probabilities(cls, probabilities: object, n: int) -> ConstantCompositionMatcher:
        """Build a matcher for the composition nearest to a target distribution."""
        return cls(quantize_composition(probabilities, n))

    @property
    def realised_probabilities(self) -> NDArray[np.float64]:
        return np.array(self.counts, dtype=float) / self.n

    @property
    def rate(self) -> float:
        """Input bits per output symbol."""
        return self.k / self.n

    @property
    def rate_loss(self) -> float:
        """H(realised composition) minus the matcher rate, in bits per symbol."""
        return entropy_bits(self.realised_probabilities) - self.rate

    def encode(self, bits: NDArray[np.integer]) -> NDArray[np.int64]:
        """Map exactly k bits to one block of n symbol indices."""
        bits = np.asarray(bits)
        if bits.size != self.k:
            raise ValueError(f"Expected {self.k} bits, got {bits.size}")
        if np.any((bits != 0) & (bits != 1)):
            raise ValueError("Input bits must be 0 or 1")
        rank = int("".join("1" if b else "0" for b in bits) or "0", 2)
        remaining = list(self.counts)
        block_size = self.size
        symbols = np.empty(self.n, dtype=np.int64)
        for position in range(self.n):
            left = self.n - position
            for symbol, count in enumerate(remaining):
                if count == 0:
                    continue
                branch = block_size * count // left
                if rank < branch:
                    symbols[position] = symbol
                    remaining[symbol] -= 1
                    block_size = branch
                    break
                rank -= branch
            else:  # pragma: no cover
                raise DistributionMatcherError("Rank exceeded the type class size")
        return symbols

    def decode(self, symbols: NDArray[np.integer]) -> NDArray[np.int8]:
        """Invert encode for one block; raises on a block that cannot be valid."""
        symbols = np.asarray(symbols)
        if symbols.size != self.n:
            raise ValueError(f"Expected {self.n} symbols, got {symbols.size}")
        observed = tuple(np.bincount(symbols, minlength=self.alphabet_size).tolist())
        if observed != self.counts:
            raise CompositionError(f"Composition {observed} differs from {self.counts}")
        remaining = list(self.counts)
        block_size = self.size
        rank = 0
        for position, value in enumerate(symbols.tolist()):
            left = self.n - position
            for symbol in range(value):
                if remaining[symbol]:
                    rank += block_size * remaining[symbol] // left
            block_size = block_size * remaining[value] // left
            remaining[value] -= 1
        if rank >= 1 << self.k:
            raise RankOverflowError("Block maps to a rank above 2^k")
        text = format(rank, f"0{self.k}b") if self.k else ""
        return np.frombuffer(text.encode(), dtype=np.uint8).astype(np.int8) - ord("0")

    def try_decode(self, symbols: NDArray[np.integer]) -> CcdmBlockResult:
        """Decode a block from a noisy channel, reporting failures instead of raising."""
        try:
            return CcdmBlockResult(self.decode(symbols), None)
        except DistributionMatcherError as error:
            return CcdmBlockResult(None, type(error).__name__)
