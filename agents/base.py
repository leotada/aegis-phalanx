from abc import ABC, abstractmethod
from typing import List


class AgentCLI(ABC):
    """Common abstraction for all AI Agent CLIs (Single Responsibility Principle)."""

    @abstractmethod
    def build_command(
        self,
        prompt: str,
        model: str,
        reasoning_budget: str,
        timeout: str = None,
        read_only: bool = False,
    ) -> List[str]:
        """Generates the terminal argument list to run the tool."""
        raise NotImplementedError  # pragma: no cover
