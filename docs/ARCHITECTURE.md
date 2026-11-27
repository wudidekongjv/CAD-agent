# 架构设计

## 为什么从固定流水线改为 Swarm

固定流水线（Planner→Coder→Executor→Validator）的局限：
- 节点顺序预设，只能通过有限的条件边选择分支
- 校验失败时只能"回到 Planner"，无法区分失败性质
- Agent 没有自主决策权，只是流水线的阶段

Swarm 的核心改进：
- **Handoff 作为协调原语**：每个 Agent 持有 `transfer_to_X` 工具，执行即跳出当前循环，由 Swarm 读取路由并切换 Agent
- **运行时涌现拓扑**：Agent 根据当前情况自主决定移交目标，Validator 可针对参数问题交给 Coder、需求偏差交给 Planner、需人工交给 Reviewer
- **轻量**：Agent + Tools + Handoffs 三原语，无需重型框架

## Swarm 运行时五个原语

1. **LLM 接口**：本地 Ollama 兼容客户端
2. **工具注册表**：函数签名 + docstring 自动生成 JSON Schema
3. **Agent 循环**：reason → tool_calls → observe → repeat，max_turns 防死循环
4. **Handoff**：工具名以 `transfer_to_` 开头且返回目标 Agent，即切换控制权
5. **Swarm**：读取 handoff，压缩历史为交接摘要，启动新 Agent 循环

工具异常被封装成 error 字符串返回给模型，让 Agent 观察-重试而不是崩溃。失败是数据而非异常。

## 安全护栏（代码强制）

| 护栏 | 实现位置 | 行为 |
|---|---|---|
| 隐私门 | `config.validate_endpoint()` | 拒绝非 127.0.0.1/localhost/::1 的 LLM 地址 |
| kill-switch | `config.check_kill_switch()` | 每次循环与文件操作前检查，文件存在即抛异常 |
| 轮次上限 | `max_turns=12` / `max_handoffs=8` | 超限降级返回，不无限循环 |
| 文件沙箱 | `config.check_path()` | 文件操作限定在 allowed_roots |
| 执行隔离 | Executor Agent | 临时副本执行，校验通过才写回 |

这些是代码中的强制检查，不是文档中的建议。

## 双后端抽象

```
Agent → MCP 工具 → DrawingBackend 接口
                      ├─ EzdxfBackend      （离线，纯 Python，无授权依赖）
                      ├─ AutoCADComBackend （在线，Windows + AutoCAD）
                      └─ AutoBackend       （自动探测 + 失败降级）
```

AutoBackend 优先尝试 COM，失败时自动降级 ezdxf；屏蔽 AutoCAD 版本兼容（R2000–R2024）、授权差异与平台差异。DWG 在离线模式下先转 DXF。

## 工具层设计

- **工具发现**：`search_tools(query, pack)` 按需返回工具描述，避免一次性加载全部工具占用上下文
- **批处理**：`cad_batch` 一次传入操作列表，在同一图纸上顺序执行，避免几十次工具往返
- **垂直工具包**：core（通用）/ arch（建筑）/ mech（构造），按场景启用
- **操作日志**：每次工具调用记录，支持 undo 检查点与任务审计

## 离线运行

默认 LLM 端点 `http://127.0.0.1:11434/v1`（Ollama 兼容格式）。所有推理、状态与文件均在本地：
- 图纸不出内网
- 提示词不发送第三方
- 无外部 API 依赖

如需切换到其他本地模型服务，设置 `SWARM_LLM_URL` 与 `SWARM_LLM_MODEL` 环境变量；隐私门仍会拒绝任何非本地地址。
