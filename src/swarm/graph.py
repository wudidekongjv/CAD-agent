"""LangGraph 驱动的 Swarm 多 Agent 编排

用 LangGraph StateGraph + Command(goto=...) 实现 handoff：
- 每个 Agent 是一个节点
- Agent 通过 Command(goto="下一个Agent") 自主移交控制权
- 保留 LangGraph 的持久化、流式、human-in-the-loop 能力

这比自研循环更稳健：有 checkpoint、可断点续跑、可_STREAM 输出。
"""

import json
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command

from .state import SwarmState
from .llm import get_llm


def _llm_decide(system: str, user: str, tools: Optional[List[Dict]] = None) -> Dict:
    """调用 LLM 获取决策（工具调用或最终答案）"""
    llm = get_llm()
    return llm.chat([
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ], tools=tools)


def _extract_decision(response: Dict) -> tuple:
    """从 LLM 响应中提取 (handoff_target, content, tool_calls)"""
    tool_calls = response.get("tool_calls") or []
    for call in tool_calls:
        name = call["function"]["name"]
        if name.startswith("transfer_to_"):
            return name.replace("transfer_to_", ""), response.get("content", ""), tool_calls
    return None, response.get("content", ""), tool_calls


# ============ Agent 节点 ============

def planner_node(state: SwarmState) -> Command:
    """Planner：理解需求 + 读知识库规范 → 输出计划"""
    from knowledge import retrieve_standards

    # 从知识库检索相关规范（这是规范校验的依据）
    standards = retrieve_standards(state["user_request"], top_k=5)
    state["knowledge_refs"] = [s["source"] for s in standards]

    system = """你是建筑 CAD 施工图深化的 Planner。
基于用户需求与检索到的制图规范，制定操作计划。
输出 JSON 数组：[{"op": 操作名, "params": {...}, "reason": "依据哪条规范"}]

可用操作：drawing_info / layer_audit / set_layer / batch_modify / draw_wall /
insert_block / add_dimension / delete_entities / offset / hatch

完成后：
- 需要 Coder 生成脚本 → 调用 transfer_to_Coder
- 信息不足需人工 → 调用 transfer_to_Reviewer
"""
    context = {
        "user_request": state["user_request"],
        "drawing_summary": state.get("drawing_summary", {}),  # 只有结构摘要，无坐标原文
        "standards": standards,
    }
    response = _llm_decide(system, json.dumps(context, ensure_ascii=False),
                           tools=state.get("handoff_tools"))
    target, content, _ = _extract_decision(response)

    state["plan"] = content
    state["current_agent"] = "planner"
    state["messages"].append({"agent": "Planner", "content": f"检索到 {len(standards)} 条规范，已制定计划"})
    state["handoff_count"] += 1

    if state["handoff_count"] >= state["max_handoffs"]:
        return Command(goto="deliver", update=state)
    return Command(goto=target.lower() if target else "coder", update=state)


def coder_node(state: SwarmState) -> Command:
    """Coder：计划 → MCP 工具调用参数"""
    system = """你是 CAD 操作代码生成 Agent。
把 Planner 的计划转换为 cad_batch 的 ops 数组。
每个 op: {"op": 操作名, ...参数}
检查参数完整性，不确定尺寸时从图纸摘要推断。
完成后调用 transfer_to_Executor。
"""
    response = _llm_decide(system, f"计划:\n{state.get('plan', '')}\n\n图纸摘要:\n{json.dumps(state.get('drawing_summary', {}), ensure_ascii=False)}",
                           tools=state.get("handoff_tools"))
    target, content, _ = _extract_decision(response)

    state["generated_ops"] = content
    state["current_agent"] = "coder"
    state["messages"].append({"agent": "Coder", "content": "已生成工具调用参数"})
    state["handoff_count"] += 1

    if state["handoff_count"] >= state["max_handoffs"]:
        return Command(goto="deliver", update=state)
    return Command(goto=target.lower() if target else "executor", update=state)


def executor_node(state: SwarmState) -> Command:
    """Executor：在临时副本执行"""
    from mcp.cad_mcp_server import cad_batch

    system = """你是 CAD 执行 Agent。
调用 cad_batch 在临时副本执行操作。
执行失败时：
- 参数问题 → transfer_to_Coder
- 需求理解问题 → transfer_to_Planner
- 成功 → transfer_to_Validator
"""
    response = _llm_decide(system, f"操作:\n{state.get('generated_ops', '')}",
                           tools=state.get("handoff_tools"))
    target, content, _ = _extract_decision(response)

    # 实际执行（结构化 ops 从 LLM 输出解析）
    try:
        ops = json.loads(content) if content.strip().startswith("[") else []
    except Exception:
        ops = []

    if ops:
        result = cad_batch(ops, state["drawing_path"], state["temp_output"], state.get("backend", "auto"))
        state["exec_result"] = result
    else:
        state["exec_result"] = {"success": False, "message": "无法解析操作"}

    state["current_agent"] = "executor"
    state["messages"].append({"agent": "Executor", "content": f"执行 {len(ops)} 个操作"})
    state["handoff_count"] += 1

    if state["handoff_count"] >= state["max_handoffs"]:
        return Command(goto="deliver", update=state)
    return Command(goto=target.lower() if target else "validator", update=state)


def validator_node(state: SwarmState) -> Command:
    """Validator：规则校验 + 知识库规范比对"""
    from knowledge import retrieve_standards, validate_against_standards

    # 基于知识库规范校验
    standards = retrieve_standards("图层命名 标注样式 制图规范", top_k=8)
    validation = validate_against_standards(state["temp_output"], standards)
    state["validation"] = validation

    # 语义校验（API 模型更强）
    system = """你是 CAD 校验 Agent。
判断执行结果是否满足用户需求与规范。
- 通过 → transfer_to_Deliver
- 图层问题 → transfer_to_Coder
- 需求偏差 → transfer_to_Planner
- 需人工 → transfer_to_Reviewer
"""
    response = _llm_decide(system, json.dumps({
        "user_request": state["user_request"],
        "validation": validation,
        "exec_result": state.get("exec_result", {}),
    }, ensure_ascii=False), tools=state.get("handoff_tools"))
    target, content, _ = _extract_decision(response)

    state["current_agent"] = "validator"
    state["messages"].append({"agent": "Validator", "content": f"校验{'通过' if validation.get('passed') else '未通过'}"})
    state["handoff_count"] += 1

    if state["handoff_count"] >= state["max_handoffs"]:
        return Command(goto="deliver", update=state)
    return Command(goto=target.lower() if target else "deliver", update=state)


def reviewer_node(state: SwarmState) -> Command:
    """Reviewer：人工复核协调（interrupt）"""
    state["current_agent"] = "reviewer"
    state["needs_review"] = True
    state["messages"].append({"agent": "Reviewer", "content": "等待人工确认"})
    return Command(goto="deliver", update=state)


def deliver_node(state: SwarmState) -> Dict[str, Any]:
    """Deliver：汇总交付"""
    state["current_agent"] = "deliver"
    import shutil
    shutil.copy(state["temp_output"], state["output_path"])
    state["messages"].append({"agent": "Deliver", "content": f"交付: {state['output_path']}"})
    return state


# ============ 图构建 ============

def build_swarm_graph():
    """构建 LangGraph Swarm（handoff via Command）"""
    workflow = StateGraph(SwarmState)

    # 六个 Agent 节点
    for name, node in [
        ("planner", planner_node), ("coder", coder_node),
        ("executor", executor_node), ("validator", validator_node),
        ("reviewer", reviewer_node), ("deliver", deliver_node),
    ]:
        workflow.add_node(name, node)

    # 入口边
    workflow.add_edge(START, "planner")

    # 节点间通过 Command(goto) 自主跳转，无需静态边
    # 只需为 deliver 添加终点边
    workflow.add_edge("deliver", END)

    return workflow.compile(checkpointer=MemorySaver())


# 全局图
swarm_graph = build_swarm_graph()


def run_swarm(state: SwarmState, thread_id: str = "default") -> SwarmState:
    """执行 Swarm 任务"""
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}
    result = swarm_graph.invoke(state, config)
    return result
