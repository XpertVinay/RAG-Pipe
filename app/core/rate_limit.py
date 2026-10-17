"""In-memory sliding window rate limiter for FastAPI endpoints."""

import time
from collections import defaultdict
from typing import Dict, List
from fastapi import HTTPException, Request, status


class RateLimiter:
    """Sliding-window in-memory rate limiter dependency.

    Enforces a maximum number of requests within a sliding time window (in seconds)
    per client IP address.
    """

    def __init__(self, max_requests: int = 20, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._clients: Dict[str, List[float]] = defaultdict(list)

    def __call__(self, request: Request) -> None:
        client_ip = request.client.host if request.client else "unknown"
        now = time.time()
        window_start = now - self.window_seconds

        # Prune request timestamps older than the window
        timestamps = [t for t in self._clients[client_ip] if t > window_start]
        self._clients[client_ip] = timestamps

        if len(timestamps) >= self.max_requests:
            retry_after = int(self.window_seconds - (now - timestamps[0])) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Try again in {retry_after} seconds.",
                headers={"Retry-After": str(max(1, retry_after))},
            )

        self._clients[client_ip].append(now)

    def reset(self) -> None:
        """Reset internal rate limit tracking (useful for unit tests)."""
        self._clients.clear()
