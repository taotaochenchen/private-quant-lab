"""Tool contracts for agent execution."""

from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: Dict[str, Any]


@dataclass(frozen=True)
class ToolResult:
    name: str
    output: Dict[str, Any]


class QuantTool:
    """A callable tool with a JSON-like input and output contract."""

    def __init__(
        self,
        spec: ToolSpec,
        handler: Callable[[Dict[str, Any]], Dict[str, Any]],
        observation_mocker=None,
    ):
        self.spec = spec
        self._handler = handler
        self._observation_mocker = observation_mocker

    def run(self, arguments):
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be a JSON object")
        local_fallback = self._handler(arguments)
        if self._observation_mocker is None:
            return ToolResult(name=self.spec.name, output=local_fallback)
        return ToolResult(
            name=self.spec.name,
            output=self._observation_mocker.simulate(
                self.spec,
                arguments,
                local_fallback,
            ),
        )
