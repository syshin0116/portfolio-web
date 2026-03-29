"""Request logging middleware."""

import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Log every HTTP request with method, path, status, and duration."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", uuid.uuid4().hex[:8])
        start = time.perf_counter()

        # Attach request_id for downstream loggers
        request.state.request_id = request_id

        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "[%s] %s %s → 500 (%.1fms)",
                request_id,
                request.method,
                request.url.path,
                duration_ms,
                exc_info=True,
            )
            raise

        duration_ms = (time.perf_counter() - start) * 1000
        log_fn = logger.warning if response.status_code >= 400 else logger.info
        log_fn(
            "[%s] %s %s → %d (%.1fms)",
            request_id,
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
        )

        response.headers["X-Request-ID"] = request_id
        return response
