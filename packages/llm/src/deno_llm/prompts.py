"""Versioned prompt registry. One YAML file per prompt in ``deno_llm/prompts/``:

    id: analyst.pain
    version: 3
    system: |
      ...
    user: |
      ... {variables} ...
    examples:            # optional few-shot pairs, rendered before the user turn
      - user: "..."
        assistant: "..."

The id and version travel in each call's metadata, so every trace/log/usage row names the prompt.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig

PROMPT_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    id: str
    version: int
    system: str
    user: str
    examples: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def metadata(self) -> dict[str, Any]:
        return {"prompt_id": self.id, "prompt_version": self.version}

    def messages(self, **variables: Any) -> list[BaseMessage]:
        """Render with ``str.format``-style variables. Values are inserted verbatim, never re-parsed."""
        out: list[BaseMessage] = [SystemMessage(self.system.format(**variables))]
        for user, assistant in self.examples:
            out += [HumanMessage(user), AIMessage(assistant)]
        out.append(HumanMessage(self.user.format(**variables)))
        return out

    def config(self, **extra: Any) -> RunnableConfig:
        return {"metadata": {**self.metadata, **extra}, "run_name": self.id}


class PromptNotFound(KeyError):
    pass


def _load(path: Path) -> Prompt:
    raw = yaml.safe_load(path.read_text())
    return Prompt(
        id=str(raw["id"]),
        version=int(raw["version"]),
        system=str(raw["system"]).strip(),
        user=str(raw["user"]).strip(),
        examples=tuple((str(e["user"]), str(e["assistant"])) for e in raw.get("examples") or ()),
    )


@cache
def registry(directory: Path = PROMPT_DIR) -> dict[str, Prompt]:
    prompts: dict[str, Prompt] = {}
    for path in sorted(directory.glob("*.yaml")):
        prompt = _load(path)
        if prompt.id in prompts:
            raise ValueError(f"duplicate prompt id {prompt.id}")
        prompts[prompt.id] = prompt
    return prompts


def get_prompt(prompt_id: str, directory: Path = PROMPT_DIR) -> Prompt:
    try:
        return registry(directory)[prompt_id]
    except KeyError:
        raise PromptNotFound(prompt_id) from None
