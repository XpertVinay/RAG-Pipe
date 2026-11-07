"""Security module providing Anonymous Proxy Scrubbing and SSRF protection for third-party MCP calls."""

import hashlib
import ipaddress
import re
from typing import Any, Dict, List, Optional, Union
from urllib.parse import urlparse

from app.core.logging import logger


class AnonymousScrubber:
    """Anonymizes prompts, parameters, and metadata sent to external third-party MCP servers.

    Ensures zero PII (Personally Identifiable Information), secret keys, internal IP addresses,
    and user identity leakage to external tool providers.
    """

    # Sensitive patterns
    EMAIL_REGEX = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")
    IPV4_REGEX = re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")
    API_KEY_PATTERNS = [
        re.compile(r"sk-[a-zA-Z0-9_-]{20,}", re.IGNORECASE),          # OpenAI / generic
        re.compile(r"ghp_[a-zA-Z0-9]{30,}", re.IGNORECASE),          # GitHub personal token
        re.compile(r"AKIA[0-9A-Z]{16}", re.IGNORECASE),               # AWS Access Key ID
        re.compile(r"rzp_(?:test|live)_[a-zA-Z0-9]{14,}", re.IGNORECASE),  # Razorpay
        re.compile(r"AIza[0-9A-Za-z-_]{35}", re.IGNORECASE),          # Google API Key
        re.compile(r"Bearer\s+[a-zA-Z0-9\-._~+/]+=*", re.IGNORECASE),  # JWT / Bearer
    ]
    JWT_REGEX = re.compile(r"eyJ[a-zA-Z0-9-_]+\.eyJ[a-zA-Z0-9-_]+\.[a-zA-Z0-9-_]+")
    PATH_PATTERNS = [
        re.compile(r"/(?:Users|home)/[a-zA-Z0-9_-]+(?:/[a-zA-Z0-9_.-]+)*"),
        re.compile(r"[A-Z]:\\[Users|Documents]+(?:\\[a-zA-Z0-9_.-]+)*", re.IGNORECASE),
    ]

    @classmethod
    def anonymize_text(cls, text: str, salt: Optional[str] = "anon_agent") -> str:
        """Strip PII, system paths, internal tokens, and credentials from a string."""
        if not text or not isinstance(text, str):
            return text

        scrubbed = text

        # 1. Redact API keys and Tokens
        for pattern in cls.API_KEY_PATTERNS:
            scrubbed = pattern.sub("[REDACTED_API_KEY]", scrubbed)

        scrubbed = cls.JWT_REGEX.sub("[REDACTED_JWT_TOKEN]", scrubbed)

        # 2. Anonymize Emails
        def _replace_email(match):
            email = match.group(0)
            hash_suffix = hashlib.sha256(f"{email}_{salt}".encode()).hexdigest()[:6]
            return f"anonymous_user_{hash_suffix}@proxy.internal"

        scrubbed = cls.EMAIL_REGEX.sub(_replace_email, scrubbed)

        # 3. Anonymize IPs (ignore standard loopback/safe strings)
        def _replace_ip(match):
            ip_str = match.group(0)
            try:
                ip = ipaddress.ip_address(ip_str)
                if ip.is_private or ip.is_loopback:
                    return "10.0.0.0"
                return f"198.51.100.{hash(ip_str) % 250 + 1}"
            except ValueError:
                return ip_str

        scrubbed = cls.IPV4_REGEX.sub(_replace_ip, scrubbed)

        # 4. Normalize file paths to generic workspace paths
        for path_pat in cls.PATH_PATTERNS:
            scrubbed = path_pat.sub("/workspace/project", scrubbed)

        return scrubbed

    @classmethod
    def anonymize_payload(cls, data: Any) -> Any:
        """Recursively scrub dictionaries, lists, and strings for safe anonymous transmission."""
        if isinstance(data, str):
            return cls.anonymize_text(data)
        elif isinstance(data, dict):
            scrubbed_dict = {}
            for k, v in data.items():
                k_lower = str(k).lower()
                # Redact keys holding credentials or user identities
                if any(sec in k_lower for sec in ("auth", "password", "secret", "token", "api_key", "cookie")):
                    scrubbed_dict[k] = "[REDACTED_SECRET]"
                elif any(ident in k_lower for ident in ("user_id", "email", "username", "client_ip")):
                    val_str = str(v)
                    h = hashlib.sha256(val_str.encode()).hexdigest()[:8]
                    scrubbed_dict[k] = f"anon_{h}"
                else:
                    scrubbed_dict[k] = cls.anonymize_payload(v)
            return scrubbed_dict
        elif isinstance(data, list):
            return [cls.anonymize_payload(item) for item in data]
        return data

    @classmethod
    def generate_anonymous_session_id(cls, real_id: Optional[str] = None) -> str:
        """Generate an anonymous ephemeral session identifier."""
        seed = real_id or "anonymous"
        h = hashlib.sha256(f"{seed}_mcp_session".encode()).hexdigest()[:12]
        return f"anon_session_{h}"


class SSRFProtector:
    """Validates third-party URLs to prevent Server-Side Request Forgery attacks."""

    BLOCKED_NETWORKS = [
        ipaddress.ip_network("127.0.0.0/8"),      # Loopback
        ipaddress.ip_network("10.0.0.0/8"),       # Private RFC1918
        ipaddress.ip_network("172.16.0.0/12"),    # Private RFC1918
        ipaddress.ip_network("192.168.0.0/16"),   # Private RFC1918
        ipaddress.ip_network("169.254.0.0/16"),   # Link-Local / Cloud Metadata
        ipaddress.ip_network("0.0.0.0/8"),        # Current network
    ]

    @classmethod
    def validate_url(cls, url: str, allow_local_for_dev: bool = True) -> bool:
        """Validate if target URL is safe for outbound communication."""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                logger.warning(f"SSRF Check: Rejected invalid scheme '{parsed.scheme}' in {url}")
                return False

            hostname = parsed.hostname
            if not hostname:
                return False

            # If dev mode allows local docker or localhost
            if allow_local_for_dev:
                if hostname in ("localhost", "127.0.0.1", "host.docker.internal"):
                    return True

            # Attempt to resolve IP address
            try:
                ip = ipaddress.ip_address(hostname)
                for net in cls.BLOCKED_NETWORKS:
                    if ip in net and not allow_local_for_dev:
                        logger.warning(f"SSRF Check: Target IP {ip} is inside blocked network {net}")
                        return False
            except ValueError:
                # Hostname is a domain name (e.g. api.github.com), which is valid
                pass

            return True
        except Exception as e:
            logger.warning(f"SSRF validation exception for '{url}': {e}")
            return False
