from collections import defaultdict
from threading import Lock
from time import perf_counter
from typing import Callable, TypeVar

T = TypeVar("T")


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[str, int] = defaultdict(int)
        self._timings: dict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def observe(self, name: str, seconds: float) -> None:
        with self._lock:
            self._timings[name].append(seconds)

    def time(self, name: str, func: Callable[[], T]) -> T:
        start = perf_counter()
        try:
            return func()
        finally:
            self.observe(name, perf_counter() - start)

    def snapshot(self) -> dict:
        with self._lock:
            timings = {}
            for name, values in self._timings.items():
                count = len(values)
                total = sum(values)
                timings[name] = {
                    "count": count,
                    "total_seconds": total,
                    "avg_seconds": total / count if count else 0,
                    "max_seconds": max(values) if values else 0,
                }
            return {"counters": dict(self._counters), "timings": timings}

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._timings.clear()


metrics = MetricsRegistry()
