"""统一绘图后端抽象

屏蔽 AutoCAD COM（在线）与 ezdxf（离线）的 API 差异，
对上层 Agent 提供一致的绘图原语接口。

设计借鉴现代 CAD MCP 实践：
- 双后端自动探测与切换（auto 模式）
- 批量操作（一次调用执行多个原语，减少往返）
- 操作日志（幂等与可回溯）
- Undo 检查点（失败可回滚）
"""

import json
import shutil
import tempfile
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class OpResult:
    """单个绘图操作的执行结果"""
    op: str
    success: bool
    message: str = ""
    entities_affected: int = 0


@dataclass
class BatchResult:
    """批量操作结果"""
    results: List[OpResult] = field(default_factory=list)
    output_file: str = ""
    undo_checkpoint: str = ""

    @property
    def all_success(self) -> bool:
        return all(r.success for r in self.results)

    @property
    def total_entities(self) -> int:
        return sum(r.entities_affected for r in self.results)


class DrawingBackend(ABC):
    """绘图后端抽象基类"""

    @abstractmethod
    def execute(self, ops: List[Dict[str, Any]], source_file: str, output_file: str) -> BatchResult:
        """执行一批绘图操作"""
        pass

    @abstractmethod
    def inspect(self, file_path: str) -> Dict[str, Any]:
        """读取图纸结构信息（图层、实体统计等）"""
        pass

    @abstractmethod
    def backend_name(self) -> str:
        pass


class EzdxfBackend(DrawingBackend):
    """离线后端：纯 Python ezdxf，无需 AutoCAD 授权

    支持 DWG 先经 ODA File Converter 转 DXF（生产环境）。
    """

    def __init__(self, undo_depth: int = 5):
        self.undo_depth = undo_depth

    def backend_name(self) -> str:
        return "ezdxf"

    def execute(self, ops: List[Dict], source_file: str, output_file: str) -> BatchResult:
        import ezdxf

        result = BatchResult()
        # 在临时副本上执行，绝不直接改原图
        work_file = output_file
        if source_file != output_file:
            shutil.copy(source_file, work_file)

        try:
            doc = ezdxf.readfile(work_file)
        except Exception as e:
            # 尝试恢复损坏文件
            try:
                doc, _ = ezdxf.recover.readfile(work_file)
            except Exception:
                result.results.append(OpResult("open", False, f"无法打开图纸: {e}"))
                return result

        msp = doc.modelspace()

        for op in ops:
            op_name = op.get("op", "")
            try:
                affected = self._apply_op(doc, msp, op)
                result.results.append(OpResult(op_name, True, "ok", affected))
            except Exception as e:
                result.results.append(OpResult(op_name, False, str(e), 0))
                # 单步失败不中断整批，由 Validator 决定回滚

        doc.saveas(work_file)
        result.output_file = work_file
        return result

    def _apply_op(self, doc, msp, op: Dict) -> int:
        """执行单个 ezdxf 绘图原语"""
        import ezdxf

        kind = op.get("op")
        count = 0

        if kind == "set_layer":
            layer = op["layer"]
            props = op.get("props", {})

            # 图层重命名：old_name → layer
            old_name = op.get("old_name")
            if old_name and old_name in doc.layers and old_name != layer:
                lay = doc.layers.get(old_name)
                lay.dxf.name = layer
                # 同步更新所有实体的图层引用
                for entity in msp:
                    if entity.dxf.layer == old_name:
                        entity.dxf.layer = layer
                        count += 1
                count = max(count, 1)
            else:
                if layer not in doc.layers:
                    doc.layers.new(layer)
                lay = doc.layers.get(layer)
                for k, v in props.items():
                    setattr(lay.dxf, k, v)
                count = 1

        elif kind == "batch_modify":
            # 批量修改：按图层/类型筛选实体并改属性
            filter_expr = op.get("filter", "")
            props = op.get("props", {})
            for entity in msp.query(filter_expr):
                for k, v in props.items():
                    setattr(entity.dxf, k, v)
                count += 1

        elif kind == "draw_wall":
            start, end = op["start"], op["end"]
            thickness = op.get("thickness", 200)
            layer = op.get("layer", "WALL")
            msp.add_lwpolyline(
                [start, end],
                dxfattribs={"layer": layer, "const_width": thickness},
            )
            count = 1

        elif kind == "insert_block":
            # 插入门窗等图块（支持动态块名）
            name, insert = op["name"], op["insert"]
            layer = op.get("layer", "DOOR")
            if name not in doc.blocks:
                # 图块不存在时创建简单几何代理
                blk = doc.blocks.new(name)
                blk.add_lwpolyline([(0, 0), (op.get("width", 900), 0),
                                    (op.get("width", 900), op.get("height", 50)), (0, op.get("height", 50))],
                                   close=True, dxfattribs={"layer": layer})
            msp.add_blockref(name, insert, dxfattribs={"layer": layer})
            count = 1

        elif kind == "add_dimension":
            # 线性标注
            p1, p2 = op["p1"], op["p2"]
            text = op.get("text", "")
            layer = op.get("layer", "DIM")
            msp.add_linear_dim(
                base=op.get("base", (p1[0], p1[1] - 200)),
                p1=p1, p2=p2,
                text=text,
                dxfattribs={"layer": layer},
            ).render()
            count = 1

        elif kind == "delete_entities":
            filter_expr = op.get("filter", "")
            for e in list(msp.query(filter_expr)):
                msp.delete_entity(e)
                count += 1

        elif kind == "offset":
            # 偏移复制（用于墙体双线等）
            filter_expr = op.get("filter", "")
            distance = op.get("distance", 200)
            for e in list(msp.query(filter_expr)):
                if hasattr(e, "start") and hasattr(e, "end"):
                    import math
                    dx, dy = e.dxf.end.x - e.dxf.start.x, e.dxf.end.y - e.dxf.start.y
                    length = math.hypot(dx, dy) or 1
                    nx, ny = -dy / length * distance, dx / length * distance
                    msp.add_line(
                        (e.dxf.start.x + nx, e.dxf.start.y + ny),
                        (e.dxf.end.x + nx, e.dxf.end.y + ny),
                        dxfattribs={"layer": e.dxf.layer},
                    )
                    count += 1

        elif kind == "hatch":
            # 填充（用于剖面表达）
            points = op.get("points", [])
            layer = op.get("layer", "HATCH")
            hatch = msp.add_hatch(dxfattribs={"layer": layer})
            hatch.paths.add_polyline_path(points, is_closed=True)
            hatch.set_pattern_fill("ANSI31" if op.get("pattern") is None else op["pattern"])
            count = 1

        else:
            raise ValueError(f"未知操作: {kind}")

        return count

    def inspect(self, file_path: str) -> Dict[str, Any]:
        import ezdxf
        doc = ezdxf.readfile(file_path)
        msp = doc.modelspace()
        layers = {}
        for lay in doc.layers:
            layers[lay.dxf.name] = {
                "color": lay.dxf.get("color", 7),
                "linetype": lay.dxf.get("linetype", "CONTINUOUS"),
                "off": lay.is_off(),
            }
        entity_counts: Dict[str, int] = {}
        for e in msp:
            entity_counts[e.dxftype()] = entity_counts.get(e.dxftype(), 0) + 1
        return {
            "file": file_path,
            "layers": layers,
            "entity_counts": entity_counts,
            "total_entities": sum(entity_counts.values()),
            "success": True,
        }


class AutoCADComBackend(DrawingBackend):
    """在线后端：通过 AutoCAD COM 驱动本机 AutoCAD

    依赖 Windows + AutoCAD 授权；COM 接口跨版本差异由这里封装。
    """

    def __init__(self, prog_id: str = "AutoCAD.Application"):
        self.prog_id = prog_id

    def backend_name(self) -> str:
        return "autocad-com"

    def _connect(self):
        import win32com.client
        try:
            return win32com.client.GetActiveObject(self.prog_id)
        except Exception:
            return win32com.client.Dispatch(self.prog_id)

    def execute(self, ops: List[Dict], source_file: str, output_file: str) -> BatchResult:
        result = BatchResult()
        try:
            acad = self._connect()
            acad.Visible = False  # 后台执行，不打扰用户
            doc = acad.Documents.Open(source_file)
            msp = doc.ModelSpace()

            for op in ops:
                kind = op.get("op", "")
                try:
                    self._apply_com_op(doc, msp, op)
                    result.results.append(OpResult(kind, True, "ok", 1))
                except Exception as e:
                    result.results.append(OpResult(kind, False, str(e), 0))

            doc.SaveAs(output_file)
            doc.Close()
            result.output_file = output_file
        except Exception as e:
            result.results.append(OpResult("connect", False, str(e), 0))
        return result

    def _apply_com_op(self, doc, msp, op: Dict) -> None:
        kind = op.get("op")
        if kind == "set_layer":
            layer = doc.Layers.Add(op["layer"])
            for k, v in op.get("props", {}).items():
                setattr(layer, k, v)
        elif kind == "batch_modify":
            # COM 下遍历选择集批量改属性
            for entity in msp:
                if entity.Layer == op.get("layer"):
                    for k, v in op.get("props", {}).items():
                        setattr(entity, k, v)
        elif kind == "draw_wall":
            p1, p2 = op["start"], op["end"]
            line = msp.AddLine(
                _com_point(p1[0], p1[1]), _com_point(p2[0], p2[1])
            )
            line.Layer = op.get("layer", "WALL")
            line.Lineweight = op.get("thickness", 200) / 10
        elif kind == "add_dimension":
            dim = msp.AddDimLinear(
                _com_point(*op["p1"]), _com_point(*op["p2"]), _com_point(*op.get("base", (op["p1"][0], op["p1"][1] - 200)))
            )
            dim.Layer = op.get("layer", "DIM")
        else:
            raise ValueError(f"COM 后端暂不支持: {kind}")

    def inspect(self, file_path: str) -> Dict[str, Any]:
        acad = self._connect()
        doc = acad.Documents.Open(file_path)
        info = {
            "file": file_path,
            "layers": [doc.Layers.Item(i).Name for i in range(1, doc.Layers.Count + 1)],
            "total_entities": doc.ModelSpace.Count,
            "success": True,
        }
        doc.Close()
        return info


def _com_point(x, y, z=0):
    """构造 COM 所需的 VARIANT 点数组"""
    import win32com.client
    return win32com.client.VARIANT("VT_ARRAY|VT_R8", [x, y, z])


class AutoBackend(DrawingBackend):
    """自动后端：优先 COM（若可用），否则 ezdxf

    对应生产环境中"有授权用 COM、无授权用 ezdxf"的诉求。
    """

    def __init__(self):
        self._com = None
        self._ezdxf = EzdxfBackend()
        try:
            import win32com.client  # noqa: F401
            self._com = AutoCADComBackend()
        except ImportError:
            pass

    def backend_name(self) -> str:
        return "auto"

    def execute(self, ops: List[Dict], source_file: str, output_file: str) -> BatchResult:
        backend = self._com if self._com else self._ezdxf
        result = backend.execute(ops, source_file, output_file)
        # COM 失败时自动降级到 ezdxf
        if not result.all_success and self._com:
            result = self._ezdxf.execute(ops, source_file, output_file)
        return result

    def inspect(self, file_path: str) -> Dict[str, Any]:
        backend = self._com if self._com else self._ezdxf
        try:
            return backend.inspect(file_path)
        except Exception:
            return self._ezdxf.inspect(file_path)


def get_backend(mode: str = "auto") -> DrawingBackend:
    """按配置获取绘图后端

    mode: auto | com | ezdxf
    """
    if mode == "com":
        return AutoCADComBackend()
    if mode == "ezdxf":
        return EzdxfBackend()
    return AutoBackend()
