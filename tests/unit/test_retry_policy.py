"""Tests for retry policy backoff computation."""

from __future__ import annotations

from random import Random

from insuranceops.workflows.retry import RetryPolicy, compute_backoff_delay


class TestBackoffComputation:
    """Verify exponential backoff with jitter respects bounds."""

    def test_backoff_first_retry(self, random_seed: Random) -> None:
        """Attempt 1 with base_delay_s=2, cap_s=60 -> raw=2, delay in [0, 2]."""
        policy = RetryPolicy(base_delay_s=2.0, cap_s=60.0, jitter="full")
        delay = compute_backoff_delay(policy, attempt_number=1, rng=random_seed)
        assert 0.0 <= delay <= 2.0

    def test_backoff_second_retry(self, random_seed: Random) -> None:
        """Attempt 2 -> raw=4, delay in [0, 4]."""
        policy = RetryPolicy(base_delay_s=2.0, cap_s=60.0, jitter="full")
        delay = compute_backoff_delay(policy, attempt_number=2, rng=random_seed)
        assert 0.0 <= delay <= 4.0

    def test_backoff_cap_enforcement(self, random_seed: Random) -> None:
        """Attempt 10 with cap_s=60 -> raw=min(60, 2*512)=60, delay in [0, 60]."""
        policy = RetryPolicy(base_delay_s=2.0, cap_s=60.0, jitter="full")
        delay = compute_backoff_delay(policy, attempt_number=10, rng=random_seed)
        assert 0.0 <= delay <= 60.0

    def test_backoff_deterministic_with_seed(self) -> None:
        """With Random(42), same attempt always produces same delay."""
        policy = RetryPolicy(base_delay_s=2.0, cap_s=60.0, jitter="full")

        rng1 = Random(42)
        delay1 = compute_backoff_delay(policy, attempt_number=3, rng=rng1)

        rng2 = Random(42)
        delay2 = compute_backoff_delay(policy, attempt_number=3, rng=rng2)

        assert delay1 == delay2

    def test_default_policy_values(self) -> None:
        """RetryPolicy() has expected defaults."""
        policy = RetryPolicy()
        assert policy.base_delay_s == 2.0
        assert policy.cap_s == 60.0
        assert policy.jitter == "full"
