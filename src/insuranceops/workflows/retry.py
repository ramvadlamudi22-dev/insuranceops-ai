"""Retry policy with exponential backoff and jitter."""

from __future__ import annotations

import random as _random_mod
from dataclasses import dataclass, field
from random import Random


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Configuration for exponential backoff with jitter.

    Attributes:
        base_delay_s: Base delay in seconds for the first retry.
        cap_s: Maximum delay cap in seconds.
        jitter: Jitter strategy. Currently only "full" is supported.
    """

    base_delay_s: float = field(default=2.0)
    cap_s: float = field(default=60.0)
    jitter: str = field(default="full")


def compute_backoff_delay(
    policy: RetryPolicy,
    attempt_number: int,
    rng: Random | None = None,
) -> float:
    """Compute the backoff delay for a retry attempt.

    Formula:
        raw = min(cap_s, base_delay_s * 2^(attempt_number - 1))
        If jitter == "full": delay = uniform(0, raw)

    Args:
        policy: The retry policy configuration.
        attempt_number: 1-based attempt number (first retry is 1).
        rng: Optional Random instance for deterministic testing.

    Returns:
        Delay in seconds before the next retry.
    """
    raw = min(policy.cap_s, policy.base_delay_s * (2 ** (attempt_number - 1)))

    if policy.jitter == "full":
        if rng is not None:
            return rng.uniform(0, raw)
        return _random_mod.uniform(0, raw)

    # Default: no jitter
    return raw
