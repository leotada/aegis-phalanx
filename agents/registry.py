from typing import Dict, Type

from agents.base import AgentCLI


class AgentRegistry:
    """Extensible factory for resolving agent instances without direct coupling."""

    _registry: Dict[str, Type[AgentCLI]] = {}

    @classmethod
    def register(cls, name: str, cli_class: Type[AgentCLI]) -> None:
        cls._registry[name] = cli_class

    @classmethod
    def get_agent(cls, name: str) -> AgentCLI:
        cli_class = cls._registry.get(name)
        if not cli_class:
            raise ValueError(f"Agent tool '{name}' is not registered.")
        return cli_class()
