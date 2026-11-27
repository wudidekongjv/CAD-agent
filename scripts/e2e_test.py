# -*- coding: utf-8 -*-
"""端到端测试：逐一验证所有后端接口"""
import json
import urllib.request
import urllib.error
import urllib.parse
import uuid

BASE = "http://127.0.0.1:8000"
DEVICE = "dev_e2etest_" + uuid.uuid4().hex[:16]
results = []


def req(method, path, data=None, headers=None, raw=False):
    h = {"X-Device-Id": DEVICE, **(headers or {})}
    body = None
    if data is not None:
        if isinstance(data, (dict, list)):
            body = json.dumps(data).encode()
            h["Content-Type"] = "application/json"
        else:
            body = data
    r = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as resp:
            content = resp.read()
            return resp.status, (content if raw else json.loads(content))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:200]


def check(name, method, path, expect=200, data=None, headers=None, validator=None):
    status, body = req(method, path, data, headers)
    ok = status == expect
    detail = ""
    if ok and validator:
        try:
            ok, detail = validator(body)
        except Exception as e:
            ok, detail = False, str(e)
    results.append((name, ok, status, detail or str(body)[:80]))
    print(f"{'✓' if ok else '✗'} {name}: {status} {detail or str(body)[:80]}")
    return body


print("=" * 60)
print("CAD Agent 端到端测试")
print("=" * 60)

# 1. 无设备头应 401
print("\n--- 安全门槛 ---")
r = urllib.request.Request(BASE + "/api/tasks")
try:
    urllib.request.urlopen(r, timeout=10)
    print("✗ 无设备头未拦截")
except urllib.error.HTTPError as e:
    print(f"{'✓' if e.code == 401 else '✗'} 无设备头拦截: {e.code}")

# 2. 设备注册
body = check("设备注册", "POST", "/api/auth/register",
             data={"device_id": DEVICE, "label": "e2e test"},
             validator=lambda b: (b.get("user_id", "").startswith("BZ-"), b.get("user_id", "")))

# 3. 身份
check("查询身份", "GET", "/api/auth/me",
      validator=lambda b: (bool(b.get("user_id")), b.get("role", "")))

# 4. Agent 团队
check("Agent 团队", "GET", "/api/agents",
      validator=lambda b: (len(b.get("agents", [])) == 6, f"{len(b.get('agents',[]))} agents"))

# 5. 工具目录
check("工具目录", "GET", "/api/tools/detail",
      validator=lambda b: (all(k in b for k in ["core", "arch", "mech"]), list(b.keys())))

# 6. 模型供应商
check("模型供应商", "GET", "/api/models/providers",
      validator=lambda b: (len(b.get("providers", [])) == 4, b.get("current", {}).get("model", "")))

# 7. 安全护栏状态
check("安全护栏状态", "GET", "/api/safety/status",
      validator=lambda b: (all(k in b for k in ["safety_gate", "model_fallback", "data_validation", "retry", "loop_guard"]), list(b.keys())))

# 8. 知识库统计
check("知识库统计", "GET", "/api/knowledge/stats",
      validator=lambda b: (b.get("total_chunks", 0) >= 5, f"{b.get('total_chunks')} chunks"))

# 9. 知识库检索
check("知识库检索", "GET", "/api/knowledge/search?q=" + urllib.parse.quote("图层命名") + "&top_k=3",
      validator=lambda b: (len(b.get("results", [])) > 0, f"{len(b.get('results',[]))} results"))

# 10. 任务列表
check("任务列表", "GET", "/api/tasks",
      validator=lambda b: (isinstance(b, list), f"{len(b)} tasks"))

# 11. 上传 DXF
import ezdxf
doc = ezdxf.new("R2010")
msp = doc.modelspace()
msp.add_line((0, 0), (5000, 0), dxfattribs={"layer": "WALL"})
msp.add_line((0, 3000), (5000, 3000), dxfattribs={"layer": "WALL"})
msp.add_circle((2500, 1500), 500, dxfattribs={"layer": "0"})
doc.layers.new("ARCH_DOOR")
doc.saveas("C:/Users/32553/WorkBuddy/2026-11-24-11-35-17/CAD-agent/examples/test_drawing.dxf")

boundary = "----WebKitFormBoundary" + uuid.uuid4().hex
with open("C:/Users/32553/WorkBuddy/2026-11-24-11-35-17/CAD-agent/examples/test_drawing.dxf", "rb") as f:
    file_bytes = f.read()
form = (
    f"--{boundary}\r\n"
    f'Content-Disposition: form-data; name="file"; filename="test_drawing.dxf"\r\n'
    f"Content-Type: application/octet-stream\r\n\r\n"
).encode() + file_bytes + f"\r\n--{boundary}--\r\n".encode()

upload = check("上传DXF", "POST", "/api/upload", data=form,
               headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
               validator=lambda b: (b.get("path") == "test_drawing.dxf", b.get("path", "")))

# 12. 提交深化任务（会调用 LLM，可能因无 API Key 失败，但接口应可用）
task = check("提交深化任务", "POST", "/api/cad/deepen",
             data={"request": "把 WALL 图层墙线改为 200 厚并批量标注", "drawing_file": "test_drawing.dxf",
                   "backend": "ezdxf", "max_retries": 3},
             validator=lambda b: (bool(b.get("task_id")), b.get("status", "")))

# 13. 任务状态
if isinstance(task, dict) and task.get("task_id"):
    check("任务状态", "GET", f"/api/task/{task['task_id']}/status")
    check("任务详情", "GET", f"/api/tasks/{task['task_id']}")

# 14. 元数据提取（细粒度+整体性）
print("\n--- CAD 元数据 ---")
import sys
sys.path.insert(0, "C:/Users/32553/WorkBuddy/2026-11-24-11-35-17/CAD-agent/src")
from backend.metadata import extract_metadata, compare_metadata

meta = extract_metadata("C:/Users/32553/WorkBuddy/2026-11-24-11-35-17/CAD-agent/examples/test_drawing.dxf", "full")
print(f"{'✓' if meta['overview']['totals']['entities'] == 3 else '✗'} 实体总数: {meta['overview']['totals']['entities']}")
print(f"{'✓' if len(meta['entities']) == 3 else '✗'} 细粒度实体: {len(meta['entities'])}")
print(f"{'✓' if meta['entities'][0].get('handle') else '✗'} 实体句柄: {meta['entities'][0].get('handle')}")
print(f"{'✓' if 'length' in meta['entities'][0] else '✗'} 几何参数: length={meta['entities'][0].get('length')}")
print(f"{'✓' if meta['overview']['layer_tree'] else '✗'} 图层树: {len(meta['overview']['layer_tree'])} layers")
print(f"{'✓' if meta['overview']['spatial_extent'].get('available') else '✗'} 空间范围: {meta['overview']['spatial_extent']}")

summary = extract_metadata("C:/Users/32553/WorkBuddy/2026-11-24-11-35-17/CAD-agent/examples/test_drawing.dxf", "summary")
print(f"{'✓' if not summary['entities'] else '✗'} 摘要脱敏（无实体明细）")
print(f"{'✓' if 'coordinates' not in str(summary) else '✗'} 摘要无坐标原文")

# 15. 安全护栏实测
print("\n--- 安全护栏 ---")
from swarm.guard import SafetyGate, ModelFallback, DataValidator, RetryPolicy, LoopGuard

gate = SafetyGate()
d1 = gate.check([{"op": "set_layer", "layer": "WALL", "props": {}}], "same.dxf", "same.dxf")
print(f"{'✓' if not d1.allowed else '✗'} 拦截直接改原图: {d1.reason}")
d2 = gate.check([{"op": "delete_entities", "filter": 'LINE[layer=="0"]'}], "out.dxf", "in.dxf")
print(f"{'✓' if d2.requires_confirmation else '✗'} 高风险需确认: {d2.reason}")

dv = DataValidator()
ok, errs = dv.validate_ops([{"op": "draw_wall"}])
print(f"{'✓' if not ok else '✗'} 参数缺失检测: {errs}")

lg = LoopGuard(max_handoffs=8)
for i in range(6):
    target = "planner" if i % 2 == 0 else "coder"
    ok, reason = lg.check_handoff(target, {})
print(f"{'✓' if not ok and '循环' in reason else '✗'} 循环检测: {reason}")

rp = RetryPolicy(max_attempts=3)
print(f"{'✓' if rp.should_retry('Connection timeout', 0) else '✗'} 重试判定")
print(f"{'✓' if not rp.should_retry('Invalid argument', 0) else '✗'} 非重试错误判定")

print("\n" + "=" * 60)
passed = sum(1 for _, ok, _, _ in results if ok)
print(f"接口测试: {passed}/{len(results)} 通过")
print("=" * 60)
