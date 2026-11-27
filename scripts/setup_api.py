# -*- coding: utf-8 -*-
"""API 配置向导：交互式生成 .env 并验证密钥可用性

用法：
    python scripts/setup_api.py           # 交互式配置
    python scripts/setup_api.py --check   # 仅检查当前配置状态
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / ".env"

PROVIDERS = {
    "1": {
        "name": "deepseek",
        "label": "DeepSeek（推荐，性价比高）",
        "env_key": "DEEPSEEK_API_KEY",
        "url": "https://platform.deepseek.com/api_keys",
        "model": "deepseek-chat",
    },
    "2": {
        "name": "openai",
        "label": "OpenAI GPT-4o",
        "env_key": "OPENAI_API_KEY",
        "url": "https://platform.openai.com/api-keys",
        "model": "gpt-4o",
    },
    "3": {
        "name": "qwen",
        "label": "通义千问 qwen-max",
        "env_key": "DASHSCOPE_API_KEY",
        "url": "https://dashscope.console.aliyun.com/apiKey",
        "model": "qwen-max",
    },
    "4": {
        "name": "local",
        "label": "本地 Ollama（无需密钥）",
        "env_key": None,
        "url": "",
        "model": "qwen3-32b",
    },
}


def load_dotenv_manual():
    """手动读取 .env（不依赖 python-dotenv）"""
    values = {}
    if ENV_FILE.exists():
        for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                values[k.strip()] = v.strip()
    return values


def check_status():
    """显示当前配置状态"""
    print("=" * 60)
    print("当前 API 配置状态")
    print("=" * 60)

    env = load_dotenv_manual()
    current = os.getenv("LLM_PROVIDER") or env.get("LLM_PROVIDER", "(未设置)")
    print(f"\n默认供应商: {current}")
    print(f"配置文件: {ENV_FILE} {'✓ 存在' if ENV_FILE.exists() else '✗ 不存在'}\n")

    print("供应商可用性：")
    for key, p in PROVIDERS.items():
        val = os.getenv(p["env_key"], "") if p["env_key"] else "local"
        env_val = env.get(p["env_key"], "") if p["env_key"] else "local"
        configured = bool(val or env_val)
        mark = "✓" if configured else "✗"
        print(f"  {mark} {p['label']:<28} {p['env_key'] or '无需密钥'}")

    print("\n提示：设置密钥后重启后端服务生效")
    print("=" * 60)


def interactive():
    """交互式配置"""
    print("=" * 60)
    print("CAD Agent API 配置向导")
    print("=" * 60)

    print("\n选择模型供应商：")
    for key, p in PROVIDERS.items():
        print(f"  [{key}] {p['label']}")

    choice = input("\n请输入选项 [1-4，默认1]: ").strip() or "1"
    if choice not in PROVIDERS:
        print("无效选项")
        return

    p = PROVIDERS[choice]
    lines = [
        "# CAD Agent 模型配置（由 setup_api.py 生成）",
        f"LLM_PROVIDER={p['name']}",
        f"LLM_MODEL={p['model']}",
        "",
    ]

    if p["env_key"]:
        print(f"\n请前往 {p['url']} 获取 API Key")
        key = input(f"输入 {p['env_key']}: ").strip()
        if not key:
            print("密钥为空，取消配置")
            return
        lines.append(f"{p['env_key']}={key}")
    else:
        url = input(f"本地模型端点 [http://127.0.0.1:11434/v1]: ").strip()
        model = input(f"模型名 [qwen3-32b]: ").strip()
        lines += [
            f"SWARM_LLM_URL={url or 'http://127.0.0.1:11434/v1'}",
            f"SWARM_LLM_MODEL={model or 'qwen3-32b'}",
        ]

    lines += [
        "",
        "# 其他配置",
        "CADAGENT_HOME=./cadagent_data",
        "CADAGENT_LAN=127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16",
    ]

    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n✓ 配置已写入 {ENV_FILE}")
    print("  重启后端服务后生效")
    print(f"\n当前配置：{p['label']} / {p['model']}")


if __name__ == "__main__":
    if "--check" in sys.argv:
        check_status()
    else:
        interactive()
