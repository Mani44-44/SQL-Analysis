"""Versioned prompt files.

Each prompt is a Markdown file in this directory that starts with a front-matter header:

    ---
    name: generate_sql
    version: 1
    ---
    <prompt text, may contain {placeholders}>

The pair `name@version` is recorded on every query run and eval run.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Prompt:
    name: str
    version: str
    text: str

    @property
    def tag(self) -> str:
        return f"{self.name}@v{self.version}"

    def render(self, **kwargs: str) -> str:
        out = self.text
        for key, value in kwargs.items():
            out = out.replace("{" + key + "}", value)
        return out


@lru_cache
def load_prompt(name: str) -> Prompt:
    path = PROMPTS_DIR / f"{name}.md"
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---"):
        raise ValueError(f"prompt {name} is missing its front-matter header")
    _, header, body = raw.split("---", 2)
    meta = {}
    for line in header.strip().splitlines():
        key, _, value = line.partition(":")
        meta[key.strip()] = value.strip()
    if meta.get("name") != name or "version" not in meta:
        raise ValueError(f"prompt {name} has an invalid header")
    return Prompt(name=name, version=meta["version"], text=body.strip() + "\n")
