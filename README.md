# CAD Agent · 施工图辅助深化

> 基于 Swarm 多 Agent 架构的建筑 CAD 施工图深化系统。六个专职 Agent 通过 handoff 自主协作，全程本地离线运行，单张图纸标注与图层整理耗时由约 30 分钟降至 10 分钟以内。

## 界面

![CAD Agent 施工图深化工作台](docs/images/frontend-preview.png)

空间计算风格界面：建筑摄影背景、深色毛玻璃悬浮面板、圆形图标导航栏、消息式任务列表。

## 核心特性

- **Swarm 架构**：Agent + Tools + Handoffs 三原语，Agent 自主决定把控制权移交给谁，拓扑运行时涌现而非预设
- **六个专职 Agent**：Planner / Coder / Executor / Validator / Deliver / Reviewer，各自持有独立工具集
- **全程本地离线**：本地 Ollama 兼容 LLM 端点，隐私门硬阻止非本地地址，图纸数据不出内网
- **MCP 工具层**：工具发现（按需加载）、批处理（cad_batch）、垂直工具包（core/arch/mech）
- **双后端抽象**：ezdxf（离线）与 AutoCAD COM（在线）统一接口，auto 模式自动探测与降级
- **安全护栏**：kill-switch、轮次上限、文件系统沙箱、临时副本执行、校验通过才写回原图

## Swarm 协作流程

```
用户任务 + DXF 图纸
        │
        ▼
   [Planner] 读取图纸 → 制定计划
        │ transfer_to_Coder
        ▼
   [Coder] 计划 → MCP 工具调用参数
        │ transfer_to_Executor
        ▼
   [Executor] 临时副本执行
        │ transfer_to_Validator
        ▼
   [Validator] ─┬─ 通过 → [Deliver] 交付
                ├─ 参数问题 → transfer_to_Coder 重生成
                ├─ 需求偏差 → transfer_to_Planner 重规划
                └─ 需人工 → transfer_to_Reviewer 复核
```

**与固定流水线的区别**：固定流水线节点顺序预设，条件边只在有限分支中选择；Swarm 中每个 Agent 持有 `transfer_to_X` 工具，自主决定下一步交给谁，能处理"校验失败后不同性质的回退"。

## Agent 团队

| Agent | 职责 | 可移交目标 |
|---|---|---|
| Planner | 读取图纸结构、理解需求、制定计划 | Coder |
| Coder | 计划转工具调用参数、检查参数完整性 | Executor / Planner |
| Executor | 临时副本执行、失败归因 | Validator / Coder / Planner |
| Validator | 规则校验 + 语义一致性 | Deliver / Coder / Planner / Reviewer |
| Deliver | 汇总交付说明 | —（终点） |
| Reviewer | 人工复核协调 | Planner / Deliver |

## MCP 工具包

| 包 | 工具 | 用途 |
|---|---|---|
| core | `drawing_info` / `cad_batch` / `undo_checkpoint` | 图纸读取 / 批量操作 / 回滚 |
| arch | `draw_wall` / `insert_opening` / `batch_dimension` / `layer_audit` / `room_boundary` | 建筑深化 |
| mech | `add_hatch` / `offset_copy` | 构造表达 |

工具发现机制 `search_tools(query, pack)` 按需返回工具描述，避免全量工具占用上下文；批处理 `cad_batch` 一次调用完成多个原语。

## 离线与安全

| 机制 | 实现 |
|---|---|
| 隐私门 | `config.validate_endpoint()` 拒绝非本地 LLM 地址 |
| kill-switch | `.kill_switch` 文件存在即停止所有运行与文件操作 |
| 轮次上限 | `max_turns=12` / `max_handoffs=8`，防止无限循环 |
| 文件沙箱 | `allowed_roots` 限定 Agent 可访问的目录 |
| 执行安全 | 临时副本执行，校验通过才写回原图 |
| 多用户隔离 | 局域网 IP 白名单 + 设备指纹 + `outputs/{role}/{user_id}/{task_id}/` |

## 快速开始

```bash
git clone https://github.com/wudidekongjv/CAD-agent.git
cd CAD-agent
cd docker && docker compose up -d
# 局域网访问 http://<服务器IP>:5173
```

本地 LLM 默认 `http://127.0.0.1:11434/v1`（Ollama 兼容），可通过 `SWARM_LLM_URL` 与 `SWARM_LLM_MODEL` 配置。

## 技术栈

| 层 | 技术 |
|---|---|
| Agent 编排 | 自研轻量 Swarm 运行时（Agent / Tools / Handoffs） |
| LLM | 本地 Qwen3-32B（Ollama 兼容端点） |
| 工具协议 | MCP（FastMCP + stdio） |
| 绘图引擎 | ezdxf / AutoCAD COM / auto |
| 后端 | FastAPI + SQLite + Redis + SSE |
| 前端 | Vue3 + Vite + 毛玻璃空间计算 UI |
| 部署 | Docker Compose（局域网） |

## 仓库结构

```
├── src/
│   ├── swarm/
│   │   ├── config.py      # 隐私门 / kill-switch / 沙箱 / 轮次上限
│   │   ├── llm.py         # 本地 LLM 客户端
│   │   ├── core.py        # Swarm 运行时（Agent 循环 + handoff）
│   │   └── agents.py      # 六个 CAD Agent 定义
│   ├── mcp/cad_mcp_server.py
│   ├── backend/drawing_backend.py
│   └── api/main.py
├── web/                   # Vue3 毛玻璃前端
├── docker/
├── docs/
└── examples/
```

## License

MIT
