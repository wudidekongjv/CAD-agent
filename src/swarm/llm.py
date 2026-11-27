"""LLM 客户端：API 为主，本地为辅

设计决策：
- 云端模型（DeepSeek-V3 / GPT-4o / qwen-max）能力显著强于本地 32B，作为主力
- 本地 Ollama 端点作为离线降级与隐私敏感场景备选
- 图纸原文（坐标、几何）绝不发送到 API；只发送结构摘要（图层名、实体统计）
"""

import os
from typing import Any, Dict, List, Optional

import requests

from .config import config


# 支持的 API 供应商（OpenAI 兼容格式）
PROVIDERS = {
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o",
        "env_key": "OPENAI_API_KEY",
    },
    "qwen": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-max",
        "env_key": "DASHSCOPE_API_KEY",
    },
    "local": {
        "base_url": os.getenv("SWARM_LLM_URL", "http://127.0.0.1:11434/v1"),
        "model": os.getenv("SWARM_LLM_MODEL", "qwen3-32b"),
        "env_key": None,
    },
}


class LLMClient:
    """统一的 LLM 客户端，支持 API 与本地模型切换"""

    def __init__(self, provider: Optional[str] = None, model: Optional[str] = None):
        self.provider = provider or os.getenv("LLM_PROVIDER", "deepseek")
        if self.provider not in PROVIDERS:
            raise ValueError(f"Unknown provider: {self.provider}. Choose from {list(PROVIDERS)}")

        cfg = PROVIDERS[self.provider]
        self.base_url = cfg["base_url"].rstrip("/")
        self.model = model or os.getenv("LLM_MODEL", cfg["model"])
        self.env_key = cfg["env_key"]

        # 隐私检查：本地模型才需要严格校验端点；API 模式由用户显式选择
        if self.provider == "local":
            config.validate_endpoint(self.base_url)

        # API Key（本地模式不需要）
        self.api_key = os.getenv(self.env_key, "") if self.env_key else ""

    def chat(
        self,
        messages: List[Dict[str, str]],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.1,
        max_tokens: int = 4096,
    ) -> Dict[str, Any]:
        config.check_kill_switch()

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers=headers,
            timeout=config.tool_timeout,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]

    def simple(self, system: str, user: str) -> str:
        msg = self.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ])
        return msg.get("content", "")

    def describe(self) -> Dict[str, str]:
        return {
            "provider": self.provider,
            "model": self.model,
            "base_url": self.base_url,
            "mode": "api" if self.provider != "local" else "local",
            "key_configured": bool(self.api_key) if self.env_key else True,
        }


# 全局客户端（延迟创建，支持运行时切换）
_client: Optional[LLMClient] = None


def get_llm(provider: Optional[str] = None) -> LLMClient:
    global _client
    if _client is None or (provider and provider != _client.provider):
        _client = LLMClient(provider=provider)
    return _client


def set_provider(provider: str) -> LLMClient:
    """运行时切换模型供应商"""
    global _client
    _client = LLMClient(provider=provider)
    return _client


def available_providers() -> List[Dict[str, Any]]:
    """列出所有可用供应商及其配置状态"""
    result = []
    for name, cfg in PROVIDERS.items():
        key_set = bool(os.getenv(cfg["env_key"])) if cfg["env_key"] else True
        result.append({
            "name": name,
            "model": cfg["model"],
            "base_url": cfg["base_url"],
            "available": key_set,
            "mode": "local" if name == "local" else "api",
        })
    return result
