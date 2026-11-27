"""FastAPI 服务：CAD 辅助深化 Agent · 局域网多用户版

接口（与前端严格对应）：
- POST /api/auth/register        设备注册
- GET  /api/auth/me              当前身份
- GET  /api/tasks                渲染记录列表
- GET  /api/tasks/{id}           任务详情
- POST /api/cad/ deepen          提交 CAD 深化任务
- GET  /api/task/{id}/status     任务状态（SSE 断线恢复）
- GET  /api/cad/stream           SSE 进度推送
- GET  /api/files/{path}         鉴权文件访问
- GET  /api/tools                工具目录（前端展示能力）
"""

import asyncio
import ipaddress
import json
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Optional

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

# ============ 配置 ============
BASE_DIR = Path(os.getenv("CADAGENT_HOME", "./cadagent_data"))
DB_PATH = BASE_DIR / "cadagent.db"
OUTPUT_ROOT = BASE_DIR / "outputs"
UPLOAD_ROOT = BASE_DIR / "uploads"
DRAWING_ROOT = BASE_DIR / "drawings"

LAN_NETWORKS = [
    ipaddress.ip_network(n) for n in
    os.getenv("CADAGENT_LAN", "127.0.0.1/32,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16").split(",")
]
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{16,128}$")
DEFAULT_ROLE = os.getenv("CADAGENT_DEFAULT_ROLE", "designer")
ROLE_CONFIG = {
    "designer": {"name": "深化设计师", "quota_per_day": 200},
    "reviewer": {"name": "图纸审核", "quota_per_day": 50},
    "admin": {"name": "管理员", "quota_per_day": 1000},
}

for d in (BASE_DIR, OUTPUT_ROOT, UPLOAD_ROOT, DRAWING_ROOT):
    d.mkdir(parents=True, exist_ok=True)


# ============ 数据库 ============
def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS devices (
                device_id TEXT PRIMARY KEY, user_id TEXT UNIQUE NOT NULL,
                role TEXT NOT NULL, label TEXT DEFAULT '',
                created_at TEXT NOT NULL, last_seen TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY, device_id TEXT NOT NULL,
                user_id TEXT NOT NULL, role TEXT NOT NULL,
                request TEXT NOT NULL, stage TEXT NOT NULL,
                drawing_path TEXT DEFAULT '', output_path TEXT DEFAULT '',
                validation TEXT DEFAULT '{}', messages TEXT DEFAULT '[]',
                error TEXT DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_device ON tasks(device_id, created_at DESC)")
        conn.commit()


init_db()


@contextmanager
def db_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============ 中间件 ============
app = FastAPI(title="CAD Agent API", version="1.0.0")


def is_lan_ip(ip_str: str) -> bool:
    try:
        return any(ipaddress.ip_address(ip_str) in net for net in LAN_NETWORKS)
    except ValueError:
        return False


@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path
    client_ip = request.client.host if request.client else ""

    if not is_lan_ip(client_ip):
        return JSONResponse(status_code=403, content={"detail": "Access denied: non-LAN address"})

    if path in ("/docs", "/openapi.json", "/redoc", "/api/auth/register"):
        return await call_next(request)

    device_id = request.headers.get("X-Device-Id", "")
    if not device_id and path == "/api/cad/stream":
        device_id = request.query_params.get("device_id", "")
    if not device_id or not DEVICE_ID_RE.match(device_id):
        return JSONResponse(status_code=401, content={"detail": "Missing or invalid X-Device-Id"})

    with db_conn() as conn:
        device = conn.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
    if not device:
        return JSONResponse(status_code=401, content={"detail": "Unregistered device"})

    request.state.device_id = device_id
    request.state.user_id = device["user_id"]
    request.state.role = device["role"]
    with db_conn() as conn:
        conn.execute("UPDATE devices SET last_seen=? WHERE device_id=?", (now_str(), device_id))
    return await call_next(request)


def identity(request: Request) -> Dict[str, str]:
    return {
        "device_id": request.state.device_id,
        "user_id": request.state.user_id,
        "role": request.state.role,
    }


# ============ 认证 ============
class RegisterReq(BaseModel):
    device_id: str
    label: Optional[str] = ""


@app.post("/api/auth/register")
async def register(req: RegisterReq):
    if not DEVICE_ID_RE.match(req.device_id):
        raise HTTPException(status_code=400, detail="Invalid device_id")
    with db_conn() as conn:
        existing = conn.execute("SELECT * FROM devices WHERE device_id=?", (req.device_id,)).fetchone()
        if existing:
            return {
                "device_id": req.device_id, "user_id": existing["user_id"],
                "role": existing["role"], "role_name": ROLE_CONFIG.get(existing["role"], {}).get("name", ""),
                "quota_per_day": ROLE_CONFIG.get(existing["role"], {}).get("quota_per_day", 50),
                "is_new": False,
            }
        count = conn.execute("SELECT COUNT(*) FROM devices").fetchone()[0]
        user_id = f"BZ-{count + 1:04d}"
        conn.execute(
            "INSERT INTO devices(device_id,user_id,role,label,created_at,last_seen) VALUES(?,?,?,?,?,?)",
            (req.device_id, user_id, DEFAULT_ROLE, req.label or "", now_str(), now_str()),
        )
    (OUTPUT_ROOT / DEFAULT_ROLE / user_id).mkdir(parents=True, exist_ok=True)
    return {
        "device_id": req.device_id, "user_id": user_id, "role": DEFAULT_ROLE,
        "role_name": ROLE_CONFIG[DEFAULT_ROLE]["name"],
        "quota_per_day": ROLE_CONFIG[DEFAULT_ROLE]["quota_per_day"],
        "is_new": True,
    }


@app.get("/api/auth/me")
async def me(user=Depends(identity)):
    return {**user, "role_name": ROLE_CONFIG.get(user["role"], {}).get("name", ""),
            "quota_per_day": ROLE_CONFIG.get(user["role"], {}).get("quota_per_day", 50)}


# ============ 任务记录 ============
@app.get("/api/tasks")
async def list_tasks(user=Depends(identity)):
    with db_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE device_id=? ORDER BY created_at DESC LIMIT 100",
            (user["device_id"],),
        ).fetchall()
    out = []
    for r in rows:
        out.append({
            "task_id": r["task_id"], "request": r["request"], "stage": r["stage"],
            "drawing_path": r["drawing_path"],
            "output_path": f"/api/files/{r['output_path']}" if r["output_path"] else "",
            "created_at": r["created_at"], "time_label": make_label(r["created_at"]),
        })
    return out


def make_label(created_at: str) -> str:
    try:
        dt = datetime.strptime(created_at, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()
        if dt.date() == now.date():
            return f"今天 {dt.strftime('%H:%M')}"
        from datetime import timedelta
        if dt.date() == (now - timedelta(days=1)).date():
            return f"昨天 {dt.strftime('%H:%M')}"
        return dt.strftime("%m-%d %H:%M")
    except Exception:
        return created_at


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str, user=Depends(identity)):
    with db_conn() as conn:
        r = conn.execute(
            "SELECT * FROM tasks WHERE task_id=? AND device_id=?", (task_id, user["device_id"])
        ).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "task_id": r["task_id"], "request": r["request"], "stage": r["stage"],
        "drawing_path": r["drawing_path"],
        "output_path": f"/api/files/{r['output_path']}" if r["output_path"] else "",
        "validation": json.loads(r["validation"] or "{}"),
        "messages": json.loads(r["messages"] or "[]"),
        "error": r["error"], "created_at": r["created_at"],
    }


# ============ 工具目录 ============
@app.get("/api/tools")
async def tools():
    """前端展示的 MCP 工具目录"""
    return {
        "core": [
            {"name": "drawing_info", "desc": "读取图纸结构"},
            {"name": "cad_batch", "desc": "批量执行绘图操作"},
            {"name": "undo_checkpoint", "desc": "回滚检查点"},
        ],
        "arch": [
            {"name": "draw_wall", "desc": "绘制墙体"},
            {"name": "insert_opening", "desc": "插入门窗"},
            {"name": "batch_dimension", "desc": "批量标注"},
            {"name": "layer_audit", "desc": "图层规范检查"},
            {"name": "room_boundary", "desc": "房间边界识别"},
        ],
    }


# ============ 任务执行 ============
TASKS: Dict[str, Dict] = {}
PROGRESS: Dict[str, List] = {}


class DeepenReq(BaseModel):
    request: str
    drawing_file: str          # 已上传的图纸相对路径
    backend: str = "auto"      # auto/com/ezdxf
    max_retries: int = 3


@app.post("/api/cad/deepen")
async def deepen(req: DeepenReq, user=Depends(identity)):
    """提交 CAD 深化任务（异步执行，SSE 推送进度）"""
    task_id = str(uuid.uuid4())
    PROGRESS[task_id] = []

    # 校验图纸归属
    drawing_path = DRAWING_ROOT / user["user_id"] / req.drawing_file
    if not drawing_path.exists():
        raise HTTPException(status_code=404, detail="Drawing not found")

    output_rel = str(Path(user["role"]) / user["user_id"] / task_id / "result.dxf")
    output_path = OUTPUT_ROOT / output_rel
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with db_conn() as conn:
        conn.execute("""
            INSERT INTO tasks(task_id,device_id,user_id,role,request,stage,drawing_path,output_path,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
        """, (task_id, user["device_id"], user["user_id"], user["role"],
              req.request, "queued", str(drawing_path), output_rel, now_str(), now_str()))

    # 后台执行（生产用 Celery；此处用 asyncio task）
    asyncio.create_task(_run_graph(task_id, req, user, str(drawing_path), str(output_path)))

    return {"task_id": task_id, "status": "queued"}


async def _run_graph(task_id: str, req: DeepenReq, user: Dict, drawing_path: str, output_path: str):
    """后台运行 LangGraph 状态机"""
    def progress(stage: str, msg: str):
        PROGRESS[task_id].append({"stage": stage, "msg": msg, "ts": now_str()})

    try:
        progress("planner", "正在分析需求与图纸结构…")

        # 读取图纸信息
        backend_mode = req.backend
        drawing_info = {}
        try:
            from backend.drawing_backend import get_backend
            backend = get_backend(backend_mode)
            drawing_info = backend.inspect(drawing_path)
        except Exception as e:
            progress("warning", f"图纸信息读取失败: {e}")

        progress("planner", "正在生成操作计划…")
        await asyncio.sleep(0.5)  # 模拟 LLM 延迟，生产环境为真实调用

        from agent.graph import run_task
        initial_state = {
            "user_request": req.request,
            "drawing_path": drawing_path,
            "output_path": output_path,
            "device_id": user["device_id"],
            "task_id": task_id,
            "drawing_info": drawing_info,
            "retry_count": 0,
            "max_retries": req.max_retries,
            "backend": backend_mode,
            "messages": [],
        }
        final_state = run_task(initial_state, thread_id=task_id)

        stage = final_state.get("stage", "unknown")
        progress("executor", f"执行完成，状态: {stage}")
        progress("validator", "校验完成")

        with db_conn() as conn:
            conn.execute("""
                UPDATE tasks SET stage=?, validation=?, messages=?, error=?, updated_at=?
                WHERE task_id=?
            """, (
                stage,
                json.dumps(final_state.get("validation", {}), ensure_ascii=False),
                json.dumps(final_state.get("messages", []), ensure_ascii=False),
                final_state.get("error", ""), now_str(), task_id,
            ))

        PROGRESS[task_id].append({"stage": "done", "msg": "深化完成", "ts": now_str()})

    except Exception as e:
        with db_conn() as conn:
            conn.execute("UPDATE tasks SET stage='failed', error=?, updated_at=? WHERE task_id=?",
                         (str(e), now_str(), task_id))
        PROGRESS[task_id].append({"stage": "error", "msg": str(e), "ts": now_str()})


@app.get("/api/task/{task_id}/status")
async def task_status(task_id: str, user=Depends(identity)):
    with db_conn() as conn:
        r = conn.execute("SELECT * FROM tasks WHERE task_id=? AND device_id=?",
                         (task_id, user["device_id"])).fetchone()
    if not r:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"task_id": task_id, "stage": r["stage"], "error": r["error"]}


@app.get("/api/cad/stream")
async def stream(task_id: str, request: Request, user=Depends(identity)):
    """SSE 进度推送"""
    with db_conn() as conn:
        r = conn.execute("SELECT device_id FROM tasks WHERE task_id=?", (task_id,)).fetchone()
    if not r or r["device_id"] != user["device_id"]:
        raise HTTPException(status_code=403, detail="Access denied")

    async def events() -> AsyncGenerator[str, None]:
        idx, heartbeat = 0, 0
        while True:
            if await request.is_disconnected():
                break
            for evt in PROGRESS.get(task_id, [])[idx:]:
                yield f"event: progress\ndata: {json.dumps(evt, ensure_ascii=False)}\n\n"
                idx += 1
            heartbeat += 1
            if heartbeat % 15 == 0:
                yield ": heartbeat\n\n"

            with db_conn() as conn:
                r = conn.execute("SELECT stage FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if r and r["stage"] in ("done", "failed"):
                yield f"event: done\ndata: {json.dumps({'stage': r['stage']}, ensure_ascii=False)}\n\n"
                break
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ============ 文件上传 / 访问 ============
@app.post("/api/upload")
async def upload(file: UploadFile = File(...), user=Depends(identity)):
    user_dir = UPLOAD_ROOT / user["user_id"]
    user_dir.mkdir(parents=True, exist_ok=True)

    # 图纸放 DRAWING_ROOT（graph 读取用）
    drawing_dir = DRAWING_ROOT / user["user_id"]
    drawing_dir.mkdir(parents=True, exist_ok=True)
    path = drawing_dir / file.filename
    path.write_bytes(await file.read())
    return {"filename": file.filename, "path": file.filename, "size": path.stat().st_size}


@app.get("/api/files/{relative_path:path}")
async def get_file(relative_path: str, user=Depends(identity)):
    if ".." in relative_path or relative_path.startswith("/"):
        raise HTTPException(status_code=400, detail="Invalid path")

    allowed = (OUTPUT_ROOT / user["role"] / user["user_id"]).resolve()
    candidates = [
        (OUTPUT_ROOT / relative_path).resolve(),
        (DRAWING_ROOT / user["user_id"] / relative_path).resolve(),
    ]
    full = next((p for p in candidates if str(p).startswith(str(allowed)) and p.exists()), None)
    if not full or not full.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(full)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
