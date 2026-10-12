import threading
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta


class LoginRateLimiter:
    def __init__(self, attempts: int, window_seconds: int) -> None:
        self.attempts = attempts
        self.window = timedelta(seconds=window_seconds)
        self._failures: dict[str, deque[datetime]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: datetime) -> deque[datetime]:
        failures = self._failures[key]
        while failures and now - failures[0] >= self.window:
            failures.popleft()
        return failures

    def retry_after(self, key: str) -> int | None:
        now = datetime.now(UTC)
        with self._lock:
            failures = self._prune(key, now)
            if len(failures) < self.attempts:
                return None
            return max(1, int((self.window - (now - failures[0])).total_seconds()))

    def record_failure(self, key: str) -> None:
        now = datetime.now(UTC)
        with self._lock:
            self._prune(key, now).append(now)

    def reset(self, key: str) -> None:
        with self._lock:
            self._failures.pop(key, None)
