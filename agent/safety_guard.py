"""Pre-Execution Security & Secret Firewall for Robin.

Inspects tool inputs, code blocks, memory updates, and terminal commands
to prevent:
  1. Secret / API token leakage into persistent storage, memory, or logs
  2. Execution of destructive system commands
  3. Accidental commits containing high-entropy keys or private certs
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Standard secret pattern matchers
SECRET_PATTERNS = [
    (re.compile(r"sk-[a-zA-Z0-9_-]{20,}"), "OpenAI/Anthropic API Key"),
    (re.compile(r"ghp_[a-zA-Z0-9]{36}"), "GitHub Personal Access Token"),
    (re.compile(r"gho_[a-zA-Z0-9]{36}"), "GitHub OAuth Access Token"),
    (re.compile(r"xox[baprs]-[0-9a-zA-Z]{10,48}"), "Slack Token"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "AWS Access Key ID"),
    (re.compile(r"-----BEGIN\s+(?:RSA|OPENSSH|DSA|EC)?\s*PRIVATE\s+KEY-----"), "Private RSA/SSH Key"),
    (re.compile(r"eyJ[a-zA-Z0-9_\-]{10,}\.eyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}"), "JWT / Bearer Token"),
]

# Highly dangerous/destructive commands that require hard blocks
DANGEROUS_COMMAND_PATTERNS = [
    (re.compile(r"\brm\s+-(?:[a-zA-Z]*[rf][a-zA-Z]*)\s+(?:/|/\*|~|~\*)(?:\s+|$)"), "Root or Home directory recursive wipe"),
    (re.compile(r"\bmkfs(?:\.[a-z0-9]+)?(?:\s+|$)"), "Filesystem format command"),
    (re.compile(r"\bdd\s+if=.*?of=(?:/dev/sd|/dev/nvme|/dev/disk)"), "Raw disk block overwrite"),
    (re.compile(r":\(\)\s*\{\s*:\s*\|\s*:\s*&\s*\}\s*;\s*:"), "Fork bomb pattern"),
    (re.compile(r"\bchmod\s+-(?:[a-zA-Z]*R[a-zA-Z]*)\s+777\s+/(?:\s+|$)"), "Dangerous recursive root permission opening"),
]


@dataclass
class SecurityScanResult:
    is_safe: bool
    risk_level: str  # "clean", "warning", "blocked"
    detected_secrets: List[Tuple[str, str]] = field(default_factory=list)  # (type, masked_value)
    blocked_reasons: List[str] = field(default_factory=list)
    sanitized_text: Optional[str] = None


class SafetyGuard:
    """Security firewall and secret analyzer for agent operations."""

    @staticmethod
    def calculate_shannon_entropy(data: str) -> float:
        """Calculate Shannon entropy to identify high-entropy random strings (e.g. keys/hashes)."""
        if not data:
            return 0.0
        entropy = 0.0
        length = len(data)
        frequencies: Dict[str, int] = {}
        for char in data:
            frequencies[char] = frequencies.get(char, 0) + 1
        for count in frequencies.values():
            p_x = count / length
            entropy -= p_x * math.log2(p_x)
        return entropy

    @classmethod
    def scan_secrets(cls, text: str) -> Tuple[bool, List[Tuple[str, str]], str]:
        """Scan text for known API keys, tokens, or private keys, returning sanitized copy."""
        if not text:
            return True, [], text

        detected: List[Tuple[str, str]] = []
        sanitized = text

        for pattern, secret_type in SECRET_PATTERNS:
            matches = pattern.findall(sanitized)
            for m in matches:
                masked = m[:4] + "..." + m[-4:] if len(m) > 8 else "[REDACTED]"
                detected.append((secret_type, masked))
                sanitized = sanitized.replace(m, "[REDACTED_SECRET]")

        is_safe = len(detected) == 0
        return is_safe, detected, sanitized

    @classmethod
    def check_command_safety(cls, command: str) -> SecurityScanResult:
        """Analyze shell command string for dangerous system commands."""
        if not command:
            return SecurityScanResult(is_safe=True, risk_level="clean")

        blocked_reasons: List[str] = []
        for pattern, desc in DANGEROUS_COMMAND_PATTERNS:
            if pattern.search(command):
                blocked_reasons.append(f"Blocked dangerous command pattern: {desc}")

        has_secrets, secrets, sanitized = cls.scan_secrets(command)

        if blocked_reasons:
            return SecurityScanResult(
                is_safe=False,
                risk_level="blocked",
                detected_secrets=secrets,
                blocked_reasons=blocked_reasons,
                sanitized_text=sanitized,
            )

        if not has_secrets:
            return SecurityScanResult(
                is_safe=True,
                risk_level="warning",
                detected_secrets=secrets,
                blocked_reasons=[],
                sanitized_text=sanitized,
            )

        return SecurityScanResult(
            is_safe=True,
            risk_level="clean",
            detected_secrets=[],
            blocked_reasons=[],
            sanitized_text=command,
        )

    @classmethod
    def sanitize_for_persistence(cls, data: Any) -> Any:
        """Deep sanitize dictionaries, lists, or strings before storing to disk/memory."""
        if isinstance(data, str):
            _, _, clean_text = cls.scan_secrets(data)
            return clean_text
        if isinstance(data, dict):
            return {k: cls.sanitize_for_persistence(v) for k, v in data.items()}
        if isinstance(data, list):
            return [cls.sanitize_for_persistence(item) for item in data]
        return data
