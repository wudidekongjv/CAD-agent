"""CAD 规范知识库

文档入库 → 分块 → 索引 → 混合检索 → 规范校验
为 Planner 与 Validator 提供可溯源的规范依据。
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List

from .store import add_chunks, hybrid_search, stats, clear

KNOWLEDGE_DOCS = Path(os.getenv("KNOWLEDGE_DOCS", "./cadagent_data/knowledge/docs"))
KNOWLEDGE_DOCS.mkdir(parents=True, exist_ok=True)

# 内置制图规范（首启自动入库，保证开箱即用）
BUILTIN_STANDARDS = [
    {
        "source": "建筑制图规范-图层命名",
        "section": "2.1 图层命名",
        "text": "图层命名应采用 ARCH_ 前缀，后接专业代码与构件类型，如 ARCH_WALL、ARCH_DOOR、ARCH_WINDOW。禁止使用 0、Defpoints、temp 等默认图层名作为工作图层。图层颜色应按专业统一：墙体白色、门窗黄色、标注绿色、轴线红色。",
    },
    {
        "source": "建筑制图规范-标注样式",
        "section": "3.2 尺寸标注",
        "text": "尺寸标注样式应统一为 ARCH_DIM，箭头大小为 2.5mm，文字高度为 3.5mm，尺寸线偏离距离为 1.5mm。轴线间距标注应放置在图纸外侧，门窗洞口尺寸应单独标注。禁止标注文字与尺寸线重叠。",
    },
    {
        "source": "建筑制图规范-墙厚",
        "section": "4.1 墙体",
        "text": "常规住宅承重墙厚度为 200mm，分户墙为 200mm，室内隔墙为 100mm。外墙应绘制双线表示保温层。墙体线宽应为 0.35mm，门窗线宽为 0.25mm，家具线宽为 0.18mm。",
    },
    {
        "source": "建筑制图规范-门窗",
        "section": "5.1 门窗洞口",
        "text": "入户门宽度不小于 900mm，卧室门宽度 900mm，卫生间门宽度 700mm。窗台高度通常为 900mm，落地窗窗台为 0mm。门窗编号格式为 M-1、C-1，同一图纸内不得重复。",
    },
    {
        "source": "施工图深化流程规范",
        "section": "1.3 深化要求",
        "text": "施工图深化应完成：图层清理与规范化、尺寸标注完整性检查、门窗表与图纸一致性核对、节点详图索引。深化成果应保留原始图层结构，修改需在临时副本执行并经校验后方可覆盖原图。",
    },
]


def initialize_builtin() -> int:
    """首次启动入库内置规范"""
    if stats()["total_chunks"] == 0:
        chunks = []
        for i, s in enumerate(BUILTIN_STANDARDS):
            chunks.append({
                "id": f"builtin_{i}",
                "text": s["text"],
                "source": s["source"],
                "section": s["section"],
                "page": 0,
            })
        return add_chunks(chunks)
    return 0


def ingest_document(path: str, source_name: str = "") -> Dict[str, Any]:
    """文档入库：读取 PDF/DOCX/TXT → 语义分块 → 向量化

    分块策略：按段落与标题切分，每块 128-512 字符，overlap 50。
    """
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(path)

    suffix = p.suffix.lower()
    if suffix in (".txt", ".md"):
        text = p.read_text(encoding="utf-8", errors="replace")
    elif suffix == ".pdf":
        try:
            import fitz
            doc = fitz.open(str(p))
            text = "\n".join(page.get_text() for page in doc)
        except ImportError:
            raise RuntimeError("PDF 解析需要 pymupdf，请安装 pip install pymupdf")
    elif suffix in (".docx",):
        try:
            from docx import Document
            doc = Document(str(p))
            text = "\n".join(par.text for par in doc.paragraphs)
        except ImportError:
            raise RuntimeError("DOCX 解析需要 python-docx")
    else:
        raise ValueError(f"不支持的格式: {suffix}")

    # 语义分块：按空行/标题切分
    sections = re.split(r"\n\s*\n|(?=第[一二三四五六七八九十\d]+[章节])", text)
    chunks = []
    source = source_name or p.name
    for i, sec in enumerate(sections):
        sec = sec.strip()
        if len(sec) < 20:
            continue
        # 长段落二次切分
        if len(sec) > 512:
            for j in range(0, len(sec), 462):
                part = sec[j:j + 512]
                chunks.append({"id": f"{source}_{i}_{j}", "text": part,
                               "source": source, "section": "", "page": 0})
        else:
            chunks.append({"id": f"{source}_{i}", "text": sec,
                           "source": source, "section": "", "page": 0})

    added = add_chunks(chunks)
    return {"file": p.name, "chunks_added": added, "source": source}


def retrieve_standards(query: str, top_k: int = 5) -> List[Dict[str, Any]]:
    """规范检索（混合检索），供 Agent 使用"""
    return hybrid_search(query, top_k=top_k)


def validate_against_standards(drawing_path: str, standards: List[Dict]) -> Dict[str, Any]:
    """基于知识库规范校验图纸

    检查项来自检索到的规范文本，输出可溯源的违规清单。
    """
    import ezdxf

    errors = []
    passed_checks = []
    try:
        doc = ezdxf.readfile(drawing_path)
        layers = [lay.dxf.name for lay in doc.layers]
    except Exception as e:
        return {"passed": False, "errors": [f"无法读取图纸: {e}"], "checked": []}

    # 从规范中提取规则（简化：关键词匹配）
    rules_text = " ".join(s["text"] for s in standards)
    forbidden = ["0", "Defpoints", "temp"]
    if "ARCH_" in rules_text:
        for layer in layers:
            if layer in forbidden:
                errors.append({"rule": "图层命名", "detail": f"禁用图层名: {layer}",
                               "source": s.get("source", "规范") if (s := standards[0] if standards else {}) else ""})
            elif not layer.startswith("ARCH_"):
                errors.append({"rule": "图层命名", "detail": f"图层 {layer} 不符合 ARCH_ 前缀",
                               "source": standards[0].get("source", "规范") if standards else ""})
        passed_checks.append("图层命名规范")

    # 实体数量检查
    entity_count = sum(1 for _ in doc.modelspace())
    if entity_count == 0:
        errors.append({"rule": "图纸完整性", "detail": "图纸无实体", "source": "施工图深化流程规范"})
    else:
        passed_checks.append(f"实体数量: {entity_count}")

    return {
        "passed": len(errors) == 0,
        "errors": errors,
        "checked": passed_checks,
        "sources": list({s.get("source", "") for s in standards}),
    }


def list_sources() -> List[Dict[str, Any]]:
    """列出知识库来源"""
    s = stats()
    return [{"source": k, "chunks": v} for k, v in s["sources"].items()]


def reset_knowledge() -> None:
    """清空并重建内置规范"""
    clear()
    initialize_builtin()


# 首启自动入库
initialize_builtin()
