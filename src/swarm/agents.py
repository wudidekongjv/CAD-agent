"""CAD 深化的 Swarm Agent 团队

四个专职 Agent，通过 handoff 动态协作：
- Planner：理解需求，读取图纸，制定计划
- Coder：把计划转成 MCP 工具调用
- Executor：在临时副本上执行
- Validator：校验结果，决定是否交付或回退

与固定流水线的关键区别：每个 Agent 都持有 transfer_to_X 工具，
自主决定把控制权交给谁。Validator 可以交回 Planner 重规划，
也可以交给 Reviewer 人工复核，拓扑是运行时涌现的。
"""

from typing import Any, Dict, List, Optional

from .config import config
from .core import Agent, Swarm, make_tool


# ============ 工具函数（延迟导入 CAD 后端） ============

def drawing_info(file: str, backend: str = "auto") -> Dict[str, Any]:
    """读取图纸结构信息：图层清单、实体统计、文件元数据"""
    from backend.drawing_backend import get_backend
    b = get_backend(backend)
    info = b.inspect(file)
    info["backend_used"] = b.backend_name()
    return info


def cad_batch(ops: List[Dict], file: str, output: str, backend: str = "auto") -> Dict[str, Any]:
    """批量执行 CAD 绘图操作。每个 op 为 {'op': 操作名, ...参数}"""
    from backend.drawing_backend import get_backend
    b = get_backend(backend)
    result = b.execute(ops, file, output)
    return {
        "success": result.all_success,
        "results": [
            {"op": r.op, "ok": r.success, "msg": r.message, "affected": r.entities_affected}
            for r in result.results
        ],
        "output_file": result.output_file,
        "total_entities": result.total_entities,
        "backend_used": b.backend_name(),
    }


def layer_audit(file: str, naming_rules: Optional[Dict] = None) -> Dict[str, Any]:
    """图层命名规范检查，返回违规项与修改建议"""
    info = drawing_info(file)
    rules = naming_rules or {"prefix": "ARCH_", "forbidden": ["0", "Defpoints", "temp"]}
    violations = []
    for layer_name in info.get("layers", {}):
        if layer_name in rules.get("forbidden", []):
            violations.append({"layer": layer_name, "issue": "禁用图层名",
                               "suggest": f"重命名为 {rules['prefix']}{layer_name}"})
        elif rules.get("prefix") and not layer_name.startswith(rules["prefix"]):
            violations.append({"layer": layer_name, "issue": "不符合命名前缀",
                               "suggest": f"重命名为 {rules['prefix']}{layer_name}"})
    return {"total_layers": len(info.get("layers", {})), "violations": violations,
            "passed": len(violations) == 0, "rules": rules}


def validate_result(file: str, expected_ops: List[str]) -> Dict[str, Any]:
    """校验执行结果：检查文件存在、实体数量合理、操作是否完成"""
    import os
    info = drawing_info(file)
    errors = []
    if not os.path.exists(file):
        errors.append("输出文件不存在")
    if info.get("total_entities", 0) == 0:
        errors.append("图纸无实体，可能执行失败")
    return {"passed": len(errors) == 0, "errors": errors,
            "total_entities": info.get("total_entities", 0),
            "expected_ops": expected_ops}


# ============ Agent 定义 ============

def _handoff_tool(name: str):
    """生成 handoff 函数"""
    def fn() -> str:
        return f"Transfer to {name}"
    fn.__name__ = f"transfer_to_{name}"
    fn.__doc__ = f"Transfer control to {name} agent"
    return fn


def build_agents() -> Dict[str, Agent]:
    """构建 CAD Swarm 团队"""

    # 工具 schema
    tools_info = [make_tool(drawing_info)]
    tools_batch = [make_tool(cad_batch), make_tool(layer_audit)]
    tools_exec = [make_tool(cad_batch)]
    tools_val = [make_tool(validate_result), make_tool(layer_audit)]

    planner = Agent(
        name="Planner",
        instructions="""你是建筑 CAD 施工图深化的规划 Agent。

职责：
1. 调用 drawing_info 读取图纸结构（图层、实体统计）
2. 理解用户的自然语言需求，结合图纸现状制定操作计划
3. 计划以 JSON 数组输出，每项 {"op": 操作名, "params": {...}, "reason": "理由"}
4. 优先用 cad_batch 合并多个操作，减少往返

可用操作：set_layer / batch_modify / draw_wall / insert_block / add_dimension / delete_entities / offset / hatch

完成后调用 transfer_to_Coder 移交。不要自己执行绘图操作。""",
        tools=tools_info,
        tool_functions={"drawing_info": drawing_info},
    )

    coder = Agent(
        name="Coder",
        instructions="""你是 CAD 操作代码生成 Agent。

职责：把 Planner 的操作计划转换为可执行的 MCP 工具调用参数。
- 检查每个 op 的参数完整性（坐标、图层名、尺寸）
- 不确定尺寸时从图纸现有实体推断，不要臆造
- 输出 cad_batch 的 ops 数组

完成后调用 transfer_to_Executor 移交。""",
        tools=tools_batch,
        tool_functions={"cad_batch": cad_batch, "layer_audit": layer_audit},
    )

    executor = Agent(
        name="Executor",
        instructions="""你是 CAD 脚本执行 Agent。

职责：
1. 在临时副本上执行 cad_batch（绝不直接改原图）
2. 记录执行结果：成功/失败的操作、影响实体数
3. 如果执行失败，分析原因并决定：
   - 参数问题 → transfer_to_Coder 重新生成
   - 需求理解问题 → transfer_to_Planner 重新规划
   - 执行成功 → transfer_to_Validator 校验

注意：backend=auto 会自动探测 COM/ezdxf，失败自动降级。""",
        tools=tools_exec,
        tool_functions={"cad_batch": cad_batch},
    )

    validator = Agent(
        name="Validator",
        instructions="""你是 CAD 深化结果校验 Agent。

职责：
1. 调用 validate_result 检查输出文件与实体数量
2. 调用 layer_audit 检查图层规范
3. 判断执行结果是否满足用户需求

决策：
- 校验通过 → transfer_to_Deliver 交付
- 图层不规范 → transfer_to_Coder 修正
- 需求未满足 → transfer_to_Planner 重规划
- 需要人工确认 → transfer_to_Reviewer 复核

失败是数据而非异常，要明确记录问题原因。""",
        tools=tools_val,
        tool_functions={"validate_result": validate_result, "layer_audit": layer_audit},
    )

    deliver = Agent(
        name="Deliver",
        instructions="""你是交付 Agent。

职责：汇总全过程（需求、计划、执行结果、校验结论），生成最终交付说明。
输出 JSON：{"status": "success", "output_file": "...", "summary": "...", "entities_affected": N}
不再移交，直接给出最终答案。""",
        tools=[],
        tool_functions={},
    )

    reviewer = Agent(
        name="Reviewer",
        instructions="""你是人工复核协调 Agent。

当 Validator 判断需要人工介入时接管：
- 汇总当前进度与问题，生成清晰的复核请求
- 输出等待人工确认的状态，不自动执行任何修改""",
        tools=[],
        tool_functions={},
    )

    # 建立 handoff 关系（动态拓扑）
    for a, targets in [
        (planner, [coder]),
        (coder, [executor, planner]),
        (executor, [validator, coder, planner]),
        (validator, [deliver, coder, planner, reviewer]),
        (reviewer, [planner, deliver]),
    ]:
        a.handoffs = targets
        for t in targets:
            tool = _handoff_tool(t.name)
            a.tools.append(make_tool(tool))
            a.tool_functions[tool.__name__] = tool

    return {
        "planner": planner,
        "coder": coder,
        "executor": executor,
        "validator": validator,
        "deliver": deliver,
        "reviewer": reviewer,
    }


def run_swarm(task: str, drawing_path: str, output_path: str,
              backend: str = "auto", progress_callback=None) -> Dict[str, Any]:
    """运行 CAD Swarm 完成深化任务

    Args:
        task: 用户自然语言需求
        drawing_path: 输入图纸路径
        output_path: 输出图纸路径
        backend: auto/com/ezdxf
        progress_callback: 进度回调 fn(stage, message)
    """
    config.check_kill_switch()

    agents = build_agents()
    swarm = Swarm()

    context = {
        "user_request": task,
        "drawing_path": drawing_path,
        "output_path": output_path,
        "backend": backend,
        "progress": [],
    }

    def progress(stage, msg):
        context["progress"].append({"stage": stage, "msg": msg})
        if progress_callback:
            progress_callback(stage, msg)

    progress("planner", "Planner 正在读取图纸结构…")

    result = swarm.run(
        agent=agents["planner"],
        messages=[{"role": "user", "content": f"""CAD 深化任务：{task}

输入图纸：{drawing_path}
输出路径：{output_path}
后端模式：{backend}

请开始规划，完成后通过 handoff 交给下一个 Agent。"""}],
        context=context,
    )

    return {
        "status": "degraded" if result.degraded else "success",
        "final_output": result.final_output,
        "handoffs": result.handoffs,
        "turns": result.turns,
        "error": result.error,
        "progress": context["progress"],
        "agent_reached": result.agent.name,
    }
