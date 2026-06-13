from collections.abc import Callable
from time import sleep
from typing import TypeVar

T = TypeVar("T")


class RetryError(RuntimeError):
    pass


def retry_call(
    operation: Callable[[], T],
    *,
    attempts: int = 3,
    delay_seconds: float = 0.1,
    retry_exceptions: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except retry_exceptions as exc:
            last_error = exc
            if attempt == attempts:
                break
            sleep(delay_seconds)
    raise RetryError(f"operation failed after {attempts} attempts") from last_error
