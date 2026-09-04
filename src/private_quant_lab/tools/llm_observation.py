"""LLM-backed mock observations for tools."""

import json
import re

from private_quant_lab.models import ChatMessage
from private_quant_lab.models.openai_compatible import ModelError, ModelRequestError


JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


class LLMObservationMocker:
    """Use a chat model to simulate tool observations.

    这个类只负责“模拟工具返回值”，不代表真的访问了行情、新闻、搜索或券商系统。
    它会要求模型按工具 schema 返回 JSON，方便 Agent 后续把 observation 继续喂回模型。
    """

    def __init__(self, model, max_tokens=700):
        self.model = model
        self.max_tokens = max_tokens

    def simulate(self, spec, arguments, local_fallback):
        """让模型根据工具定义和入参生成 mock observation。

        输入：
            spec: ToolSpec，包含工具名、功能描述和 input_schema。
            arguments: Agent 传给工具的 JSON 入参。
            local_fallback: 本地固定 mock 结果，用于提示输出字段，也用于失败兜底。

        输出：
            dict，包含模型模拟出来的 observation，并附带 observation_source 字段。
        """

        fallback = dict(local_fallback)
        try:
            response = self.model.complete(
                [
                    ChatMessage("system", _system_prompt()),
                    ChatMessage(
                        "user",
                        json.dumps(
                            {
                                "tool": {
                                    "name": spec.name,
                                    "description": spec.description,
                                    "input_schema": spec.input_schema,
                                },
                                "arguments": arguments,
                                "required_output_shape": fallback,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ),
                ],
                temperature=0,
                max_tokens=self.max_tokens,
            )
            output = _parse_json_object(response.content)
        except (ModelError, ValueError) as exc:
            output = dict(fallback)
            output["observation_source"] = "local_fallback"
            output["observation_error"] = str(exc)
            output.setdefault("mock", True)
            return output
        output.setdefault("mock", True)
        output["observation_source"] = "deepseek"
        return output


def _system_prompt():
    return (
        "You simulate tool observations for a quant research agent.\n"
        "Return exactly one JSON object. Do not include markdown, prose, Action, or Final.\n"
        "The JSON should look realistic and match the requested tool, but it is mocked data.\n"
        "Use required_output_shape as a field-shape guide, not as text to copy verbatim.\n"
        "For web_search, return search-like results with title, url, snippet, published_at when possible.\n"
        "Always include mock=true."
    )


def _parse_json_object(text):
    content = str(text or "").strip()
    block_match = JSON_BLOCK_RE.search(content)
    if block_match:
        content = block_match.group(1).strip()
    if not content:
        raise ModelRequestError("observation model returned empty content")
    try:
        value = json.loads(content)
    except ValueError as exc:
        raise ModelRequestError("observation model did not return valid JSON") from exc
    if not isinstance(value, dict):
        raise ModelRequestError("observation model must return a JSON object")
    return value
