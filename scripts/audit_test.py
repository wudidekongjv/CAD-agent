# -*- coding: utf-8 -*-
"""功能审计：实测前端所有API调用 + 任务完整执行链路"""
import json, urllib.request, urllib.error, urllib.parse, uuid, time
import requests

BASE = "http://127.0.0.1:8000"
DEVICE = "dev_audit_" + uuid.uuid4().hex[:16]
H = {"X-Device-Id": DEVICE}
issues = []

def call(method, path, data=None, expect=200):
    h = dict(H)
    body = None
    if data is not None:
        body = json.dumps(data).encode()
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(BASE + path, data=body, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        try: return e.code, json.loads(e.read().decode())
        except: return e.code, {}

print("=" * 70)
print("功能审计 v2")
print("=" * 70)

st, identity = call("POST", "/api/auth/register", {"device_id": DEVICE})
print(f"\n身份: {identity.get('user_id')} role={identity.get('role')}")

# 1. 模型切换（修复后应成功）
st, r = call("POST", "/api/models/switch", None) if False else (None, None)
resp = requests.post(BASE + "/api/models/switch", data={"provider": "local"}, headers=H)
print(f"{'✓' if resp.status_code==200 else '✗'} 模型切换: {resp.status_code} {resp.text[:80]}")
if resp.status_code != 200: issues.append(("模型切换", resp.text[:100]))

# 2. 切回 API 模式（有 key 才切，否则保持 local）
# 降级链实测
import sys
sys.path.insert(0, "C:/Users/32553/WorkBuddy/2026-11-24-11-35-17/CAD-agent/src")
from swarm.guard import ModelFallback
# 验证降级链配置正确（deepseek→qwen→openai→local，4级）
print(f"{'✓' if len(ModelFallback.CHAIN)==4 and ModelFallback.CHAIN[-1]=='local' else '✗'} 模型降级链配置: {'→'.join(ModelFallback.CHAIN)}")
# 验证 _llm_decide 在 LLM 全失败时降级到规则引擎
from swarm.graph import _llm_decide
resp = _llm_decide("planner system", '{"user_request":"检查图层命名规范","drawing_summary":{}}')
is_fallback = resp.get("_degraded", False)
print(f"{'✓' if is_fallback else '·'} LLM失败时规则引擎兜底: degraded={is_fallback}")

# 3. 知识库多关键词检索
for q in ["墙厚", "标注样式", "门窗"]:
    st, r = call("GET", "/api/knowledge/search?q=" + urllib.parse.quote(q) + "&top_k=3")
    ok = st == 200 and len(r.get("results", [])) > 0
    print(f"{'✓' if ok else '✗'} 知识库检索 '{q}': {len(r.get('results',[]))} results")
    if not ok: issues.append((f"知识库检索{q}", str(r)[:100]))

# 4. 上传（requests 正确 multipart）
with open("C:/Users/32553/WorkBuddy/2026-11-24-11-35-17/CAD-agent/examples/audit.dxf", "rb") as f:
    resp = requests.post(BASE + "/api/upload", files={"file": ("audit.dxf", f, "application/octet-stream")}, headers=H)
print(f"{'✓' if resp.status_code==200 else '✗'} 上传DXF: {resp.status_code} {resp.text[:80]}")
if resp.status_code != 200: issues.append(("上传DXF", resp.text[:100]))

# 5. 提交任务 + 完整执行
st, task = call("POST", "/api/cad/deepen", {
    "request": "检查图层命名规范", "drawing_file": "audit.dxf",
    "backend": "ezdxf", "max_retries": 3,
})
print(f"{'✓' if st==200 else '✗'} 提交任务: {st} {task}")
if st != 200:
    issues.append(("提交任务", str(task)[:100]))
else:
    tid = task["task_id"]
    print("  等待 Swarm 执行（最多90秒）…")
    stage = "queued"
    for i in range(45):
        time.sleep(2)
        st2, status = call("GET", f"/api/task/{tid}/status")
        stage = status.get("stage", "?")
        if i % 5 == 0:
            print(f"    [{i*2}s] stage={stage}")
        if stage in ("done", "failed"):
            break
    st3, detail = call("GET", f"/api/tasks/{tid}")
    v = detail.get("validation", {})
    print(f"  最终: stage={stage} passed={v.get('passed')} handoffs={v.get('handoffs')}")
    print(f"  messages: {json.dumps(detail.get('messages',[]), ensure_ascii=False)[:200]}")
    print(f"  error: {detail.get('error','')[:150]}")
    if stage == "failed":
        issues.append(("任务执行失败", str(detail.get("error",""))[:100] + " | " + str(v)[:150]))

# 6. 元数据接口（用刚上传的任务）
if st == 200:
    st4, meta = call("GET", f"/api/drawing/metadata/{tid}?detail=full")
    print(f"{'✓' if st4==200 and meta.get('entities') else '✗'} 元数据接口: {st4} entities={len(meta.get('entities',[]))}")

# 7. 任务删除接口（前端有删除按钮但后端无接口）
st5, r5 = call("DELETE", f"/api/tasks/{tid}" if st==200 else "/api/tasks/fake")
print(f"{'✗' if st5==405 else '✓'} 任务删除接口状态: {st5} (405=缺失)")
if st5 == 405: issues.append(("任务删除接口缺失", "前端有删除按钮，后端无DELETE接口"))

print("\n" + "=" * 70)
print(f"发现问题: {len(issues)}")
for name, detail in issues:
    print(f"  ✗ {name}: {detail}")
print("=" * 70)
