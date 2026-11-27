"""CAD 原始元数据提取：细粒度 + 整体性双层

设计目标：
- **整体性**：图纸级概览——图层树、实体分布、块定义、样式表、空间范围、统计特征
- **细粒度**：实体级原始数据——每个实体的 DXF 句柄、类型、图层、坐标、几何参数、扩展数据
- **分层输出**：full（本地完整）/ summary（发 API 的脱敏摘要，不含坐标）

元数据是 Agent 决策的基础：
- Planner 需要知道有哪些图层、实体类型分布，才能制定计划
- Coder 需要知道具体实体的句柄与参数，才能生成精确操作
- Validator 需要前后元数据对比，才能判断操作是否符合预期
"""

import math
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


# ============ 实体几何提取 ============

def _point(p) -> List[float]:
    """DXF 点 → [x, y, z]"""
    try:
        return [round(float(p.x), 3), round(float(p.y), 3), round(float(getattr(p, "z", 0)), 3)]
    except Exception:
        return []


def _entity_geometry(entity) -> Dict[str, Any]:
    """提取单个实体的完整几何参数（按类型分支）"""
    etype = entity.dxftype()
    geo: Dict[str, Any] = {}

    try:
        if etype == "LINE":
            geo = {"start": _point(entity.dxf.start), "end": _point(entity.dxf.end)}
            dx = entity.dxf.end.x - entity.dxf.start.x
            dy = entity.dxf.end.y - entity.dxf.start.y
            geo["length"] = round(math.hypot(dx, dy), 2)
            geo["angle"] = round(math.degrees(math.atan2(dy, dx)), 2)

        elif etype in ("LWPOLYLINE", "POLYLINE"):
            pts = [_point(p) for p in entity.get_points("xy")]
            geo = {"points": pts, "vertex_count": len(pts), "closed": bool(entity.closed)}
            if len(pts) >= 3:
                # 面积（鞋带公式）
                area = 0.0
                for i in range(len(pts)):
                    x1, y1 = pts[i][0], pts[i][1]
                    x2, y2 = pts[(i + 1) % len(pts)][0], pts[(i + 1) % len(pts)][1]
                    area += x1 * y2 - x2 * y1
                geo["area"] = round(abs(area) / 2, 2)

        elif etype == "CIRCLE":
            geo = {"center": _point(entity.dxf.center), "radius": round(float(entity.dxf.radius), 2)}

        elif etype == "ARC":
            geo = {
                "center": _point(entity.dxf.center),
                "radius": round(float(entity.dxf.radius), 2),
                "start_angle": round(float(entity.dxf.start_angle), 2),
                "end_angle": round(float(entity.dxf.end_angle), 2),
            }

        elif etype == "TEXT":
            geo = {
                "text": entity.dxf.text,
                "insert": _point(entity.dxf.insert),
                "height": round(float(entity.dxf.height), 2),
                "rotation": round(float(entity.dxf.get("rotation", 0)), 2),
            }

        elif etype == "MTEXT":
            geo = {
                "text": entity.text[:200],
                "insert": _point(entity.dxf.insert),
                "char_height": round(float(entity.dxf.char_height), 2),
            }

        elif etype == "INSERT":
            geo = {
                "block_name": entity.dxf.name,
                "insert": _point(entity.dxf.insert),
                "xscale": round(float(entity.dxf.get("xscale", 1)), 3),
                "yscale": round(float(entity.dxf.get("yscale", 1)), 3),
                "rotation": round(float(entity.dxf.get("rotation", 0)), 2),
            }

        elif etype == "DIMENSION":
            geo = {
                "text": entity.dxf.get("text", ""),
                "defpoint": _point(entity.dxf.get("defpoint", (0, 0, 0))),
                "dimtype": int(entity.dxf.get("dimtype", 0)),
            }

        elif etype == "HATCH":
            geo = {
                "pattern": entity.dxf.get("pattern_name", ""),
                "solid": bool(entity.dxf.get("solid", 0)),
            }

        else:
            # 通用：收集所有 DXF 属性
            geo = {attr: str(value)[:100] for attr, value in entity.dxf.all_existing_dxf_attribs().items()}
    except Exception as e:
        geo = {"extraction_error": str(e)}

    return geo


def _entity_record(entity) -> Dict[str, Any]:
    """实体级完整记录（最细粒度）"""
    record: Dict[str, Any] = {
        "handle": entity.dxf.handle,          # DXF 唯一句柄
        "type": entity.dxftype(),
        "layer": entity.dxf.layer,
        "linetype": entity.dxf.get("linetype", "BYLAYER"),
        "color": entity.dxf.get("color", 256),
        "lineweight": entity.dxf.get("lineweight", -1),
    }
    record.update(_entity_geometry(entity))

    # 扩展数据（XDATA）
    try:
        xdata = entity.xdata
        if xdata:
            record["xdata"] = {k: str(v)[:200] for k, v in xdata.items()}
    except Exception:
        pass

    return record


# ============ 整体性提取 ============

def _layer_tree(doc) -> List[Dict[str, Any]]:
    """图层树：名称、属性、实体数量、状态"""
    layers = []
    entity_counts = Counter(e.dxf.layer for e in doc.modelspace())
    for lay in doc.layers:
        name = lay.dxf.name
        layers.append({
            "name": name,
            "color": lay.dxf.get("color", 7),
            "linetype": lay.dxf.get("linetype", "CONTINUOUS"),
            "lineweight": lay.dxf.get("lineweight", -3),
            "on": not lay.is_off(),
            "frozen": lay.is_frozen(),
            "locked": lay.is_locked(),
            "entity_count": entity_counts.get(name, 0),
        })
    return sorted(layers, key=lambda x: -x["entity_count"])


def _block_definitions(doc) -> List[Dict[str, Any]]:
    """块定义清单（门窗等图块）"""
    blocks = []
    for blk in doc.blocks:
        name = blk.name
        if name.startswith("*"):   # 跳过匿名块
            continue
        blocks.append({
            "name": name,
            "entity_count": len(list(blk)),
            "base_point": _point(blk.base_point),
        })
    return blocks


def _style_tables(doc) -> Dict[str, Any]:
    """样式表：文字样式、标注样式、线型"""
    result = {}
    try:
        result["text_styles"] = [
            {"name": s.dxf.name, "font": s.dxf.get("font", ""), "height": s.dxf.get("height", 0)}
            for s in doc.styles
        ]
    except Exception:
        result["text_styles"] = []
    try:
        result["dim_styles"] = [
            {"name": d.dxf.name, "dimtxt": d.dxf.get("dimtxt", 0), "dimasz": d.dxf.get("dimasz", 0)}
            for d in doc.dimstyles
        ]
    except Exception:
        result["dim_styles"] = []
    try:
        result["linetypes"] = [lt.dxf.name for lt in doc.linetypes]
    except Exception:
        result["linetypes"] = []
    return result


def _spatial_extent(entities: List[Dict]) -> Dict[str, Any]:
    """空间范围：整体包围盒"""
    xs, ys = [], []
    for e in entities:
        for key in ("start", "end", "center", "insert", "defpoint"):
            p = e.get(key)
            if p and len(p) >= 2:
                xs.append(p[0]); ys.append(p[1])
        for p in e.get("points", []):
            if len(p) >= 2:
                xs.append(p[0]); ys.append(p[1])
    if not xs or not ys:
        return {"available": False}
    return {
        "available": True,
        "min_x": round(min(xs), 2), "max_x": round(max(xs), 2),
        "min_y": round(min(ys), 2), "max_y": round(max(ys), 2),
        "width": round(max(xs) - min(xs), 2),
        "height": round(max(ys) - min(ys), 2),
    }


# ============ 主入口 ============

def extract_metadata(file_path: str, detail: str = "full",
                     entity_limit: Optional[int] = None) -> Dict[str, Any]:
    """提取 CAD 元数据

    Args:
        file_path: DXF 文件
        detail: full（完整）/ summary（脱敏摘要，可发 API）
        entity_limit: 实体明细上限（None=全部）

    Returns:
        双层结构：
        - overview：整体性（图层树、块、样式、空间范围、统计）
        - entities：细粒度（逐实体原始记录）
    """
    import ezdxf

    doc = ezdxf.readfile(file_path)
    msp = doc.modelspace()

    # 细粒度：逐实体记录
    entities = []
    for i, entity in enumerate(msp):
        if entity_limit and i >= entity_limit:
            break
        entities.append(_entity_record(entity))

    # 整体性
    type_counts = Counter(e["type"] for e in entities)
    layer_counts = Counter(e["layer"] for e in entities)
    overview = {
        "file": {
            "name": Path(file_path).name,
            "dxf_version": doc.dxfversion,
            "size_bytes": Path(file_path).stat().st_size,
            "extracted_at": datetime.now().isoformat(),
        },
        "totals": {
            "entities": len(list(msp)),
            "layers": len(doc.layers),
            "blocks": len([b for b in doc.blocks if not b.name.startswith("*")]),
        },
        "layer_tree": _layer_tree(doc),
        "entity_types": dict(type_counts.most_common()),
        "layer_distribution": dict(layer_counts.most_common()),
        "block_definitions": _block_definitions(doc),
        "style_tables": _style_tables(doc),
        "spatial_extent": _spatial_extent(entities),
    }

    result = {"overview": overview, "entities": entities}

    if detail == "summary":
        # 脱敏摘要：只有元数据，无坐标/句柄/文本内容
        return {
            "overview": {
                "file": overview["file"],
                "totals": overview["totals"],
                "layer_tree": [
                    {"name": l["name"], "entity_count": l["entity_count"], "on": l["on"]}
                    for l in overview["layer_tree"]
                ],
                "entity_types": overview["entity_types"],
                "layer_distribution": overview["layer_distribution"],
                "block_names": [b["name"] for b in overview["block_definitions"]],
                "style_names": {
                    "text": [s["name"] for s in overview["style_tables"]["text_styles"]],
                    "dim": [d["name"] for d in overview["style_tables"]["dim_styles"]],
                },
                "spatial_extent": overview["spatial_extent"],
            },
            "entities": [],   # 明细不出网
        }

    return result


def compare_metadata(before: Dict[str, Any], after: Dict[str, Any]) -> Dict[str, Any]:
    """元数据前后对比（Validator 用）"""
    b, a = before["overview"], after["overview"]
    be = {e["handle"]: e for e in before["entities"]}
    ae = {e["handle"]: e for e in after["entities"]}

    added = set(ae) - set(be)
    removed = set(be) - set(ae)
    modified = []
    for h in set(be) & set(ae):
        if be[h] != ae[h]:
            modified.append({"handle": h, "before": be[h], "after": ae[h]})

    return {
        "entity_delta": a["totals"]["entities"] - b["totals"]["entities"],
        "added": [ae[h] for h in added][:20],
        "removed": [be[h] for h in removed][:20],
        "modified": modified[:20],
        "layer_changes": {
            "before": b["layer_distribution"],
            "after": a["layer_distribution"],
        },
    }
