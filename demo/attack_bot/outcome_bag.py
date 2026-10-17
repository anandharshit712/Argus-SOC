"""The pass/fail outcome bag (ATTACK_BOT_PASS_FAIL_DESIGN.md §4).

A shuffled bag, not a coin flip: `round(size * ratio)` pass tokens and the rest fail, drawn one at a
time, refilled and reshuffled when empty. So a size-10 bag at ratio 0.3 gives exactly 3 passes in
every 10 runs, in random order -- which a 30 % coin flip does not.

No deps on purpose, so the exact-ratio acceptance check (test_bag.py) runs anywhere.
"""

from __future__ import annotations

import random
import threading


class OutcomeBag:
    def __init__(self, size: int = 10, ratio: float = 0.3) -> None:
        if size < 1:
            raise ValueError("bag size must be >= 1")
        self.size = size
        self.ratio = ratio
        self._rng = random.SystemRandom()
        self._lock = threading.Lock()
        self._tokens: list[str] = []

    def _refill(self) -> None:
        n_pass = round(self.size * self.ratio)
        self._tokens = ["pass"] * n_pass + ["fail"] * (self.size - n_pass)
        self._rng.shuffle(self._tokens)

    def draw(self) -> str:
        """The next token, refilling a spent bag. 'pass' or 'fail'."""
        with self._lock:
            if not self._tokens:
                self._refill()
            return self._tokens.pop()

    def remaining(self) -> int:
        with self._lock:
            return len(self._tokens)
