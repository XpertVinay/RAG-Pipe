"""Identity-aware in-memory sliding window rate limiter for FastAPI endpoints."""

import re
import time
from collections import defaultdict
from typing import Dict, List, Tuple
from fastapi import HTTPException, Request, status

# Regex for validating device tokens (alphanumeric, hyphens, underscores, dots; 8-64 chars)
DEVICE_ID_REGEX = re.compile(r"^[a-zA-Z0-9_\-\.]{8,64}$")


class RateLimiter:
    """Identity-Aware Sliding-Window In-Memory Rate Limiter.

    Solves the Corporate VPN / Shared NAT IP problem:
    - Prioritizes Verified User ID (JWT Authorization Bearer)
    - Follows with Verified Digital Device Token (X-Device-ID header or cookie)
    - Falls back to Client IP only for anonymous/unverified requests.

    Includes a coarse outer Volumetric IP Circuit Breaker to prevent brute-force
    header spoofing from a single attacking IP address while letting all verified
    corporate employees on a shared VPN work without interference.
    """

    def __init__(
        self,
        max_requests: int = 20,
        window_seconds: int = 60,
        max_ip_multiplier: int = 15,
        min_ip_burst: int = 150,
    ):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        # Outer IP threshold allows multiple verified enterprise users on one NAT
        # while cutting off automated script floods rotating random device IDs
        self.max_ip_requests = max(max_requests * max_ip_multiplier, min_ip_burst)

        # Primary identity buckets: identity_key -> [timestamps]
        self._clients: Dict[str, List[float]] = defaultdict(list)
        # Outer IP flood breaker: client_ip -> [timestamps]
        self._ip_buckets: Dict[str, List[float]] = defaultdict(list)

    def _resolve_identity(self, request: Request) -> Tuple[str, str]:
        """Resolve (identity_key, client_ip) with verified precedence."""
        raw_headers = getattr(request, "headers", None) or {}
        cookies = getattr(request, "cookies", None) or {}
        client = getattr(request, "client", None)

        def get_header(key: str) -> str:
            if hasattr(raw_headers, "get"):
                val = raw_headers.get(key)
                if val is not None:
                    return str(val)
                val = raw_headers.get(key.lower())
                if val is not None:
                    return str(val)
                if hasattr(raw_headers, "items"):
                    k_lower = key.lower()
                    for k, v in raw_headers.items():
                        if k.lower() == k_lower:
                            return str(v)
            return ""

        # 1. Resolve raw client IP
        client_ip = (
            get_header("cf-connecting-ip")
            or get_header("x-forwarded-for").split(",")[0].strip()
            or get_header("x-real-ip")
            or (client.host if client and hasattr(client, "host") else "unknown")
        )

        # 2. Check for Authenticated User (JWT Token)
        auth_header = get_header("authorization").strip()
        if auth_header.startswith("Bearer "):
            raw_token = auth_header[7:].strip()
            if raw_token:
                parts = raw_token.split(".")
                if len(parts) == 3:
                    # Bind to authenticated token signature segment
                    return f"user:{parts[2][:24]}", client_ip
                return f"token:{raw_token[:32]}", client_ip

        # 3. Check for Verified Digital Device Token / Fingerprint
        device_id = get_header("x-device-id") or (cookies.get("rag_device_id") if hasattr(cookies, "get") else "")
        if device_id and isinstance(device_id, str):
            device_id = device_id.strip()
            if DEVICE_ID_REGEX.match(device_id):
                fp = get_header("x-device-fingerprint") or ""
                fp_suffix = f":{fp.strip()[:16]}" if (fp and isinstance(fp, str)) else ""
                return f"dev:{device_id}{fp_suffix}", client_ip

        # 4. Fallback to raw client IP for anonymous/unverified clients
        return f"ip:{client_ip}", client_ip

    def __call__(self, request: Request) -> None:
        identity_key, client_ip = self._resolve_identity(request)
        now = time.time()
        window_start = now - self.window_seconds

        # --- A. Outer Volumetric IP Circuit Breaker ---
        if client_ip != "unknown":
            ip_timestamps = [t for t in self._ip_buckets[client_ip] if t > window_start]
            self._ip_buckets[client_ip] = ip_timestamps
            if len(ip_timestamps) >= self.max_ip_requests:
                retry_after = int(self.window_seconds - (now - ip_timestamps[0])) + 1
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=f"Network volumetric traffic ceiling reached. Try again in {retry_after}s.",
                    headers={
                        "Retry-After": str(max(1, retry_after)),
                        "X-RateLimit-Scope": "ip-breaker",
                    },
                )

        # --- B. Granular Identity Bucket (User / Verified Device) ---
        timestamps = [t for t in self._clients[identity_key] if t > window_start]
        self._clients[identity_key] = timestamps

        if len(timestamps) >= self.max_requests:
            retry_after = int(self.window_seconds - (now - timestamps[0])) + 1
            scope = (
                "user"
                if identity_key.startswith("user:") or identity_key.startswith("token:")
                else ("device" if identity_key.startswith("dev:") else "ip")
            )
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded for this {scope}. Try again in {retry_after} seconds.",
                headers={
                    "Retry-After": str(max(1, retry_after)),
                    "X-RateLimit-Limit": str(self.max_requests),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(int(now + retry_after)),
                    "X-RateLimit-Scope": scope,
                },
            )

        # Record request
        self._clients[identity_key].append(now)
        if client_ip != "unknown":
            self._ip_buckets[client_ip].append(now)

    def reset(self) -> None:
        """Reset internal rate limit tracking (useful for unit tests)."""
        self._clients.clear()
        self._ip_buckets.clear()
