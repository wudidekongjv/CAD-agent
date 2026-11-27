# CAD Agent · 施工图辅助深化

> 基于 LangGraph 多 Agent 编排与 MCP 工具层的建筑 CAD 施工图深化系统。自然语言驱动，规划→生成→执行→校验闭环，单张图纸标注与图层整理耗时由约 30 分钟降至 10 分钟以内。

局域网多用户部署，设备指纹自动登录，图纸按角色与用户隔离存储。

## 界面

![CAD Agent 施工图深化工作台](docs/images/frontend-preview.png)

界面采用液态玻璃设计语言：浅色玻璃卡片、工程蓝主调、大圆角。左侧为深化记录，中央为四节点执行流水线与图纸预览，底部支持拖拽上传 DXF/DWG 图纸。

## 核心能力

- **多 Agent 编排**：LangGraph StateGraph 构建 Planner → Coder → Executor → Validator 四节点流水线，含"校验失败回退重规划"条件边（最多 3 次）
- **MCP 工具层**：绘图原语封装为 MCP 工具，支持工具发现（按需加载工具描述）、批处理（一次调用执行多步）、垂直工具包（core/arch/mech）
- **双后端抽象**：在线 AutoCAD COM 与离线 ezdxf 统一接口，auto 模式自动探测与降级，覆盖有无 CAD 授权的工作环境
- **安全执行**：脚本在临时副本执行，规则校验 + 语义校验通过后才写回原图
- **规范沉淀**：图层命名、标注样式等规则固化为可复用规则库

## 架构

```
用户自然语言需求 + DXF 图纸
            │
            ▼
   [Planner] 读取图纸结构 → 生成操作计划
            │  (条件边：失败回退，最多3次)
            ▼
   [Coder]   计划 → MCP 工具调用参数
            │
            ▼
   [Executor] 临时副本上执行 ezdxf/COM 脚本
            │
            ▼
   [Validator] 规则校验 + LLM 语义一致性
            │
       ┌────┴────┐
       │         │
    通过        失败→重规划
       │
       ▼
   [Finalize] 写回正式输出 → SSE 推送结果
```

**为何是多 Agent 而非单线 Pipeline**：自然语言到 CAD 脚本存在歧义，需要"规划→生成→执行→校验"闭环与纠错循环；单一模型直接生成易误操作污染图纸。角色分工后每步可单独评测、可插人工卡点、可追溯。

## MCP 工具包

| 包 | 工具 | 用途 |
|---|---|---|
| core | `drawing_info` | 读取图层与实体统计 |
| core | `cad_batch` | 批量执行绘图操作（核心工具） |
| core | `undo_checkpoint` | 回滚到检查点 |
| arch | `draw_wall` | 绘制墙体（支持厚度与双线偏移） |
| arch | `insert_opening` | 插入门窗洞口 |
| arch | `batch_dimension` | 按图层批量标注 |
| arch | `layer_audit` | 图层命名规范检查 |
| arch | `room_boundary` | 房间边界识别与面积统计 |
| mech | `add_hatch` / `offset_copy` | 剖面填充 / 偏移复制 |

工具发现机制：`search_tools(query, pack)` 按关键词返回相关工具，避免一次性加载全部工具描述占用上下文。批处理：`cad_batch` 一次调用完成多个原语，避免几十次工具往返。

## 快速开始

```bash
# 克隆
git clone https://github.com/wudidekongjv/CAD-agent.git
cd CAD-agent

# 启动服务
cd docker && docker compose up -d

# 局域网访问
# http://<服务器IP>:5173
```

首次打开自动注册设备并分配用户 ID（如 `BZ-0004`）。上传 DXF 图纸后输入深化需求即可。

## 技术栈

| 层 | 技术 |
|---|---|
| Agent 编排 | LangGraph StateGraph（条件边 + checkpointer） |
| 工具协议 | MCP（FastMCP + stdio） |
| 绘图引擎 | ezdxf（离线）/ AutoCAD COM（在线）/ auto 双模式 |
| 推理模型 | Qwen3-32B（本地 vLLM） |
| 后端 | FastAPI + MySQL + Redis + SSE |
| 前端 | Vue3 + Vite + 液态玻璃 UI |
| 部署 | Docker Compose（局域网） |

## 仓库结构

```
├── src/
│   ├── agent/
│   │   ├── state.py          # LangGraph 共享状态
│   │   └── graph.py          # 四节点状态机 + 条件边
│   ├── mcp/
│   │   └── cad_mcp_server.py # MCP 工具层（工具发现/批处理/分层）
│   ├── backend/
│   │   └── drawing_backend.py# ezdxf/COM 双后端抽象
│   └── api/main.py           # FastAPI 鉴权 + 任务 + SSE
├── web/                      # Vue3 前端
├── docker/                   # Docker Compose
├── docs/                     # 文档
└── examples/                 # 示例图纸
```

## 多用户与安全

与图像生成服务一致的三层机制：
- **网络层**：来源 IP 白名单（私有网段）
- **身份层**：设备指纹自动登录（X-Device-Id）
- **数据层**：`outputs/{role}/{user_id}/{task_id}/` 三级隔离

## License

MIT
