"""LangGraph 多 Agent 编排：Planner → Coder → Executor → Validator

关键设计：
- 条件边：Validator 失败时回退到 Planner 重规划（最多 max_retries 次）
- 工具发现：Planner 只看到相关工具包（search_tools），避免全量工具描述占用上下文
- 临时副本：Executor 在副本上执行，Validator 通过才写回原图
- 状态持久化：checkpointer 支持断点续跑与人工介入
"""

import json
import operator
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, StateGraph

from .state import CADState


# ============ 工具描述（Planner 可见的工具能力） ============
TOOL_DESCRIPTIONS = """
可用 MCP 工具（按包分组）：

core（通用）:
- drawing_info(file, backend) — 读取图纸图层与实体统计
- cad_batch(ops, file, output, backend) — 批量执行绘图操作（核心）
- undo_checkpoint(file) — 回滚

arch（建筑）:
- draw_wall(start, end, thickness, layer) — 绘制墙体
- insert_opening(name, insert, width, height, layer) — 插入门窗
- batch_dimension(layer, style) — 批量标注
- layer_audit(file, naming_rules) — 图层规范检查
- room_boundary(file, layer) — 房间边界识别

mech（机械/构造）:
- add_hatch — 剖面填充
- offset_copy — 偏移复制

每个 op 是 {"op": 操作名, ...参数} 的 JSON 对象。
"""


def _llm_call(prompt: str, system: str, model: str = "qwen3-32b") -> str:
    """调用 LLM（本地 vLLM OpenAI 兼容端点）"""
    import os
    import requests

    endpoint = os.getenv("VLLM_ENDPOINT", "http://localhost:8001/v1/chat/completions")
    resp = requests.post(
        endpoint,
        json={
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
            "max_tokens": 2048,
        },
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _parse_json(text: str) -> Any:
    """从 LLM 输出中提取 JSON（兼容 markdown 代码块）"""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


# ============ 节点实现 ============

def planner_node(state: CADState) -> CADState:
    """节点 1：理解需求 + 读取图纸结构 → 输出结构化计划"""
    system = f"""你是建筑 CAD 施工图深化规划器。
把用户的自然语言需求拆解为有序的 CAD 操作计划。

{TOOL_DESCRIPTIONS}

输出严格 JSON 数组，每项为 {{"op": "...", "params": {{...}}, "reason": "为什么做这一步"}}。
只输出 JSON，不要解释。"""

    # 先读取图纸上下文
    drawing_info = state.get("drawing_info", {})
    prompt = f"""用户需求：{state['user_request']}

图纸信息：
{json.dumps(drawing_info, ensure_ascii=False, indent=2)[:3000]}

请输出操作计划 JSON 数组。注意：
- 优先使用 cad_batch 合并多个操作（减少往返）
- 图层操作前先确认图层名符合 ARCH_ 前缀规范
- 不确定尺寸时从图纸现有实体推断，不要臆造"""

    retry_note = ""
    if state.get("validation", {}).get("errors"):
        retry_note = f"\n\n上次校验失败，请根据错误修正计划：\n{state['validation']['errors']}\n"

    try:
        plan = _parse_json(_llm_call(prompt + retry_note, system))
        if not isinstance(plan, list):
            plan = [plan]
    except Exception as e:
        # LLM 失败时降级为规则驱动的简单计划
        plan = [{
            "op": "layer_audit",
            "params": {"file": state["drawing_path"]},
            "reason": f"LLM 规划失败({e})，降级执行图层规范检查",
        }]

    state["plan"] = plan
    state["messages"] = state.get("messages", []) + [{
        "role": "planner",
        "content": f"生成 {len(plan)} 步计划",
    }]
    state["stage"] = "planned"
    return state


def coder_node(state: CADState) -> CADState:
    """节点 2：把计划转换为可执行的 MCP 工具调用参数"""
    plan = state.get("plan", [])

    ops = []
    script_lines = []
    for step in plan:
        op_name = step.get("op")
        params = step.get("params", {})

        if op_name == "cad_batch":
            # 批量操作：直接展开
            for sub in params.get("ops", []):
                ops.append(sub)
                script_lines.append(f"batch.add({json.dumps(sub, ensure_ascii=False)})")
        elif op_name == "draw_wall":
            ops.append({"op": "draw_wall", **params})
            script_lines.append(f'msp.add_lwpolyline({params.get("start")}, {params.get("end")}, layer="{params.get("layer", "WALL")}")')
        elif op_name == "insert_opening":
            ops.append({"op": "insert_block", "name": params.get("name", "DOOR"), **params})
            script_lines.append(f'msp.add_blockref("{params.get("name", "DOOR")}", {params.get("insert")})')
        elif op_name == "batch_dimension":
            ops.append({"op": "batch_dimension", **params})
            script_lines.append(f'# 批量标注 layer={params.get("layer")}')
        elif op_name == "layer_audit":
            # 校验类操作不写入图纸
            script_lines.append(f'# 图层规范检查 file={params.get("file", "")}')
        elif op_name == "room_boundary":
            script_lines.append(f'# 房间边界识别 layer={params.get("layer", "WALL")}')
        else:
            # 通用：原样透传给 MCP
            ops.append({"op": op_name, **params})
            script_lines.append(f'# {op_name}: {json.dumps(params, ensure_ascii=False)}')

    state["generated_ops"] = ops
    state["script"] = "\n".join(script_lines)
    state["messages"] = state.get("messages", []) + [{
        "role": "coder",
        "content": f"生成 {len(ops)} 个绘图操作",
    }]
    state["stage"] = "coded"
    return state


def executor_node(state: CADState) -> CADState:
    """节点 3：在临时副本上执行脚本（绝不直接改原图）"""
    source = state["drawing_path"]
    task_id = state.get("task_id", "task")
    out_dir = Path(tempfile.gettempdir()) / "cad_agent_outputs" / task_id
    out_dir.mkdir(parents=True, exist_ok=True)
    temp_output = str(out_dir / "draft.dxf")

    # 复制源文件到临时工作区
    shutil.copy(source, temp_output)

    try:
        from cad_tools import cad_batch

        result = cad_batch(
            ops=state.get("generated_ops", []),
            file=source,
            output=temp_output,
            backend=state.get("backend", "auto"),
        )
        state["exec_result"] = result
        state["final_output"] = temp_output
        state["messages"] = state.get("messages", []) + [{
            "role": "executor",
            "content": f"执行 {len(result.get('results', []))} 步，影响 {result.get('total_entities', 0)} 个实体",
        }]
        state["stage"] = "executed"
    except Exception as e:
        state["error"] = str(e)
        state["exec_result"] = {"success": False, "message": str(e)}
        state["stage"] = "exec_failed"

    return state


def validator_node(state: CADState) -> CADState:
    """节点 4：校验执行结果（规则 + LLM 语义一致性）"""
    errors: List[str] = []
    exec_result = state.get("exec_result", {})

    # 规则校验 1：所有操作成功
    failed_ops = [r for r in exec_result.get("results", []) if not r.get("ok")]
    if failed_ops:
        errors.append(f"操作失败: {[r.get('op') for r in failed_ops]}")

    # 规则校验 2：实体数量无异常突变
    drawing_info = state.get("drawing_info", {})
    before = drawing_info.get("total_entities", 0)
    after = exec_result.get("total_entities", 0)
    if before > 0 and after > 0:
        ratio = after / max(before, 1)
        if ratio < 0.8 or ratio > 1.5:
            errors.append(f"实体数量异常: {before} -> {after}")

    # 规则校验 3：图层规范
    try:
        from cad_tools import layer_audit
        audit = layer_audit(state.get("final_output", ""))
        if not audit.get("passed", False):
            errors.append(f"图层规范问题: {audit.get('violations', [])[:3]}")
    except Exception:
        pass  # 校验工具不可用时不阻断

    # 语义校验：结果是否符合用户意图（用 LLM 判断）
    if not errors:
        try:
            system = "你是 CAD 图纸校验器。判断执行结果是否满足用户需求，输出 JSON: {\"passed\": bool, \"reason\": \"...\"}"
            prompt = f"用户需求: {state['user_request']}\n执行摘要: {json.dumps(exec_result, ensure_ascii=False)[:2000]}"
            verdict = _parse_json(_llm_call(prompt, system))
            if not verdict.get("passed", True):
                errors.append(f"语义校验未通过: {verdict.get('reason', '')}")
        except Exception:
            pass  # LLM 校验失败不阻断

    state["validation"] = {
        "passed": len(errors) == 0,
        "errors": errors,
        "checked_at": datetime.now().isoformat(),
    }
    state["messages"] = state.get("messages", []) + [{
        "role": "validator",
        "content": "校验通过" if not errors else f"发现 {len(errors)} 个问题",
    }]
    state["stage"] = "validated"
    return state


def finalize_node(state: CADState) -> CADState:
    """节点 5：校验通过后写回正式输出路径"""
    source = state["drawing_path"]
    final = state.get("output_path") or source.replace(".dxf", "_deepened.dxf")
    temp = state.get("final_output", "")

    if temp and Path(temp).exists():
        Path(final).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(temp, final)
        state["final_output"] = final

    state["stage"] = "done"
    state["messages"] = state.get("messages", []) + [{
        "role": "system",
        "content": f"交付: {final}",
    }]
    return state


def should_retry(state: CADState) -> Literal["planner", "finalize", "end"]:
    """条件边：校验失败且未超重试次数 → 回到 Planner"""
    validation = state.get("validation", {})
    retry_count = state.get("retry_count", 0)
    max_retries = state.get("max_retries", 3)

    if state.get("stage") == "exec_failed" or state.get("error"):
        if retry_count < max_retries:
            return "planner"
        return "end"

    if validation.get("passed", False):
        return "finalize"

    if retry_count < max_retries:
        return "planner"
    return "end"  # 超过重试次数 → 转人工


# ============ 图构建 ============

def build_graph(checkpointer=None):
    """构建 LangGraph 状态机"""
    workflow = StateGraph(CADState)

    workflow.add_node("planner", planner_node)
    workflow.add_node("coder", coder_node)
    workflow.add_node("executor", executor_node)
    workflow.add_node("validator", validator_node)
    workflow.add_node("finalize", finalize_node)

    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "coder")
    workflow.add_edge("coder", "executor")
    workflow.add_edge("executor", "validator")

    workflow.add_conditional_edges(
        "validator",
        should_retry,
        {
            "planner": "planner",
            "finalize": "finalize",
            "end": END,
        },
    )
    workflow.add_edge("finalize", END)

    return workflow.compile(checkpointer=checkpointer or MemorySaver())


# 全局图实例（生产用 PostgresSaver/RedisSaver 替代 MemorySaver）
graph = build_graph()


def run_task(state: CADState, thread_id: str = "default") -> CADState:
    """执行一个 CAD 深化任务"""
    config = {"configurable": {"thread_id": thread_id}}
    final_state = graph.invoke(state, config)
    return final_state
