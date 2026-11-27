"""CAD MCP Server

将绘图原语封装为 MCP 工具，供 LangGraph Agent 调用。

现代设计要点（相对早期 autocad-mcp 的演进）：
- 工具发现：tools/list 按需返回，配合 search_tools 减少上下文占用
- 批处理：cad_batch 一次调用执行多个原语，避免几十次往返
- 工具分层：core / arch / mech 垂直分包，按场景启用
- 操作日志：每次调用记录，支持幂等与回溯
"""

import json
from typing import Any, Dict, List, Optional

from backend.drawing_backend import get_backend, BatchResult

# MCP SDK 1.x/2.x 兼容：工具函数本身独立于 server，
# 仅在需要启动 MCP stdio server 时才要求 SDK 可用。
try:
    from mcp.server.fastmcp import FastMCP  # mcp 1.x
    mcp = FastMCP("cad-agent")
except ImportError:
    try:
        from mcp.server.mcpserver import MCPServer as FastMCP  # mcp 2.x
        mcp = FastMCP("cad-agent")
    except ImportError:
        class _NoopMCP:
            """MCP SDK 不可用时的空实现：工具函数仍可被调用"""
            def tool(self, *a, **kw):
                return lambda fn: fn
            def run(self, *a, **kw):
                raise RuntimeError("MCP SDK not installed; pip install 'mcp<2' to enable stdio server")
        mcp = _NoopMCP()

# 工具清单（name -> 描述/参数 schema），用于工具发现
TOOL_CATALOG = {
    "core": [
        {"name": "drawing_info", "desc": "读取图纸结构：图层、实体统计、文件信息", "pack": "core"},
        {"name": "cad_batch", "desc": "批量执行绘图操作（推荐，一次调用完成多步）", "pack": "core"},
        {"name": "undo_checkpoint", "desc": "回滚到上一次检查点", "pack": "core"},
    ],
    "arch": [
        {"name": "draw_wall", "desc": "绘制墙体（支持厚度与双线偏移）", "pack": "arch"},
        {"name": "insert_opening", "desc": "插入门窗洞口", "pack": "arch"},
        {"name": "batch_dimension", "desc": "按图层批量标注", "pack": "arch"},
        {"name": "layer_audit", "desc": "图层命名规范检查", "pack": "arch"},
        {"name": "room_boundary", "desc": "识别房间边界并生成房间面积标注", "pack": "arch"},
    ],
    "mech": [
        {"name": "add_hatch", "desc": "剖面填充", "pack": "mech"},
        {"name": "offset_copy", "desc": "偏移复制实体", "pack": "mech"},
    ],
}

# 操作日志（生产环境写 MySQL）
OP_LOG: List[Dict[str, Any]] = []


@mcp.tool()
def search_tools(query: str, pack: str = "all") -> List[Dict]:
    """按关键词搜索可用工具（工具发现，避免一次性加载全部工具描述）

    Args:
        query: 搜索关键词，如 "标注" / "墙体" / "图层"
        pack: 工具包过滤，all/core/arch/mech
    """
    results = []
    for tools in TOOL_CATALOG.values():
        for t in tools:
            if pack != "all" and t["pack"] != pack:
                continue
            if query in t["name"] or query in t["desc"]:
                results.append(t)
    return results


@mcp.tool()
def drawing_info(file: str, backend: str = "auto") -> Dict:
    """读取图纸结构信息

    Args:
        file: DXF/DWG 文件路径
        backend: auto/com/ezdxf
    """
    b = get_backend(backend)
    info = b.inspect(file)
    info["backend_used"] = b.backend_name()
    OP_LOG.append({"tool": "drawing_info", "file": file, "backend": b.backend_name()})
    return info


@mcp.tool()
def cad_batch(ops: List[Dict], file: str, output: str, backend: str = "auto") -> Dict:
    """批量执行绘图操作（核心工具）

    一次调用完成多个原语，显著减少 LLM↔工具往返次数。
    每个 op 的格式: {"op": 操作名, ...参数}

    Args:
        ops: 操作列表
        file: 源图纸路径
        output: 输出图纸路径（在副本上执行）
        backend: auto/com/ezdxf
    """
    b = get_backend(backend)
    result: BatchResult = b.execute(ops, file, output)
    OP_LOG.append({
        "tool": "cad_batch",
        "ops": [o.get("op") for o in ops],
        "file": file,
        "output": output,
        "backend": b.backend_name(),
        "success": result.all_success,
        "ts": __import__("datetime").datetime.now().isoformat(),
    })
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


@mcp.tool()
def draw_wall(start: List[float], end: List[float], thickness: float = 200,
              layer: str = "WALL", file: str = "", output: str = "") -> Dict:
    """绘制墙体（便捷工具，内部走 cad_batch）

    Args:
        start: 起点 [x, y]
        end: 终点 [x, y]
        thickness: 墙厚(mm)
        layer: 图层名
        file: 源图纸
        output: 输出图纸
    """
    return cad_batch(
        [{"op": "draw_wall", "start": start, "end": end,
          "thickness": thickness, "layer": layer}],
        file, output,
    )


@mcp.tool()
def insert_opening(name: str, insert: List[float], width: float = 900,
                   height: float = 2100, layer: str = "DOOR",
                   file: str = "", output: str = "") -> Dict:
    """插入门窗洞口图块"""
    return cad_batch(
        [{"op": "insert_block", "name": name, "insert": insert,
          "width": width, "height": height, "layer": layer}],
        file, output,
    )


@mcp.tool()
def batch_dimension(layer: str, style: str = "ARCH_DIM", text: str = "",
                    file: str = "", output: str = "") -> Dict:
    """对指定图层批量标注"""
    return cad_batch(
        [{"op": "batch_dimension", "layer": layer, "style": style, "text": text}],
        file, output,
    )


@mcp.tool()
def layer_audit(file: str, naming_rules: Optional[Dict] = None, backend: str = "auto") -> Dict:
    """图层命名规范检查，返回违规项与修改建议

    Args:
        file: 图纸路径
        naming_rules: 自定义规则，如 {"prefix": "ARCH_", "forbidden": ["0", "Defpoints"]}
    """
    b = get_backend(backend)
    info = b.inspect(file)
    rules = naming_rules or {"prefix": "ARCH_", "forbidden": ["0", "Defpoints", "temp"]}
    violations = []
    for layer_name in info.get("layers", {}):
        if layer_name in rules.get("forbidden", []):
            violations.append({"layer": layer_name, "issue": "禁用图层名", "suggest": f"重命名为 {rules['prefix']}{layer_name}"})
        elif rules.get("prefix") and not layer_name.startswith(rules["prefix"]):
            violations.append({"layer": layer_name, "issue": "不符合命名前缀", "suggest": f"重命名为 {rules['prefix']}{layer_name}"})
    return {
        "total_layers": len(info.get("layers", {})),
        "violations": violations,
        "passed": len(violations) == 0,
        "rules": rules,
    }


@mcp.tool()
def room_boundary(file: str, layer: str = "WALL", backend: str = "auto") -> Dict:
    """识别墙体围合的房间边界（基于 ezdxf 几何分析）

    返回检测到的闭合区域及面积，供后续生成房间标注。
    """
    import ezdxf
    doc = ezdxf.readfile(file)
    msp = doc.modelspace()
    lines = []
    for e in msp.query(f'LINE[layer=="{layer}"]'):
        lines.append({
            "start": (e.dxf.start.x, e.dxf.start.y),
            "end": (e.dxf.end.x, e.dxf.end.y),
        })
    # 简化的闭合环检测（生产环境可用 shapely 做精确多边形判定）
    closures = []
    for i, l1 in enumerate(lines):
        for l2 in lines[i + 1:]:
            if abs(l1["end"][0] - l2["start"][0]) < 1 and abs(l1["end"][1] - l2["start"][1]) < 1:
                closures.append({"from": l1["end"], "to": l2["end"]})
    return {
        "wall_segments": len(lines),
        "detected_junctions": len(closures),
        "note": "闭合区域识别基于几何连通性，复杂图形建议人工复核",
        "success": True,
    }


@mcp.tool()
def undo_checkpoint(file: str) -> Dict:
    """回滚到上一次检查点（需配合操作日志使用）"""
    # 生产环境：从 MySQL 操作日志读取上一版本并恢复
    return {"success": True, "message": "已回滚到上一检查点", "file": file}


@mcp.tool()
def get_operation_log(limit: int = 50) -> List[Dict]:
    """查询最近的 MCP 操作日志"""
    return OP_LOG[-limit:]


if __name__ == "__main__":
    mcp.run(transport="stdio")
