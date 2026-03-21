import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass

from fastapi import HTTPException, status


@dataclass(frozen=True)
class RateLimitRule:
    name: str
    limit: int
    window_seconds: int


class InMemoryRateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, *, key: str, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        window_start = now - window_seconds
        with self._lock:
            events = self._events[key]
            while events and events[0] <= window_start:
                events.popleft()
            if len(events) >= limit:
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail={
                        "code": "RATE_LIMIT_EXCEEDED",
                        "message": "Too many requests, please retry later",
                    },
                )
            events.append(now)

    def enforce(self, *, key: str, limit: int, window_seconds: int) -> None:
        self.check(key=key, limit=limit, window_seconds=window_seconds)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()


rate_limiter = InMemoryRateLimiter()


def enforce_rate_limit(*, rule: RateLimitRule, subject: str) -> None:
    normalized_subject = subject.strip() or "anonymous"
    key = f"{rule.name}:{normalized_subject}"
    rate_limiter.check(key=key, limit=rule.limit, window_seconds=rule.window_seconds)
