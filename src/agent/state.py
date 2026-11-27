"""LangGraph 共享状态定义

所有节点读写同一份 State（类似共享黑板），而非 Agent 之间对话。
"""

from typing import Any, Dict, List, Optional, TypedDict


class CADState(TypedDict, total=False):
    # 输入
    user_request: str
    drawing_path: str
    output_path: str
    device_id: str
    task_id: str

    # 图纸上下文（Planner 节点读取）
    drawing_info: Dict[str, Any]

    # 规划结果
    plan: List[Dict[str, Any]]

    # 代码生成
    generated_ops: List[Dict[str, Any]]      # 结构化的 MCP 工具调用参数
    script: str                              # 可读的脚本（用于审计与展示）

    # 执行结果
    exec_result: Dict[str, Any]
    validation: Dict[str, Any]

    # 控制
    retry_count: int
    max_retries: int
    messages: List[Dict[str, str]]
    stage: str
    error: str
    final_output: str
