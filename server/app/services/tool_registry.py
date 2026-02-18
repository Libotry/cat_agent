"""
Tool Use 框架 (M5.1)

注册工具定义 → agent_runner 调用 LLM 时传入 tools 参数 → LLM 返回 tool_call → 执行工具 → 返回结果
"""
import json
import logging
from dataclasses import dataclass
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: dict  # JSON Schema
    handler: Callable[..., Awaitable[dict]]  # async (arguments, context) -> dict


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolDefinition] = {}

    def register(self, tool: ToolDefinition):
        self._tools[tool.name] = tool

    def get_tools_for_llm(self) -> list[dict]:
        """返回 OpenAI function calling 格式的工具列表。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    async def execute(self, name: str, arguments: dict, context: dict) -> dict:
        """执行工具，返回结果。"""
        tool = self._tools.get(name)
        if not tool:
            return {"ok": False, "error": f"未知工具: {name}"}
        try:
            result = await tool.handler(arguments, context)
            return {"ok": True, "result": result}
        except Exception as e:
            logger.error("Tool %s execution failed: %s", name, e)
            return {"ok": False, "error": str(e)}


# --- transfer_resource 工具 ---

async def _handle_transfer_resource(arguments: dict, context: dict) -> dict:
    """transfer_resource 工具的 handler。from_agent_id 从 context 取，Agent 不能伪造身份。"""
    from .city_service import transfer_resource
    db = context["db"]
    from_agent_id = context["agent_id"]
    to_agent_id = arguments["to_agent_id"]
    resource_type = arguments["resource_type"]
    quantity = arguments["quantity"]
    return await transfer_resource(from_agent_id, to_agent_id, resource_type, quantity, db)


TRANSFER_RESOURCE_TOOL = ToolDefinition(
    name="transfer_resource",
    description="将自己的资源转赠给另一个居民",
    parameters={
        "type": "object",
        "properties": {
            "to_agent_id": {"type": "integer", "description": "接收方居民 ID"},
            "resource_type": {"type": "string", "description": "资源类型，如 flour"},
            "quantity": {"type": "number", "description": "转赠数量"},
        },
        "required": ["to_agent_id", "resource_type", "quantity"],
    },
    handler=_handle_transfer_resource,
)

# 全局单例
tool_registry = ToolRegistry()
tool_registry.register(TRANSFER_RESOURCE_TOOL)

# TODO: 假设所有模型支持 function calling，后续按需补降级逻辑
