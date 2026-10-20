"""PII Detection, Breach Alerting, and Contextual Meaning Masking Service.

Detects sensitive PII (emails, phone numbers, API keys, passwords, SSN/IDs, financial numbers),
flags them as security/privacy breaches, and masks them with contextual explanations:
'(*****, [Context: meaning of the context])'. Also manages user consent for sharing.
"""

import re
from typing import Any, Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class PIIDetectionItem:
    """Individual PII breach detection with semantic context."""
    category: str
    original_snippet: str
    masked_representation: str
    context_meaning: str
    confidence: float
    start_pos: int
    end_pos: int


@dataclass
class PIIScanResult:
    """Full scan report detailing PII breaches and contextual masked content."""
    has_pii: bool
    breach_count: int
    original_text: str
    masked_text: str
    detections: List[PIIDetectionItem] = field(default_factory=list)
    risk_level: str = "low"  # "low", "medium", "high", "critical"
    alert_message: Optional[str] = None


class PIIService:
    """Enterprise-grade PII detection and contextual masking engine."""

    # Patterns for sensitive entities
    PATTERNS = [
        (
            "email",
            re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"),
            "Email Context: personal contact email address detected",
            "medium",
        ),
        (
            "phone",
            re.compile(
                r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b|"
                r"(?:\+91[-.\s]?)?[6789]\d{9}\b"
            ),
            "Phone Context: personal telephone contact number detected",
            "medium",
        ),
        (
            "credit_card",
            re.compile(r"\b(?:\d{4}[-\s]?){3}\d{4}\b|\b\d{15,16}\b"),
            "Financial Context: credit or debit payment card number detected",
            "critical",
        ),
        (
            "ssn_national_id",
            re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b\d{4}\s\d{4}\s\d{4}\b"),
            "Identity Context: government-issued national identity number (SSN / Aadhaar) detected",
            "critical",
        ),
        (
            "api_key_secret",
            re.compile(
                r"(?:sk-[a-zA-Z0-9_-]{20,}|ghp_[a-zA-Z0-9]{30,}|AKIA[0-9A-Z]{16}|"
                r"AIza[0-9A-Za-z-_]{35}|Bearer\s+[a-zA-Z0-9\-._~+/]+=*|"
                r"rzp_(?:test|live)_[a-zA-Z0-9]{14,}|client_secret[a-zA-Z0-9_-]{16,})",
                re.IGNORECASE,
            ),
            "Credential Context: sensitive API key, access token, or client secret detected",
            "critical",
        ),
        (
            "password",
            re.compile(r"(?:password|passwd|pwd)\s*[:=]\s*['\"]?([^\s'\"]{6,})['\"]?", re.IGNORECASE),
            "Security Context: plaintext password credential detected",
            "critical",
        ),
        (
            "jwt_token",
            re.compile(r"\beyJ[a-zA-Z0-9-_]+\.eyJ[a-zA-Z0-9-_]+\.[a-zA-Z0-9-_]+\b"),
            "Session Context: JSON Web Token authentication payload detected",
            "high",
        ),
        (
            "ip_address",
            re.compile(r"\b(?:10\.\d{1,3}|192\.168\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3})\.\d{1,3}\b"),
            "Network Context: internal private IP address infrastructure detected",
            "medium",
        ),
    ]

    @classmethod
    def scan_and_mask(cls, text: str) -> PIIScanResult:
        """Scan text for PII breaches and replace each occurrence with '(*****, [meaning of context])'."""
        if not text or not isinstance(text, str):
            return PIIScanResult(
                has_pii=False,
                breach_count=0,
                original_text=text or "",
                masked_text=text or "",
                detections=[],
                risk_level="low",
            )

        detections: List[PIIDetectionItem] = []
        replaced_text = text
        highest_risk = "low"
        risk_hierarchy = {"low": 0, "medium": 1, "high": 2, "critical": 3}

        # Track replacements by offsets to avoid nested overlaps
        spans_to_replace: List[Tuple[int, int, str, str, str, str]] = []

        for category, pattern, context_meaning, risk in cls.PATTERNS:
            for match in pattern.finditer(text):
                start, end = match.span()
                matched_str = match.group(0)

                # Special password handling: redact only the password value if grouped
                if category == "password" and match.groups():
                    pwd_val = match.group(1)
                    pwd_start = match.start(1)
                    pwd_end = match.end(1)
                    mask = f"(*****, [{context_meaning}])"
                    spans_to_replace.append((pwd_start, pwd_end, pwd_val, mask, category, context_meaning))
                else:
                    mask = f"(*****, [{context_meaning}])"
                    spans_to_replace.append((start, end, matched_str, mask, category, context_meaning))

                if risk_hierarchy.get(risk, 0) > risk_hierarchy.get(highest_risk, 0):
                    highest_risk = risk

        # Sort spans in reverse order to replace without invalidating previous string offsets
        spans_to_replace.sort(key=lambda s: s[0], reverse=True)

        # De-duplicate overlapping spans
        final_spans = []
        last_start = float("inf")
        for span in spans_to_replace:
            s_start, s_end, orig, mask, cat, meaning = span
            if s_end <= last_start:
                final_spans.append(span)
                last_start = s_start

        # Apply replacements
        masked_builder = list(text)
        for s_start, s_end, orig, mask, cat, meaning in final_spans:
            masked_builder[s_start:s_end] = list(mask)
            detections.append(
                PIIDetectionItem(
                    category=cat,
                    original_snippet=orig[:4] + "***" if len(orig) > 4 else "***",
                    masked_representation=mask,
                    context_meaning=meaning,
                    confidence=0.95,
                    start_pos=s_start,
                    end_pos=s_end,
                )
            )

        final_masked_text = "".join(masked_builder)
        has_pii = len(detections) > 0

        alert_message = None
        if has_pii:
            alert_message = (
                f"Privacy Breach Alert: Detected {len(detections)} instance(s) of sensitive personal data "
                f"({', '.join(sorted(set(d.category for d in detections)))}). "
                f"Data has been automatically masked with contextual descriptors to protect your privacy."
            )

        return PIIScanResult(
            has_pii=has_pii,
            breach_count=len(detections),
            original_text=text,
            masked_text=final_masked_text,
            detections=list(reversed(detections)),
            risk_level=highest_risk,
            alert_message=alert_message,
        )


pii_service = PIIService()
