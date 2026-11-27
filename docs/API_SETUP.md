# API 配置指南

系统默认使用云端模型（能力显著强于本地 32B），未配置密钥时自动降级到规则引擎——核心功能仍可用，但规划质量下降。

## 方式一：配置向导（推荐）

```bash
python scripts/setup_api.py
```

交互式选择供应商、粘贴 API Key，自动生成 `.env`。

检查当前配置：

```bash
python scripts/setup_api.py --check
```

## 方式二：手动配置

复制模板并填写：

```bash
cp .env.example .env
# 编辑 .env，填入密钥
```

 `.env` 内容示例（DeepSeek）：

```env
LLM_PROVIDER=deepseek
LLM_MODEL=deepseek-chat
DEEPSEEK_API_KEY=sk-你的密钥
```

## 获取 API Key

| 供应商 | 推荐度 | 获取地址 | 环境变量 |
|---|---|---|---|
| **DeepSeek** | ★★★ 推荐 | https://platform.deepseek.com/api_keys | `DEEPSEEK_API_KEY` |
| OpenAI | ★★ | https://platform.openai.com/api-keys | `OPENAI_API_KEY` |
| 通义千问 | ★★ | https://dashscope.console.aliyun.com/apiKey | `DASHSCOPE_API_KEY` |
| 本地 Ollama | 离线场景 | 无需密钥 | `SWARM_LLM_URL` / `SWARM_LLM_MODEL` |

DeepSeek 性价比最高，约 ¥1/百万 token，适合本项目的高频调用。

## 生效方式

1. **重启后端服务**（`.env` 在启动时读取）
2. 打开前端 → 设置面板 → 模型供应商，确认目标供应商显示"✓ 可用"
3. 点击卡片切换，立即生效

也可通过接口切换：

```bash
curl -X POST http://localhost:8000/api/models/switch \
  -H "X-Device-Id: <你的设备ID>" \
  -d "provider=deepseek"
```

## 降级链（自动）

```
deepseek → qwen → openai → local → 规则引擎
```

任一供应商失败（401/限流/超时）自动尝试下一个。全部失败时规则引擎接管——基于关键词与元数据确定性生成操作计划，核心功能不中断。

## Docker 部署

`docker-compose.yml` 已配置 `env_file: ../.env`，在项目根目录创建 `.env` 后：

```bash
cd docker && docker compose up -d
```

密钥通过环境变量注入容器，不写入镜像。

## 数据安全

- 发送至 API 的只有**图纸结构摘要**（图层名、实体统计、块名），不含坐标与几何原文
- `.env` 已在 `.gitignore` 中排除，不会入库
- 切换模型后立即生效，无需重启

## 验证配置是否生效

```bash
# 1. 检查环境变量读取
python scripts/setup_api.py --check

# 2. 查看后端识别的供应商状态
curl -s http://localhost:8000/api/models/providers \
  -H "X-Device-Id: <设备ID>" | python -m json.tool

# 3. 提交一个任务，观察 validation.model 字段确认使用的模型
```
