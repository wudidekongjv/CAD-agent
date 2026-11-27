"""本地 LLM 客户端：Ollama 兼容 HTTP 接口，离线推理

隐私门在请求发出前校验端点，确保图纸数据不出内网。
"""

import json
from typing import Any, Dict, List, Optional

import requests

from .config import config


class LocalLLM:
    """本地 OpenAI 兼容客户端"""

    def __init__(self, base_url: Optional[str] = None, model: Optional[str] = None):
        self.base_url = (base_url or config.llm_base_url).rstrip("/")
        self.model = model or config.llm_model
        # 隐私门：构造时即校验
        config.validate_endpoint(self.base_url)

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.1,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        """调用本地模型，返回完整响应（含 tool_calls）"""
        config.check_kill_switch()

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            timeout=config.tool_timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]

    def simple(self, system: str, user: str) -> str:
        """便捷方法：纯文本生成"""
        msg = self.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        return msg.get("content", "")


# 延迟创建的全局客户端（避免导入时因端点不可达报错）
_llm: Optional[LocalLLM] = None


def get_llm() -> LocalLLM:
    global _llm
    if _llm is None:
        _llm = LocalLLM()
    return _llm
