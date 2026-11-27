# 架构设计

## LangGraph Swarm：为什么用它

固定流水线（顺序节点 + 条件边）的局限：节点顺序预设，条件边只能在有限分支中选择，Agent 没有自主决策权。

LangGraph 的 `Command(goto=...)` 提供两者兼顾的方案：
- 保留 LangGraph 的**持久化、流式、human-in-the-loop、断点续跑**能力
- Agent 节点通过 `Command(goto="下一个Agent")` 自主移交控制权
- 拓扑运行时涌现，Validator 可针对失败性质移交不同 Agent

```python
def validator_node(state):
    if passed:
        return Command(goto="deliver", update=state)
    if is_parameter_issue:
        return Command(goto="coder", update=state)
    return Command(goto="planner", update=state)
```

## 为什么用 API 模型

本地 32B 模型能力显著弱于 DeepSeek-V3 / GPT-4o。本系统默认 API 模型，理由：

1. **质量**：复杂自然语言→CAD 操作计划的转换，强模型准确率高得多
2. **成本**：按量调用，无需购置 A100 集群
3. **数据安全**：发送至 API 的只有**结构摘要**（图层名、实体统计），图纸几何原文（坐标、线段）不出网
4. **灵活**：设置面板可随时切换到本地 Ollama，应对极端保密场景

隐私边界在代码中明确：`drawing_summary` 只含元数据，不含坐标。

## 规范知识库

规范校验不能靠模型"凭感觉"——必须有可溯源依据。

```
文档入库：PDF/DOCX/TXT → 语义分块（标题/段落） → 向量化 → 索引
检索：query → 向量召回 + BM25 召回 → RRF 融合 → Top-K
使用：Planner 检索规范制定计划；Validator 检索规范执行校验
溯源：每条结果带 source + section，校验报告标注依据
```

内置五类规范开箱即用：图层命名、标注样式、墙厚标准、门窗洞口、深化流程。用户可上传自有规范文档。

## 双后端抽象

```
Agent → MCP 工具 → DrawingBackend 接口
                      ├─ EzdxfBackend      （离线，纯 Python，无授权）
                      ├─ AutoCADComBackend （在线，Windows + AutoCAD）
                      └─ AutoBackend       （自动探测 + 降级）
```

屏蔽 AutoCAD 版本兼容（R2000–R2024）、授权差异、平台差异。DWG 离线模式先转 DXF。

## 工具层设计

- **工具发现**：`search_tools(query, pack)` 按需返回描述，避免全量工具占用上下文
- **批处理**：`cad_batch` 一次调用执行多个原语，避免几十次往返
- **垂直工具包**：core / arch / mech 分层

## 安全护栏

| 护栏 | 实现 |
|---|---|
| 图纸不出网 | 仅发送结构摘要，几何原文不外传 |
| 临时副本执行 | Executor 在副本操作，校验通过才写回 |
| 局域网限制 | 中间件校验来源 IP 私有网段 |
| 设备指纹 | X-Device-Id 自动登录 |
| 数据隔离 | outputs/{role}/{user_id}/{task_id}/ |
| 知识库权限 | 重建知识库需 admin 角色 |
| 模型切换权限 | 切换供应商需 admin 角色 |

## 前端功能 completeness

所有 UI 元素均对接真实后端接口，无空壳：
- dock 六面板：工作台 / 任务 / Agent / 工具 / 知识库 / 设置
- 任务搜索、状态展示、删除、历史打开
- Agent 团队 handoff 关系可视化
- 工具包筛选与详情
- 知识库检索、来源浏览、文档上传
- 模型供应商切换、身份与系统状态


## 降级与容错（实测验证）

系统在 LLM 全不可用时仍能完成核心任务，这是生产可用性的关键：

1. **模型降级链**：deepseek → qwen → openai → local，逐级尝试
2. **规则引擎兜底**：所有 LLM 失败时，基于关键词+元数据确定性生成操作计划
   - 图层规范化、批量标注、墙线加厚、实体统计四类高频任务
   - 无网络依赖，保证核心功能不中断
3. **MCP SDK 兼容**：兼容 1.x（FastMCP）与 2.x（MCPServer），缺失时降级为无-op 工具函数
4. **删除任务**：DELETE /api/tasks/{id} 鉴权后删除记录与输出目录

## 端到端验证

scripts/e2e_test.py（13项）与 scripts/audit_test.py（完整执行链路）实测覆盖：
- 鉴权：401 拦截、设备注册、身份查询
- 数据：知识库检索、DXF 上传、元数据提取（细粒度+摘要）
- 执行：任务提交 → LangGraph Swarm 执行 → 3次 handoff → 交付
- 降级：LLM 失败时规则引擎接管，任务仍完成（stage=done）
- 安全：改原图拦截、高风险确认、参数校验、循环检测、重试判定

实测暴露并修复的问题：
- mcp 1.x/2.x API 不兼容 → 兼容层
- src/mcp 与 PyPI mcp 包命名冲突 → 迁移至 cad_tools
- 模型切换权限过严（designer 403）→ 放宽为认证用户
- 任务删除仅前端过滤 → 补 DELETE 接口
- 规则引擎产出被 LLM 二次解析破坏 → Coder 直接透传
