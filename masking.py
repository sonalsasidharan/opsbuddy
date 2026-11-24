"""Redact secrets and personal data before text is shown or sent to an LLM.

Best effort, not a guarantee: regexes can't know every secret format. Treat the
preview as the real safety check, and skip Analyze when logs hold anything sensitive.
mask() returns (masked_text, {category: count}).
"""
import re

_REDACT = "***REDACTED***"
_KEY_NAMES = r"(?:password|passwd|pwd|secret|token|api[_-]?key|apikey|access[_-]?key|private[_-]?key|authorization|credential|client[_-]?secret)"


def _luhn_ok(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = int(ch)
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _high_entropy(m: re.Match) -> str:
    s = m.group(0)
    # Needs letters and digits mixed; skips plain words and plain numbers.
    if re.search(r"[A-Za-z]", s) and re.search(r"\d", s):
        return "[TOKEN REDACTED]"
    return s


# (category, compiled regex, replacement string or function). Order matters.
_RULES = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?(?:-----END [A-Z ]*PRIVATE KEY-----|$)"), "[PRIVATE KEY REDACTED]"),
    ("url credentials", re.compile(r"(\b[a-z][a-z0-9+.\-]*://)[^/\s:@]+:[^/\s@]+@", re.I), r"\1***:***@"),
    ("cloud key", re.compile(r"\b(?:AKIA|ASIA|AGPA|AIDA|AROA|ANPA)[A-Z0-9]{16}\b"), "[AWS KEY REDACTED]"),
    ("api token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}|sk-[A-Za-z0-9_\-]{20,}|xox[baprs]-[A-Za-z0-9\-]{10,}|AIza[0-9A-Za-z_\-]{30,})\b"), "[API TOKEN REDACTED]"),
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\.[A-Za-z0-9_\-]{5,}\b"), "[JWT REDACTED]"),
    ("bearer/basic auth", re.compile(r"\b(Bearer|Basic)\s+(?!\*\*\*)[A-Za-z0-9\-._~+/]{6,}=*", re.I), r"\1 " + _REDACT),
    # key=value, key: value, "key": "value", with quoted values that may contain spaces
    ("secret value", re.compile(
        r"(?i)([\"']?[\w.\-]*" + _KEY_NAMES + r"[\w.\-]*[\"']?\s*[:=]\s*)(?!(?:Bearer|Basic)\s)(?!\*\*\*)(\"[^\"]*\"|'[^']*'|[^\s,;&}\]\"']+)"),
        lambda m: m.group(1) + (f'"{_REDACT}"' if m.group(2)[:1] in "\"'" else _REDACT)),
    ("email", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)*\.[A-Za-z]{2,}\b"), "[EMAIL REDACTED]"),
    ("card number", re.compile(r"\b(?:\d[ -]?){13,19}\b"),
        lambda m: "[CARD REDACTED]" if _luhn_ok(re.sub(r"\D", "", m.group(0))) and 13 <= len(re.sub(r"\D", "", m.group(0))) <= 19 else m.group(0)),
    ("long token", re.compile(r"\b[A-Za-z0-9+/_\-]{32,}={0,2}"), _high_entropy),
]


def mask(text: str) -> tuple[str, dict]:
    report: dict = {}
    for name, pattern, repl in _RULES:
        count = 0

        def _sub(m, repl=repl):
            nonlocal count
            out = repl(m) if callable(repl) else m.expand(repl)
            if out != m.group(0):
                count += 1
            return out

        text = pattern.sub(_sub, text)
        if count:
            report[name] = count
    return text, report


def mask_text(text: str) -> str:
    return mask(text)[0]
