"""Tool environment used by agents."""

import json

from .types import QuantTool


class ToolEnvironment:
    """Registry and execution boundary for agent tools."""

    def __init__(self, tools):
        self._tools = {}
        for tool in tools:
            if tool.spec.name in self._tools:
                raise ValueError("duplicate tool: {0}".format(tool.spec.name))
            self._tools[tool.spec.name] = tool

    @property
    def tools(self):
        return list(self._tools.values())

    def run(self, name, arguments):
        tool = self._tools.get(name)
        if tool is None:
            raise ValueError("unknown tool: {0}".format(name))
        return tool.run(arguments)

    def describe(self):
        lines = []
        for tool in self.tools:
            lines.append(
                "- {0}: {1}\n  input_schema: {2}".format(
                    tool.spec.name,
                    tool.spec.description,
                    json.dumps(tool.spec.input_schema, ensure_ascii=False, sort_keys=True),
                )
            )
        return "\n".join(lines)


def make_tool_environment(tools):
    return ToolEnvironment(tools)
