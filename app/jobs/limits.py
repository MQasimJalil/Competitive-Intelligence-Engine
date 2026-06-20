from collections import defaultdict, deque
from threading import Lock
from time import monotonic


class JobStartLimiter:
    def __init__(self, *, window_seconds: int, max_per_window: int):
        self.window_seconds = window_seconds
        self.max_per_window = max_per_window
        self._starts: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    def allow(self, user_id: str) -> bool:
        if self.max_per_window <= 0:
            return True
        now = monotonic()
        with self._lock:
            starts = self._starts[user_id]
            while starts and now - starts[0] > self.window_seconds:
                starts.popleft()
            if len(starts) >= self.max_per_window:
                return False
            starts.append(now)
            return True

    def reset(self) -> None:
        with self._lock:
            self._starts.clear()
