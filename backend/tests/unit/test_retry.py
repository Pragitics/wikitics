import pytest

from app.shared.retry import RetryError, retry_call


def test_retry_call_retries_until_success():
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 2:
            raise ValueError("not yet")
        return "ok"

    assert retry_call(flaky, attempts=3, delay_seconds=0) == "ok"
    assert attempts["count"] == 2


def test_retry_call_raises_after_exhaustion():
    with pytest.raises(RetryError):
        retry_call(lambda: (_ for _ in ()).throw(ValueError("fail")), attempts=2, delay_seconds=0)
