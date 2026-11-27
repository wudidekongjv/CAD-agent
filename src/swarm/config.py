"""Swarm 运行时配置：离线优先 + 安全护栏

所有约束在代码中强制执行，而非文档建议：
- allow_cloud=False：阻止任何非本地 LLM 端点
- kill_switch：文件存在时立即停止运行与文件系统操作
- allowed_roots：文件系统操作白名单目录
- max_turns：Agent 循环轮次上限，防止无限循环
"""

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import List


@dataclass
class SwarmConfig:
    # LLM 端点：本地 Ollama 兼容格式
    llm_base_url: str = os.getenv("SWARM_LLM_URL", "http://127.0.0.1:11434/v1")
    llm_model: str = os.getenv("SWARM_LLM_MODEL", "qwen3-32b")
    allow_cloud: bool = False  # 硬编码 False，离线优先

    # 轮次上限
    max_turns: int = 12
    max_handoffs: int = 8

    # 文件系统沙箱
    allowed_roots: List[Path] = field(default_factory=lambda: [
        Path(os.getenv("CADAGENT_HOME", "./cadagent_data")).resolve(),
        Path("./examples").resolve(),
    ])

    # kill-switch 文件
    kill_switch_path: Path = Path(os.getenv("SWARM_KILL_SWITCH", "./.kill_switch"))

    # 工具超时
    tool_timeout: int = 120

    def validate_endpoint(self, url: str) -> None:
        """拒绝非本地 LLM 端点（隐私门）"""
        if self.allow_cloud:
            return
        local_markers = ("127.0.0.1", "localhost", "::1", "0.0.0.0")
        if not any(m in url for m in local_markers):
            raise PermissionError(
                f"Privacy gate: non-local LLM endpoint blocked ({url}). "
                "Set allow_cloud=True explicitly to override."
            )

    def check_kill_switch(self) -> None:
        """检查 kill-switch"""
        if self.kill_switch_path.exists():
            raise RuntimeError("Kill-switch engaged: swarm halted")

    def check_path(self, path: Path) -> None:
        """检查文件路径是否在允许的目录内"""
        resolved = path.resolve()
        if not any(str(resolved).startswith(str(root)) for root in self.allowed_roots):
            raise PermissionError(f"Path outside allowed_roots: {path}")


# 全局配置实例
config = SwarmConfig()
