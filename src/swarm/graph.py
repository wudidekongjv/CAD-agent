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


def _llm_decide(system: str, user: str, tools: Optional[List[Dict]] = None,
                fallback: Optional[Any] = None) -> Dict:
    """调用 LLM 获取决策（带模型降级 + 规则引擎兜底）

    降级链：API模型 → 备用API → 规则引擎（确定性，无需网络）
    """
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        if fallback:
            response, provider = fallback.call(messages, tools)
            return response
        llm = get_llm()
        return llm.chat(messages, tools=tools)
    except Exception as e:
        # 所有 LLM 不可用 → 规则引擎兜底（返回带 tool_calls 结构的响应）
        from .rule_engine import rule_based_plan

        content = rule_based_plan(system, user)
        return {
            "role": "assistant",
            "content": content,
            "tool_calls": [{
                "id": "rule_fallback",
                "function": {"name": "transfer_to_coder", "arguments": "{}"},
            }],
            "_degraded": True,
            "_error": str(e)[:200],
        }


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
    """Planner：理解需求 + 读知识库规范 + 细粒度元数据 → 输出计划"""
    from knowledge import retrieve_standards
    from backend.metadata import extract_metadata
    from swarm.guard import ModelFallback, LoopGuard

    # 防死循环检查
    guard = state.get("loop_guard") or LoopGuard()
    state["loop_guard"] = guard

    # 提取细粒度元数据（本地完整，含实体句柄与几何）
    try:
        meta = extract_metadata(state["drawing_path"], detail="full")
        state["drawing_metadata"] = meta
        # 整体性摘要（发 API 用脱敏版）
        state["drawing_summary"] = extract_metadata(
            state["drawing_path"], detail="summary"
        )["overview"]
    except Exception as e:
        state["drawing_summary"] = {"error": str(e)}

    # 从知识库检索相关规范（这是规范校验的依据）
    standards = retrieve_standards(state["user_request"], top_k=5)
    state["knowledge_refs"] = [s["source"] for s in standards]

    # 模型降级链调用
    fallback = state.get("model_fallback") or ModelFallback()
    state["model_fallback"] = fallback

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
                           tools=state.get("handoff_tools"), fallback=state.get("model_fallback"))
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
    # 若 plan 已是合法 ops JSON（规则引擎降级产出），直接透传，不再让 LLM 重新解析
    plan_raw = state.get("plan", "")
    direct_ops = None
    try:
        parsed = json.loads(plan_raw) if isinstance(plan_raw, str) else plan_raw
        if isinstance(parsed, list) and all(isinstance(x, dict) and "op" in x for x in parsed):
            direct_ops = parsed
    except Exception:
        pass

    if direct_ops is not None:
        # 规则引擎已产出确定性 ops
        ops_json = json.dumps(direct_ops, ensure_ascii=False)
        state["generated_ops"] = ops_json
        state["current_agent"] = "coder"
        state["messages"].append({"agent": "Coder", "content": f"规则引擎产出 {len(direct_ops)} 个操作"})
        state["handoff_count"] += 1
        return Command(goto="executor", update=state)

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
    """Executor：在临时副本执行

    确定性执行 generated_ops（不让 LLM 重新生成——那是 Coder 的职责）。
    LLM 仅在失败时用于归因，且降级为规则判断。
    """
    from cad_tools import cad_batch

    # 直接解析 Coder 产出的 ops
    ops_raw = state.get("generated_ops", "")
    try:
        ops = json.loads(ops_raw) if isinstance(ops_raw, str) else ops_raw
        if not isinstance(ops, list):
            ops = []
    except Exception:
        ops = []

    if ops:
        result = cad_batch(ops, state["drawing_path"], state["temp_output"], state.get("backend", "auto"))
        state["exec_result"] = result
        all_ok = result.get("success", False)
    else:
        # 无操作（如纯查询意图）→ 复制原图作为结果，视为成功
        import shutil
        shutil.copy(state["drawing_path"], state["temp_output"])
        result = {"success": True, "results": [], "message": "只读任务，无绘图操作"}
        state["exec_result"] = result
        all_ok = True

    state["current_agent"] = "executor"
    state["messages"].append({
        "agent": "Executor",
        "content": f"执行 {len(ops)} 个操作，{'成功' if all_ok else '部分失败'}",
    })
    state["handoff_count"] += 1

    # 失败归因：规则判断（不依赖 LLM）
    if not all_ok:
        failed = [r for r in result.get("results", []) if not r.get("ok")]
        failure_msg = "; ".join(r.get("msg", "") for r in failed)[:200]
        state.setdefault("errors", []).append(f"执行失败: {failure_msg}")

    if state["handoff_count"] >= state["max_handoffs"]:
        return Command(goto="deliver", update=state)
    return Command(goto="validator", update=state)


def validator_node(state: SwarmState) -> Command:
    """Validator：规则校验 + 知识库规范比对 + 元数据前后对比"""
    from knowledge import retrieve_standards, validate_against_standards
    from backend.metadata import extract_metadata
    from swarm.guard import DataValidator, LoopGuard

    # 基于知识库规范校验
    standards = retrieve_standards("图层命名 标注样式 制图规范", top_k=8)
    validation = validate_against_standards(state["temp_output"], standards)

    # 元数据前后对比（细粒度：实体级增删改）
    try:
        before = state.get("drawing_metadata") or extract_metadata(state["drawing_path"], "full")
        after = extract_metadata(state["temp_output"], "full")
        expected_ops = state.get("generated_ops", "")
        try:
            import json as _json
            ops = _json.loads(expected_ops) if isinstance(expected_ops, str) and expected_ops.strip().startswith("[") else []
        except Exception:
            ops = []
        diff_check = DataValidator().validate_result(before, after, ops)
        validation["metadata_diff"] = diff_check.get("diff", {})
        if not diff_check.get("passed"):
            validation["errors"].extend([
                {"rule": "元数据校验", "detail": e} for e in diff_check.get("errors", [])
            ])
            validation["passed"] = False
    except Exception as e:
        validation.setdefault("errors", []).append({"rule": "元数据校验", "detail": str(e)})

    # 防死循环检查
    guard = state.get("loop_guard") or LoopGuard()
    ok, reason = guard.check_handoff("validator", state)
    if not ok:
        validation["passed"] = False
        validation.setdefault("errors", []).append({"rule": "循环保护", "detail": reason})

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
    }, ensure_ascii=False), tools=state.get("handoff_tools"), fallback=state.get("model_fallback"))
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
