"""轻量向量存储（零外部依赖）

用 JSON 持久化 chunks 与向量，余弦相似度检索。
生产环境可替换为 Milvus/Chroma，接口保持一致。
"""

import json
import math
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

STORE_PATH = Path(os.getenv("KNOWLEDGE_STORE", "./cadagent_data/knowledge/store.json"))
STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load() -> Dict:
    if STORE_PATH.exists():
        try:
            return json.loads(STORE_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"chunks": [], "vectors": []}


def _save(data: Dict) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STORE_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _tokenize(text: str) -> List[str]:
    """中英文混合分词（轻量）

    中文用 2-gram 切分，保证"图层命名"能匹配"图层命名应采用"——
    连续中文若整体成 token，短查询永远命不中长文档。
    """
    tokens = []
    # 中文：提取连续中文串，再切 2-gram
    for run in re.findall(r"[\u4e00-\u9fa5]+", text):
        if len(run) == 1:
            tokens.append(run)
        else:
            for i in range(len(run) - 1):
                tokens.append(run[i:i + 2])
    # 英文/数字/下划线
    tokens.extend(re.findall(r"[a-zA-Z_]+|\d+", text.lower()))
    return tokens


def _embed(text: str) -> List[float]:
    """简易嵌入：词频向量（生产环境替换为 bge-large-zh-v1.5）

    这里用哈希技巧 + 词频，保证零依赖可运行；接口与真实 embedding 一致。
    """
    tokens = _tokenize(text)
    vec = [0.0] * 256
    for t in tokens:
        idx = hash(t) % 256
        vec[idx] += 1.0
    # L2 归一化
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def add_chunks(chunks: List[Dict[str, Any]]) -> int:
    """入库：chunks = [{text, source, page, section}]"""
    data = _load()
    for c in chunks:
        data["chunks"].append(c)
        data["vectors"].append(_embed(c["text"]))
    _save(data)
    return len(chunks)


def vector_search(query: str, top_k: int = 5) -> List[Dict]:
    """向量检索"""
    data = _load()
    if not data["chunks"]:
        return []
    qv = _embed(query)
    scored = []
    for i, vec in enumerate(data["vectors"]):
        scored.append((_cosine(qv, vec), i))
    scored.sort(reverse=True)
    results = []
    for score, idx in scored[:top_k]:
        if score <= 0:
            continue
        item = dict(data["chunks"][idx])
        item["score"] = round(score, 4)
        results.append(item)
    return results


def bm25_search(query: str, top_k: int = 5) -> List[Dict]:
    """BM25 关键词检索（简化版 TF-IDF）"""
    data = _load()
    qtokens = _tokenize(query)
    if not qtokens or not data["chunks"]:
        return []

    results = []
    for i, chunk in enumerate(data["chunks"]):
        tokens = _tokenize(chunk["text"])
        score = sum(tokens.count(t) for t in qtokens)
        if score > 0:
            item = dict(chunk)
            item["score"] = float(score)
            results.append(item)
    results.sort(key=lambda x: x["score"], reverse=True)
    return results[:top_k]


def hybrid_search(query: str, top_k: int = 5) -> List[Dict]:
    """混合检索：向量 + BM25 → RRF 融合"""
    vr = vector_search(query, top_k * 2)
    br = bm25_search(query, top_k * 2)

    # RRF 融合
    scores: Dict[str, float] = {}
    items: Dict[str, Dict] = {}
    k = 60
    for rank, item in enumerate(vr):
        key = item.get("id", str(item["text"][:50]))
        scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
        items[key] = item
    for rank, item in enumerate(br):
        key = item.get("id", str(item["text"][:50]))
        scores[key] = scores.get(key, 0) + 1 / (k + rank + 1)
        items[key] = item

    sorted_keys = sorted(scores, key=lambda x: scores[x], reverse=True)[:top_k]
    out = []
    for key in sorted_keys:
        item = items[key]
        item["rrf_score"] = round(scores[key], 4)
        out.append(item)
    return out


def stats() -> Dict[str, Any]:
    data = _load()
    sources = {}
    for c in data["chunks"]:
        sources[c.get("source", "unknown")] = sources.get(c.get("source", "unknown"), 0) + 1
    return {
        "total_chunks": len(data["chunks"]),
        "sources": sources,
        "store_path": str(STORE_PATH),
    }


def clear() -> None:
    _save({"chunks": [], "vectors": []})
