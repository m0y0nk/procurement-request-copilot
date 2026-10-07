from __future__ import annotations

import re

INJECTION_PATTERNS = (
    re.compile(r"\bignore\b.{0,50}\b(rules|policy|instructions|controls)\b", re.IGNORECASE),
    re.compile(r"\b(disregard|override|bypass)\b.{0,50}\b(rules|policy|instructions|controls)\b", re.IGNORECASE),
    re.compile(r"\b(treat|consider)\b.{0,40}\b(cfo|manager|security|legal)\b.{0,30}\bapproved\b", re.IGNORECASE),
    re.compile(r"\bapprove\b.{0,30}\b(immediately|automatically|without review)\b", re.IGNORECASE),
    re.compile(r"\b(reveal|expose|print)\b.{0,30}\b(secret|credential|api key|system prompt)\b", re.IGNORECASE),
)


def scan_untrusted_texts(texts: list[str]) -> list[str]:
    findings: list[str] = []
    for index, text in enumerate(texts):
        if any(pattern.search(text) for pattern in INJECTION_PATTERNS):
            findings.append(f"untrusted_text_{index + 1}")
    return findings
