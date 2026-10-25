"""Security filter and secret detection/redaction for the JARVIS memory subsystem."""

import re

# Comprehensive regex patterns for detecting secrets, tokens, keys, and credentials
_SECRET_PATTERNS = [
    # Google AI Studio / Gemini API keys (e.g. AIzaSy...)
    (re.compile(r"AIzaSy[A-Za-z0-9_\-]{33}"), "[REDACTED_GEMINI_KEY]"),
    # General secret keys (e.g. sk-..., secret-..., token-...)
    (re.compile(r"(?:sk|ghp|gho|glpat|xoxb|xoxp)-[A-Za-z0-9_\-]{20,}"), "[REDACTED_KEY]"),
    # Explicit test secrets or generic SECRET_ uppercase tokens
    (re.compile(r"(?i)SECRET_[A-Z0-9_\-]{3,}"), "[REDACTED_SECRET]"),
    # Bearer authentication tokens
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-\.]{15,}"), "Bearer [REDACTED_TOKEN]"),
    # Key-value secret assignments: api_key=..., password=..., secret=...
    (
        re.compile(
            r"(?i)(api[_-]?key|password|secret|token|auth[_-]?token|client[_-]?secret)\s*[:=]\s*['\"]?([A-Za-z0-9_\-\.]{4,})['\"]?"
        ),
        r"\1=[REDACTED_CREDENTIAL]",
    ),
]


def contains_secrets(text: str) -> bool:
    """Return True if any known secret or credential pattern is detected."""
    if not text:
        return False
    return any(pattern.search(text) is not None for pattern, _ in _SECRET_PATTERNS)


def redact_secrets(text: str) -> str:
    """Redact detected API keys, credentials, passwords, and secrets from text."""
    if not text:
        return ""

    sanitized = text
    for pattern, replacement in _SECRET_PATTERNS:
        sanitized = pattern.sub(replacement, sanitized)

    return sanitized
