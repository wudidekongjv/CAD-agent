"""规则引擎：LLM 不可用时的确定性降级

真实项目中 LLM 端点可能故障（无 Key、限流、网络断开）。
规则引擎基于关键词匹配 + 元数据，完成高频 CAD 深化任务：
- 图层规范化（重命名、清理）
- 批量标注（按图层）
- 墙线加厚（线宽调整）
- 实体查询/统计

这不是"演示"，而是生产级降级——保证核心功能不中断。
"""

import re
from typing import Any, Dict, List, Tuple


# 中文数字 → 阿拉伯数字
CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
          "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def parse_request(text: str, metadata: Dict) -> Dict[str, Any]:
    """规则解析用户需求 → 结构化操作计划

    Returns:
        {"intent": 意图, "ops": [...], "reason": ...}
    """
    text = text.lower()
    layers = [l["name"] for l in metadata.get("overview", {}).get("layer_tree", [])]
    has_arch = any(l.startswith("ARCH_") for l in layers)

    # 意图1：图层规范化
    if any(k in text for k in ["图层", "layer", "规范", "命名"]):
        ops = []
        if not has_arch:
            # 非 ARCH_ 图层 → 重命名
            for l in layers:
                if l in ("0", "Defpoints"):
                    continue
                new_name = f"ARCH_{l}" if not l.startswith("ARCH_") else l
                ops.append({
                    "op": "set_layer",
                    "old_name": l,
                    "layer": new_name,
                    "props": {},
                    "reason": "图层命名规范要求 ARCH_ 前缀",
                })
        return {
            "intent": "layer_normalize",
            "ops": ops[:20],
            "reason": f"检测到 {len(layers)} 个图层，规划 {min(len(ops),20)} 项规范化操作",
            "confidence": 0.85,
        }

    # 意图2：批量标注
    if any(k in text for k in ["标注", "dimension", "尺寸"]):
        target = "WALL"
        m = re.search(r"([A-Z_]+)\s*图层", text, re.I)
        if m:
            target = m.group(1).upper()
        return {
            "intent": "batch_dimension",
            "ops": [{
                "op": "batch_dimension",
                "layer": target,
                "style": "ARCH_DIM",
                "reason": "按标注样式规范 ARCH_DIM 批量标注",
            }],
            "reason": f"对 {target} 图层批量标注",
            "confidence": 0.8,
        }

    # 意图3：墙线加厚/线宽
    if any(k in text for k in ["加厚", "线宽", "墙线", "粗细"]):
        target = "WALL"
        m = re.search(r"([A-Z_]+)\s*图层", text, re.I)
        if m:
            target = m.group(1).upper()
        # 提取数字（如 0.35mm）
        weight = 35  # 默认 0.35mm → DXF lineweight 35
        mw = re.search(r"0\.(\d+)\s*mm", text)
        if mw:
            weight = int(mw.group(1)) * 10
        return {
            "intent": "lineweight",
            "ops": [{
                "op": "batch_modify",
                "filter": f'LINE[layer=="{target}"]',
                "props": {"lineweight": weight},
                "reason": f"线宽规范：墙线 {weight/100:.2f}mm",
            }],
            "reason": f"将 {target} 图层线宽调整为 {weight/100:.2f}mm",
            "confidence": 0.8,
        }

    # 意图4：查询/统计
    if any(k in text for k in ["统计", "多少", "查询", "检查", "识别"]):
        return {
            "intent": "inspect",
            "ops": [],
            "reason": f"图纸含 {metadata.get('overview',{}).get('totals',{}).get('entities',0)} 个实体，"
                      f"{len(layers)} 个图层",
            "confidence": 0.9,
        }

    # 兜底：图层审计（最安全的只读操作）
    return {
        "intent": "audit",
        "ops": [],
        "reason": "无法精确解析需求，执行安全的图层规范检查（只读）",
        "confidence": 0.5,
    }


def execute_rule_plan(ops: List[Dict], source: str, output: str, backend: str = "ezdxf") -> Dict:
    """执行规则计划（扩展后端以支持 rename）"""
    import sys
    from backend.drawing_backend import get_backend

    b = get_backend(backend)
    # set_layer 的 old_name → rename 操作由后端处理
    result = b.execute(ops, source, output)
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


def rule_based_plan(system: str, user: str) -> str:
    """生成规则驱动的计划 JSON（供 graph 的 planner 节点调用）

    从 user 中提取需求文本与元数据。
    """
    try:
        ctx = json.loads(user) if user.strip().startswith("{") else {}
    except Exception:
        ctx = {}

    request = ctx.get("user_request", "")
    metadata = ctx.get("drawing_summary", {})
    plan = parse_request(request, metadata)
    return json.dumps(plan["ops"], ensure_ascii=False)


import json  # noqa: E402
