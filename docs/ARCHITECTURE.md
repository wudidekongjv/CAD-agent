# 架构设计

## 为什么是多 Agent 而非单线 Pipeline

判断依据是**任务是否需要动态决策与循环纠错**：

| 维度 | 单线 Pipeline | 多 Agent 状态机 |
|---|---|---|
| 流程确定性 | 步骤固定、无分支 | 步骤依赖中间结果、有分支 |
| 决策主体 | 人预设，机器只执行 | 机器需判断下一步 |
| 错误处理 | 失败即报错/固定重试 | 失败需重新规划 |

项目二属于后者：自然语言到 CAD 脚本存在歧义，一次生成容易误操作污染图纸，因此需要"规划→生成→执行→校验→失败重规划"的闭环。

## StateGraph 状态设计

State 记录任务推进的全部上下文：

- `user_request` / `drawing_path` / `output_path`：输入与输出
- `drawing_info`：图纸结构（图层、实体统计）
- `plan`：Planner 输出的操作计划
- `generated_ops` / `script`：Coder 生成的工具调用参数
- `exec_result`：执行结果
- `validation`：校验结论与错误清单
- `retry_count`：重试次数（控制最多 3 次）
- `messages`：全过程消息（追溯与人工交接）

节点间通过**共享 State**通信，而非 Agent 之间对话。checkpointer 支持断点续跑与人工介入。

## 工具层设计

### 工具发现
一次性把全部工具描述塞进 LLM 上下文会浪费大量 token。采用 `search_tools(query, pack)` 按需返回相关工具，Planner 只看当前任务需要的工具包。

### 批处理
早期方案一个操作一次工具往返，一张平面图可能需要几十次调用。`cad_batch` 一次传入操作列表，在同一份图纸上顺序执行，显著减少往返。

### 垂直工具包
- core：通用（drawing_info、cad_batch、undo_checkpoint）
- arch：建筑（draw_wall、insert_opening、batch_dimension、layer_audit、room_boundary）
- mech：构造（add_hatch、offset_copy）

按场景启用，减少无关工具干扰。

## 双后端抽象

```
Agent → MCP 工具 → DrawingBackend 接口
                      ├─ EzdxfBackend   （离线，纯 Python，无授权依赖）
                      ├─ AutoCADComBackend（在线，Windows + AutoCAD）
                      └─ AutoBackend    （自动探测 + 失败降级）
```

上层 Agent 只调用统一接口，不感知后端差异。这屏蔽了：
- AutoCAD COM 的版本兼容（R2000–R2024 API 差异）
- 授权问题（无 AutoCAD 时用 ezdxf）
- 平台差异（ezdxf 跨平台，COM 仅 Windows）

DWG 文件在离线模式下先经 ODA File Converter 转 DXF。

## 安全执行

1. 脚本在**临时副本**执行，绝不直接操作原图
2. Validator 通过后才写回正式输出路径
3. 规则校验：操作成功率、实体数量突变、图层规范
4. 语义校验：LLM 判断执行结果是否符合用户意图
5. 超过重试次数转人工，不强行交付错误结果

## 操作日志与幂等

每次 MCP 工具调用记录到操作日志（生产环境写 MySQL）：
- 工具名、参数、后端、时间戳、成功状态
- 支持 undo_checkpoint 回滚
- 支持任务审计与问题复现
