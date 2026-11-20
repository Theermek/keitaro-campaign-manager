import threading
import time
from collections.abc import Callable
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLValue(Generic[T]):
    """A single lazily loaded value that is reloaded after `ttl` seconds."""

    def __init__(self, ttl: float):
        self._ttl = ttl
        self._lock = threading.Lock()
        self._value: T | None = None
        self._expires_at = 0.0

    def get(self, load: Callable[[], T]) -> T:
        with self._lock:
            if self._value is None or time.monotonic() >= self._expires_at:
                self._value = load()
                self._expires_at = time.monotonic() + self._ttl
            return self._value

    def clear(self) -> None:
        with self._lock:
            self._value = None
