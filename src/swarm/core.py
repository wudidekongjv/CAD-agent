"""Swarm 运行时核心：Agent + Tools + Handoffs

核心思想（轻量 Agent 循环的五个原语）：
1. LLM 接口
2. 工具注册表
3. Agent 循环：reason → tool_calls → observe → repeat
4. Handoff：工具调用返回另一个 Agent 即为移交，跳出当前循环
5. Swarm：读取 handoff，切换到新 Agent 继续执行

与固定流水线的区别：
- 固定流水线：节点顺序预设，条件边在有限分支中选择
- Swarm：Agent 自主决定调用工具或移交控制权，拓扑是运行时涌现的
"""

import json
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set

from .config import config
from .llm import LocalLLM, get_llm


@dataclass
class Agent:
    """Agent 定义：指令 + 可用工具 + 可移交目标"""
    name: str
    instructions: str
    tools: List[Dict] = field(default_factory=list)
    tool_functions: Dict[str, Callable] = field(default_factory=dict)
    handoffs: List["Agent"] = field(default_factory=list)
    model: Optional[str] = None

    def describe(self) -> str:
        return f"{self.name}: {self.instructions[:100]}..."


@dataclass
class RunResult:
    """运行结果的强类型封装"""
    agent: Agent
    messages: List[Dict[str, Any]]
    handoffs: List[str] = field(default_factory=list)
    turns: int = 0
    final_output: str = ""
    error: str = ""
    degraded: bool = False   # 部分失败但继续（失败是数据，不是异常）

    @property
    def last_message(self) -> str:
        for m in reversed(self.messages):
            if m.get("role") == "assistant" and m.get("content"):
                return m["content"]
        return ""


def _tool_to_schema(fn: Callable) -> Dict:
    """从函数签名与 docstring 生成工具 schema（简化版）"""
    import inspect
    sig = inspect.signature(fn)
    properties = {}
    for name, param in sig.parameters.items():
        annotation = param.annotation
        type_name = "string"
        if annotation in (int, float):
            type_name = "number"
        elif annotation is bool:
            type_name = "boolean"
        elif annotation in (list, List):
            type_name = "array"
        elif annotation in (dict, Dict):
            type_name = "object"
        properties[name] = {
            "type": type_name,
            "description": f"参数 {name}",
        }
    return {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": (fn.__doc__ or "").strip().split("\n")[0],
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": [n for n, p in sig.parameters.items()
                             if p.default == inspect.Parameter.empty],
            },
        },
    }


def make_tool(fn: Callable) -> Dict:
    """将 Python 函数注册为工具"""
    return _tool_to_schema(fn)


class Swarm:
    """Swarm 运行时：驱动 Agent 循环与 handoff 路由"""

    def __init__(self, llm: Optional[LocalLLM] = None):
        self.llm = llm or get_llm()

    def run(
        self,
        agent: Agent,
        messages: List[Dict[str, Any]],
        context: Optional[Dict[str, Any]] = None,
        max_turns: Optional[int] = None,
    ) -> RunResult:
        """运行 Agent 循环，直到给出最终答案或发生 handoff"""
        config.check_kill_switch()
        turns = 0
        limit = max_turns or config.max_turns
        handoffs: List[str] = []
        current = agent
        working = list(messages)
        ctx = context or {}
        pending_agent: Optional[Agent] = None

        while turns < limit:
            turns += 1
            config.check_kill_switch()

            # 注入系统指令（含上下文摘要）
            system_content = current.instructions
            if ctx:
                system_content += "\n\n## 当前上下文\n" + json.dumps(ctx, ensure_ascii=False, indent=2)[:4000]

            full_messages = [{"role": "system", "content": system_content}] + working

            # 调用本地 LLM
            try:
                response = self.llm.chat(
                    messages=full_messages,
                    tools=current.tools if current.tools else None,
                )
            except Exception as e:
                return RunResult(
                    agent=current, messages=working, turns=turns,
                    error=str(e), degraded=True,
                )

            # 无工具调用 → 最终答案
            tool_calls = response.get("tool_calls") or []
            if not tool_calls:
                working.append({
                    "role": "assistant",
                    "content": response.get("content", ""),
                })
                return RunResult(
                    agent=current, messages=working, turns=turns,
                    handoffs=handoffs, final_output=response.get("content", ""),
                )

            # 有工具调用 → 执行
            working.append({
                "role": "assistant",
                "content": response.get("content", ""),
                "tool_calls": tool_calls,
            })

            handed_off = False
            errors = []

            for call in tool_calls:
                fn_name = call["function"]["name"]
                try:
                    args = json.loads(call["function"].get("arguments", "{}"))
                except json.JSONDecodeError:
                    args = {}

                # Handoff 判定：工具名匹配 transfer_to_*
                if fn_name.startswith("transfer_to_"):
                    target_name = fn_name.replace("transfer_to_", "")
                    target = next((a for a in current.handoffs if a.name == target_name), None)
                    if target:
                        handoffs.append(f"{current.name}->{target.name}")
                        pending_agent = target
                        handed_off = True
                        working.append({
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": f"Handing control to {target.name}",
                        })
                        break  # handoff 跳出当前循环
                    else:
                        errors.append(f"Unknown handoff target: {target_name}")

                # 普通工具调用
                elif fn_name in current.tool_functions:
                    try:
                        result = current.tool_functions[fn_name](**args)
                        working.append({
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps(result, ensure_ascii=False, default=str),
                        })
                    except Exception as e:
                        errors.append(f"{fn_name}: {e}")
                        working.append({
                            "role": "tool",
                            "tool_call_id": call["id"],
                            "content": json.dumps({"error": str(e)}, ensure_ascii=False),
                        })
                else:
                    errors.append(f"Unknown tool: {fn_name}")

            # Handoff → 切换 Agent
            if handed_off and pending_agent:
                current = pending_agent
                pending_agent = None
                # 把历史压缩为交接摘要（避免上下文膨胀）
                working = [
                    {"role": "system", "content": f"Handoff from previous agent. Errors so far: {errors}"},
                    {"role": "user", "content": json.dumps({
                        "original_request": ctx.get("user_request", ""),
                        "progress": ctx.get("progress", []),
                    }, ensure_ascii=False)},
                ]
                continue

            # 记录错误到上下文（失败是数据）
            if errors:
                ctx.setdefault("errors", []).extend(errors)

        # 超过轮次上限
        return RunResult(
            agent=current, messages=working, handoffs=handoffs, turns=turns,
            degraded=True, error=f"Max turns ({limit}) reached",
            final_output=working[-1].get("content", "") if working else "",
        )
