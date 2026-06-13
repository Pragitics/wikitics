from time import perf_counter
from uuid import uuid4

from fastapi import Request

from app.shared.metrics import metrics
from app.shared.request_context import set_request_id


async def request_context_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    set_request_id(request_id)
    start = perf_counter()
    metrics.increment("http.requests")
    try:
        response = await call_next(request)
        metrics.increment(f"http.responses.{response.status_code}")
        return response
    except Exception:
        metrics.increment("http.exceptions")
        raise
    finally:
        elapsed = perf_counter() - start
        metrics.observe("http.request_latency", elapsed)
        try:
            response.headers["X-Request-ID"] = request_id
        except UnboundLocalError:
            pass
