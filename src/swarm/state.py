"""LangGraph Swarm 共享状态"""
from typing import Any, Dict, List, TypedDict


class SwarmState(TypedDict, total=False):
    # 输入
    user_request: str
    drawing_path: str
    temp_output: str
    output_path: str
    backend: str

    # 图纸摘要（只有元数据，无几何原文——不发 API）
    drawing_summary: Dict[str, Any]

    # 知识库依据
    knowledge_refs: List[str]

    # Agent 决策
    plan: str
    generated_ops: str
    exec_result: Dict[str, Any]
    validation: Dict[str, Any]

    # 控制
    current_agent: str
    handoff_count: int
    max_handoffs: int
    needs_review: bool
    messages: List[Dict[str, str]]
    handoff_tools: List[Dict]

    # 结果
    final_output: str
    error: str
