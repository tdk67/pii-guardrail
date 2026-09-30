"""State builder and prompt injection defense engine for Latch.

Ensures staged code additions are safely isolated inside explicit structural
delimiters (<code_diff_payload>) and that adversarial attempts to close
delimiters are sanitized.
"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Any, Optional
from latch.config import LatchConfig, get_config

DEFAULT_PROMPT_TEMPLATE = (
    "<code_diff_payload>\n"
    "{payload}\n"
    "</code_diff_payload>\n"
)


import re

INJECTION_DIRECTIVE_PATTERN = re.compile(
    r"(?i)(#|//|\*)\s*.*?(?:ignore\s+(?:all\s+)?(?:previous\s+)?instructions|system\s+override|override\s+system|bypass\s+mode|disregard\s+(?:all\s+)?(?:prior|previous)|do\s+not\s+flag|return\s+false\s+(?:verdict|for\s+pii|evaluation)|treat\s+as\s+clean).*"
)


def sanitize_payload(payload: str) -> str:
    """Sanitize code diff to prevent delimiter escape and prompt injection attacks."""
    sanitized = payload.replace("</code_diff_payload>", "&lt;/code_diff_payload&gt;")
    sanitized = sanitized.replace("<code_diff_payload>", "&lt;code_diff_payload&gt;")
    # Neutralize adversarial prompt injection attempts inside code comments
    sanitized = INJECTION_DIRECTIVE_PATTERN.sub(r"\1 [INJECTION_ATTEMPT_NEUTRALIZED]", sanitized)
    return sanitized


class StateBuilder:
    """Builds evaluation prompt payloads isolated from instruction space."""

    def __init__(
        self,
        config: Optional[LatchConfig] = None,
        template_path: Optional[str] = None,
    ) -> None:
        self.config = config or get_config()
        self.template_path = template_path or self.config.noul_prompt_template_path
        self._template: Optional[str] = None

    def _load_template(self) -> str:
        if self._template is not None:
            return self._template

        if self.template_path and os.path.exists(self.template_path):
            try:
                with open(self.template_path, "r", encoding="utf-8") as f:
                    self._template = f.read()
                    return self._template
            except Exception:
                pass

        self._template = DEFAULT_PROMPT_TEMPLATE
        return self._template

    def build(self, raw_code: str) -> str:
        """Sanitizes raw code additions and binds into delimiter template."""
        clean_code = sanitize_payload(raw_code)
        template = self._load_template()
        return template.format(payload=clean_code)
