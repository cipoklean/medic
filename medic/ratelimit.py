"""Client-side rate limiting.

Why this is here and not in the provider config: the free NaraRouter plan is
15 requests/minute, and a single real heal issues a BURST, diagnose, surgeon,
then verification across the train task plus every held-out task. Without a
limiter the burst trips the limit mid-run, and a trip mid-heal is the worst
possible time for it: the trace is half-written and the demo is on camera.

The limiter is deliberately dumb and honest about what it does NOT protect:
it paces THIS process only. It cannot see other processes, and it does not
back off on a 429, see medic/llm.py, which owns that.

  MEDIC_RATE_RPM      requests per minute (default 15, the free-plan limit)
  MEDIC_RATE_RPM_<P>  per-provider override, e.g. MEDIC_RATE_RPM_GROQ=30
"""
from __future__ import annotations

import os
import threading
import time
from collections import deque


class RateLimiter:
    """Sliding-window limiter, safe for threads."""

    def __init__(self, rpm: int):
        self.max_calls = max(1, rpm)
        self.interval = 60.0 / self.max_calls
        self._calls: deque[float] = deque()
        self._lock = threading.Lock()

    def acquire(self) -> None:
        while True:
            with self._lock:
                now = time.monotonic()
                while self._calls and now - self._calls[0] >= 60.0:
                    self._calls.popleft()
                if len(self._calls) < self.max_calls:
                    self._calls.append(now)
                    return
                wait = 60.0 - (now - self._calls[0])
            # Sleep OUTSIDE the lock so one waiter cannot block the others.
            time.sleep(max(0.05, wait))

    max_calls: int = 60


_limiters: dict[str, RateLimiter] = {}
_lock = threading.Lock()


def limiter_for(provider: str) -> RateLimiter:
    """One limiter per provider, so a slow provider cannot stall the other."""
    with _lock:
        if provider not in _limiters:
            _limiters[provider] = RateLimiter(_rpm_for(provider))
        return _limiters[provider]


# Conservative defaults per provider. Free endpoints are tighter than paid
# ones, and a trip mid-heal leaves a half-written trace, so the default for an
# unknown free host is the stingiest one we know rather than a middle guess.
DEFAULT_RPM = {
    "nara": 15,        # free plan: 15 req/min
    "openrouter": 10,  # free models are aggressively rate limited
    "groq": 15,
}


def _rpm_for(provider: str) -> int:
    specific = os.environ.get(f"MEDIC_RATE_RPM_{provider.upper()}")
    if specific:
        try:
            return max(1, int(specific))
        except ValueError:
            pass
    env_default = os.environ.get("MEDIC_RATE_RPM")
    if env_default:
        try:
            return max(1, int(env_default))
        except ValueError:
            pass
    return DEFAULT_RPM.get(provider, 10)


def describe() -> dict:
    return {name: _rpm_for(name) for name in ("nara", "groq", "openrouter")}