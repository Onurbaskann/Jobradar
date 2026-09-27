from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Lock

_lock = Lock()
_interactive_requests = 0


@contextmanager
def prioritize_interactive_model_call() -> Iterator[None]:
    """Arka plan işlerine kullanıcı tarafından başlatılmış model çağrısını bildirir."""
    global _interactive_requests
    with _lock:
        _interactive_requests += 1
    try:
        yield
    finally:
        with _lock:
            _interactive_requests -= 1


def interactive_model_call_pending() -> bool:
    with _lock:
        return _interactive_requests > 0
