<template>
  <div class="space">
    <!-- 背景层：建筑摄影 + 模糊 -->
    <div class="bg-layer" :style="{ backgroundImage: `url(/bg-terminal.jpg)` }"></div>
    <div class="bg-veil"></div>

    <!-- 左侧圆形图标栏 -->
    <nav class="dock glass">
      <button class="dock-btn" :class="{ active: panel === 'home' }" @click="panel = 'home'" title="工作台">
        <svg viewBox="0 0 24 24"><path d="M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1z"/></svg>
      </button>
      <button class="dock-btn" :class="{ active: panel === 'tasks' }" @click="panel = 'tasks'" title="任务">
        <svg viewBox="0 0 24 24"><path d="M9 5h10v2H9zm0 6h10v2H9zm0 6h10v2H9zM4 5h3v3H4zm0 6h3v3H4zm0 6h3v3H4z"/></svg>
      </button>
      <button class="dock-btn" :class="{ active: panel === 'agents' }" @click="panel = 'agents'" title="Agent 团队">
        <svg viewBox="0 0 24 24"><path d="M12 2a4 4 0 1 1 0 8 4 4 0 0 1 0-8M6 14a6 6 0 0 1 12 0v1H6zm-4 4a2 2 0 0 1 2-2h2v5H4a2 2 0 0 1-2-2zm16-2h2a2 2 0 0 1 2 2v1a2 2 0 0 1-2 2h-2z"/></svg>
      </button>
      <button class="dock-btn" :class="{ active: panel === 'tools' }" @click="panel = 'tools'" title="工具">
        <svg viewBox="0 0 24 24"><path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.8-3.8a6 6 0 0 1-7.6 7.6l-6.9 6.9a2 2 0 0 1-2.8-2.8l6.9-6.9a6 6 0 0 1 7.6-7.6z"/></svg>
      </button>
      <button class="dock-btn" @click="panel = 'settings'" title="设置">
        <svg viewBox="0 0 24 24"><path d="M12 8a4 4 0 1 0 0 8 4 4 0 0 0 0-8m9 4a9 9 0 0 0-.2-1.8l2-1.5-2-3.4-2.4 1a9 9 0 0 0-3.1-1.8L14.8 2h-4l-.5 2.5a9 9 0 0 0-3.1 1.8l-2.4-1-2 3.4 2 1.5a9 9 0 0 0 0 3.6l-2 1.5 2 3.4 2.4-1a9 9 0 0 0 3.1 1.8l.5 2.5h4l.5-2.5a9 9 0 0 0 3.1-1.8l2.4 1 2-3.4-2-1.5A9 9 0 0 0 21 12"/></svg>
      </button>
      <div class="dock-spacer"></div>
      <div class="dock-avatar">{{ (identity.user_id || 'BZ-0216').slice(-4) }}</div>
    </nav>

    <!-- 中央主卡片 -->
    <section class="stage glass">
      <!-- 顶部浏览器式工具条 -->
      <div class="stage-toolbar">
        <div class="toolbar-left">
          <span class="tb-dot"></span>
          <button class="tb-icon" @click="newTask">‹</button>
          <button class="tb-icon" @click="showHistory = !showHistory">›</button>
          <span class="tb-title">CAD Agent · 施工图深化</span>
        </div>
        <div class="toolbar-right">
          <span class="status-pill" :class="{ on: serverOk }">
            <span class="status-dot"></span>{{ serverOk ? '本地在线' : '离线' }}
          </span>
        </div>
      </div>

      <!-- 主内容区 -->
      <div class="stage-body no-scrollbar" ref="stageBody">
        <!-- Hero / 欢迎 -->
        <div v-if="!currentTask && !messages.length" class="hero">
          <div class="hero-badge">
            <svg viewBox="0 0 24 24"><path d="M12 2 2 7l10 5 10-5zM2 12l10 5 10-5M2 17l10 5 10-5"/></svg>
          </div>
          <h1>让施工图深化，交给 Agent 团队</h1>
          <p>规划 · 生成 · 执行 · 校验 —— 六个专职 Agent 通过 handoff 自主协作，全程本地离线运行</p>

          <div class="cap-grid">
            <div class="cap" v-for="c in capabilities" :key="c.title">
              <div class="cap-icon" v-html="c.icon"></div>
              <div class="cap-title">{{ c.title }}</div>
              <div class="cap-sub">{{ c.sub }}</div>
            </div>
          </div>

          <div class="hero-tags">
            <button v-for="q in quickPrompts" :key="q.label" class="tag-pill" @click="input = q.text">{{ q.label }}</button>
          </div>
        </div>

        <!-- 任务执行流 -->
        <div v-else class="flow">
          <div v-for="m in messages" :key="m.id" class="flow-row" :class="m.role">
            <!-- 用户气泡 -->
            <div v-if="m.role === 'user'" class="bubble user">
              <div class="bubble-label">你</div>
              <div class="bubble-text">{{ m.text }}</div>
              <div v-if="m.file" class="file-tag">▤ {{ m.file }}</div>
            </div>

            <!-- Agent 消息 -->
            <div v-else class="agent-block">
              <div class="agent-head">
                <span class="agent-avatar" :class="m.agent || 'planner'">✦</span>
                <span class="agent-name">{{ m.agentName || 'CAD Agent' }}</span>
                <span class="agent-phase" v-if="m.phase">{{ m.phase }}</span>
              </div>

              <!-- Handoff 轨迹 -->
              <div v-if="m.type === 'handoff'" class="handoff-track">
                <div v-for="(h, i) in m.chain" :key="i" class="hop">
                  <span class="hop-node">{{ h }}</span>
                  <span v-if="i < m.chain.length - 1" class="hop-arrow">→</span>
                </div>
              </div>

              <!-- 执行计划 -->
              <div v-if="m.type === 'plan'" class="card-inset">
                <div class="inset-title">执行计划</div>
                <div v-for="(s, i) in m.steps" :key="i" class="plan-row">
                  <span class="plan-num">{{ String(i + 1).padStart(2, '0') }}</span>
                  <span class="plan-op">{{ s.op || s }}</span>
                  <span class="plan-reason" v-if="s.reason">{{ s.reason }}</span>
                </div>
              </div>

              <!-- 校验 -->
              <div v-if="m.type === 'validation'" class="card-inset" :class="{ ok: m.passed }">
                <div class="inset-title">{{ m.passed ? '✓ 校验通过' : '⚠ 需要处理' }}</div>
                <div v-for="(e, i) in m.errors" :key="i" class="err-row">{{ e }}</div>
                <div v-if="m.handoffs" class="meta-row">Agent 移交 {{ m.handoffs.length }} 次</div>
              </div>

              <!-- 结果 -->
              <div v-if="m.type === 'result'" class="result-card">
                <div class="result-preview">
                  <img :src="m.image" alt="深化后图纸" v-if="m.image" />
                  <div class="no-preview" v-else>图纸已生成</div>
                </div>
                <div class="result-meta">
                  <div class="meta-item"><span>实体</span><b>{{ m.entities || '—' }}</b></div>
                  <div class="meta-item"><span>移交</span><b>{{ m.handoffs || 0 }}</b></div>
                  <div class="meta-item"><span>轮次</span><b>{{ m.turns || '—' }}</b></div>
                </div>
                <div class="result-btns">
                  <a class="pill-btn primary" :href="m.download" download>下载 DXF</a>
                  <button class="pill-btn" @click="referenceDrawing(m.download)">引用此图</button>
                </div>
              </div>

              <div v-if="m.type === 'text'" class="bubble-text">{{ m.text }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 底部控制条（参考图的播放器形态） -->
      <div class="control-bar">
        <button class="ctrl-btn" @click="triggerUpload" title="上传图纸">▤</button>
        <input ref="fileInput" type="file" accept=".dxf,.dwg" hidden @change="onFileChange" />
        <div class="file-mini" v-if="file">
          <span>{{ file.name }}</span>
          <button @click="file = null">×</button>
        </div>
        <textarea v-model="input" rows="1" class="cmd-input"
                  placeholder="描述深化需求，如：把 WALL 图层墙线改为 200 厚并批量标注…"
                  :disabled="!serverOk"
                  @keydown.enter.exact.prevent="submit"></textarea>
        <button class="send-btn" :disabled="!serverOk || (!input.trim() || !file)" @click="submit">➤</button>
      </div>
      <div class="control-hint">Enter 发送 · 全程本地离线 · 支持 DXF / DWG</div>
    </section>

    <!-- 右侧消息/任务面板 -->
    <aside class="messages glass" v-if="showHistory">
      <div class="msg-head">
        <span>深化记录</span>
        <button class="msg-more" @click="showHistory = false">···</button>
      </div>
      <div class="msg-search">
        <span>⌕</span> 搜索任务
      </div>
      <div class="msg-list no-scrollbar">
        <div v-if="!history.length" class="msg-empty">暂无深化记录</div>
        <div v-for="t in history" :key="t.task_id" class="msg-item" :class="{ sel: currentTask && currentTask.task_id === t.task_id }"
             @click="loadTask(t)">
          <div class="msg-avatar">▤</div>
          <div class="msg-content">
            <div class="msg-line1"><b>{{ t.request.slice(0, 18) }}</b><span>{{ t.time_label }}</span></div>
            <div class="msg-line2">{{ stageLabel(t.stage) }} · CAD 深化任务</div>
          </div>
        </div>
      </div>
      <div class="msg-foot">
        <span class="foot-dot"></span> Swarm 本地运行时 · {{ identity.user_id || 'BZ-0216' }}
      </div>
    </aside>

    <!-- 连接失败横幅（不遮挡主体） -->
    <div v-if="initError" class="err-banner glass-light">
      <span>⚠</span> {{ initError }}
      <button @click="init">重试</button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import './assets/styles/variables.css'

const API = ''
const serverOk = ref(false)
const initError = ref('')
const identity = ref({})
const deviceId = ref('')
const panel = ref('home')
const showHistory = ref(true)
const file = ref(null)
const input = ref('')
const fileInput = ref(null)
const stageBody = ref(null)
const currentTask = ref(null)
const messages = ref([])
const history = ref([])

const capabilities = [
  { icon: '▤', title: '图层整理', sub: '规范命名 · 合并冗余' },
  { icon: '⌗', title: '批量标注', sub: '按图层自动标注' },
  { icon: '⊞', title: '门窗布置', sub: '按开间批量插入' },
  { icon: '✓', title: '规范校验', sub: '出图前合规检查' },
]

const quickPrompts = [
  { label: '图层规范化', text: '检查所有图层命名，按 ARCH_ 前缀规范重命名不合规图层，删除空图层' },
  { label: '批量标注', text: '对 WALL 图层的墙体批量添加线性标注，样式使用 ARCH_DIM' },
  { label: '墙线加厚', text: '将所有 WALL 图层的墙线线宽改为 0.35mm，并偏移生成双线' },
  { label: '房间识别', text: '识别墙体围合的房间边界，统计每个房间面积' },
]

function fingerprint() {
  let id = localStorage.getItem('cad_agent_device')
  if (id) return id
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  ctx.fillText('cad', 2, 2)
  const sig = canvas.toDataURL().slice(-40)
  const raw = [navigator.userAgent, `${screen.width}x${screen.height}`, sig,
    crypto.randomUUID ? crypto.randomUUID() : String(Math.random())].join('|')
  let h = 0x811c9dc5
  for (let i = 0; i < raw.length; i++) { h ^= raw.charCodeAt(i); h = Math.imul(h, 0x01000193) }
  id = 'dev_' + (h >>> 0).toString(16).padStart(8, '0') +
       (crypto.randomUUID ? crypto.randomUUID().replace(/-/g, '').slice(0, 16) : Math.random().toString(36).slice(2))
  localStorage.setItem('cad_agent_device', id)
  return id
}

async function api(path, opts = {}) {
  const headers = { ...(opts.headers || {}), 'X-Device-Id': deviceId.value }
  if (opts.body && !(opts.body instanceof FormData)) headers['Content-Type'] = 'application/json'
  const res = await fetch(API + path, { ...opts, headers })
  if (!res.ok) {
    let d = res.statusText
    try { d = (await res.json()).detail || d } catch {}
    throw new Error(d)
  }
  return res.json()
}

async function init() {
  initError.value = ''
  serverOk.value = false
  try {
    deviceId.value = fingerprint()
    const res = await fetch(API + '/api/auth/register', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ device_id: deviceId.value }),
    })
    if (!res.ok) throw new Error('设备注册失败')
    identity.value = await res.json()
    serverOk.value = true
    history.value = await api('/api/tasks')
  } catch (e) { initError.value = e.message || '连接失败' }
}
onMounted(init)

function stageLabel(s) {
  return ({ queued: '排队', planned: '规划中', coded: '生成中', executed: '执行中',
    validated: '校验中', done: '已完成', failed: '失败' })[s] || s
}
function triggerUpload() { fileInput.value?.click() }
function onFileChange(e) { file.value = e.target.files[0]; e.target.value = '' }
function newTask() { currentTask.value = null; messages.value = []; input.value = ''; file.value = null }

async function submit() {
  if (!serverOk.value || !input.value.trim() || !file.value) return
  const text = input.value.trim()
  const fname = file.value.name
  messages.value.push({ id: Date.now(), role: 'user', text, file: fname })
  input.value = ''
  await nextTick(); scroll()

  try {
    const fd = new FormData()
    fd.append('file', file.value)
    const up = await api('/api/upload', { method: 'POST', body: fd })
    const r = await api('/api/cad/deepen', {
      method: 'POST',
      body: JSON.stringify({ request: text, drawing_file: up.path, backend: 'auto', max_retries: 3 }),
    })
    currentTask.value = { task_id: r.task_id, request: text, stage: 'queued' }
    history.value.unshift(currentTask.value)

    const hm = { id: Date.now() + 1, role: 'agent', agent: 'planner', agentName: 'Planner',
      type: 'handoff', phase: '协作中', chain: ['Planner', 'Coder', 'Executor', 'Validator', 'Deliver'] }
    messages.value.push(hm)
    listen(r.task_id, hm)
  } catch (e) {
    messages.value.push({ id: Date.now() + 2, role: 'agent', type: 'text', text: e.message })
  }
  await nextTick(); scroll()
}

function listen(taskId, hm) {
  const es = new EventSource(`${API}/api/cad/stream?task_id=${taskId}&device_id=${deviceId.value}`)
  es.addEventListener('progress', (e) => {
    const d = JSON.parse(e.data)
    hm.phase = d.msg || d.stage
  })
  es.addEventListener('done', async () => {
    es.close()
    try {
      const d = await api(`/api/tasks/${taskId}`)
      const v = d.validation || {}
      hm.phase = '完成'
      hm.chain = v.handoffs?.length ? ['Planner', ...v.handoffs.map(h => h.split('->')[1])] : hm.chain
      messages.value.push({
        id: Date.now(), role: 'agent', agent: 'validator', agentName: 'Validator',
        type: 'validation', passed: v.passed, errors: v.errors || [], handoffs: v.handoffs,
      })
      messages.value.push({
        id: Date.now() + 1, role: 'agent', agent: 'deliver', agentName: 'Deliver',
        type: 'result', image: d.output_path, download: d.output_path,
        entities: v.total_entities, handoffs: v.handoffs?.length, turns: v.turns,
      })
      currentTask.value.stage = 'done'
    } catch (e) {
      messages.value.push({ id: Date.now(), role: 'agent', type: 'text', text: e.message })
    }
    await nextTick(); scroll()
  })
}

async function loadTask(t) {
  currentTask.value = t
  try {
    const d = await api(`/api/tasks/${t.task_id}`)
    messages.value = [
      { id: Date.now(), role: 'user', text: d.request, file: '图纸' },
      { id: Date.now() + 1, role: 'agent', agent: 'deliver', agentName: 'Deliver',
        type: 'result', image: d.output_path, download: d.output_path,
        passed: d.validation?.passed, handoffs: d.validation?.handoffs?.length, turns: d.validation?.turns },
    ]
  } catch (e) {
    messages.value = [{ id: Date.now(), role: 'agent', type: 'text', text: e.message }]
  }
  await nextTick(); scroll()
}

function referenceDrawing(url) {
  messages.value.push({ id: Date.now(), role: 'user', text: '基于这张深化图纸继续处理', file: url })
}
function scroll() { if (stageBody.value) stageBody.value.scrollTop = stageBody.value.scrollHeight }
</script>

<style scoped>
.space { position: relative; height: 100vh; width: 100%; overflow: hidden; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
.bg-layer { position: absolute; inset: -20px; background-size: cover; background-position: center 52%; filter: blur(1.5px) brightness(0.88) saturate(1.05); transform: scale(1.02); }
.bg-veil { position: absolute; inset: 0; background: linear-gradient(180deg, rgba(10,14,20,0.18), rgba(10,14,20,0.42)); }

/* 左侧 dock */
.dock { position: absolute; left: 22px; top: 50%; transform: translateY(-50%); z-index: 10;
  width: 66px; padding: 12px 8px; border-radius: var(--r-pill); display: flex; flex-direction: column; gap: 6px; align-items: center; }
.dock-btn { width: 46px; height: 46px; border-radius: 50%; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
  background: transparent; transition: all 0.2s; }
.dock-btn svg { width: 21px; height: 21px; fill: rgba(255,255,255,0.62); }
.dock-btn:hover, .dock-btn.active { background: rgba(255,255,255,0.16); }
.dock-btn.active svg { fill: #fff; }
.dock-spacer { height: 20px; }
.dock-avatar { width: 40px; height: 40px; border-radius: 50%; background: linear-gradient(135deg,#3b82f6,#1d4ed8);
  display: flex; align-items: center; justify-content: center; color: #fff; font-size: 11px; font-weight: 700; }

/* 中央舞台 */
.stage { position: absolute; left: 108px; right: 330px; top: 22px; bottom: 22px; border-radius: var(--r-xl);
  display: flex; flex-direction: column; overflow: hidden; z-index: 5; }
.stage-toolbar { height: 54px; flex-shrink: 0; display: flex; align-items: center; justify-content: space-between;
  padding: 0 20px; border-bottom: 1px solid rgba(255,255,255,0.1); background: rgba(255,255,255,0.04); }
.toolbar-left, .toolbar-right { display: flex; align-items: center; gap: 10px; }
.tb-dot { width: 9px; height: 9px; border-radius: 50%; background: rgba(255,255,255,0.28); }
.tb-icon { width: 28px; height: 28px; border-radius: 50%; border: none; background: rgba(255,255,255,0.1); color: #fff; cursor: pointer; font-size: 17px; }
.tb-title { font-size: 12px; color: var(--text-secondary); margin-left: 6px; }
.status-pill { display: flex; align-items: center; gap: 6px; padding: 5px 12px; border-radius: var(--r-pill);
  background: rgba(255,255,255,0.1); font-size: 11px; color: var(--text-secondary); }
.status-pill.on { background: rgba(52,211,153,0.15); color: #a7f3d0; }
.status-dot { width: 6px; height: 6px; border-radius: 50%; background: #fbbf24; }
.status-pill.on .status-dot { background: #34d399; box-shadow: 0 0 8px #34d399; }

.stage-body { flex: 1; overflow-y: auto; padding: 24px 32px; }

/* Hero */
.hero { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
.hero-badge { width: 62px; height: 62px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  background: rgba(255,255,255,0.1); border: 1px solid var(--glass-border); margin-bottom: 20px; }
.hero-badge svg { width: 30px; height: 30px; fill: none; stroke: #fff; stroke-width: 1.6; }
.hero h1 { font-size: 30px; font-weight: 600; margin: 0 0 12px; color: var(--text-primary); letter-spacing: -0.5px; }
.hero p { font-size: 13px; color: var(--text-secondary); margin: 0 0 32px; line-height: 1.7; }
.cap-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; width: 100%; max-width: 720px; margin-bottom: 26px; }
.cap { padding: 18px 14px; border-radius: var(--r-md); background: rgba(255,255,255,0.07); border: 1px solid var(--glass-border);
  backdrop-filter: blur(12px); text-align: left; }
.cap-icon { font-size: 22px; color: #fff; margin-bottom: 10px; }
.cap-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.cap-sub { font-size: 11px; color: var(--text-tertiary); margin-top: 4px; }
.hero-tags { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
.tag-pill { padding: 8px 16px; border-radius: var(--r-pill); border: 1px solid var(--glass-border);
  background: rgba(255,255,255,0.08); color: var(--text-secondary); font-size: 12px; cursor: pointer; }
.tag-pill:hover { background: rgba(255,255,255,0.18); color: #fff; }

/* 流程 */
.flow { max-width: 780px; margin: 0 auto; }
.flow-row { margin-bottom: 20px; display: flex; }
.flow-row.user { justify-content: flex-end; }
.bubble.user { max-width: 74%; padding: 14px 18px; border-radius: var(--r-lg) var(--r-lg) 6px var(--r-lg);
  background: rgba(59,130,246,0.22); border: 1px solid rgba(59,130,246,0.35); }
.bubble-label { font-size: 10px; color: var(--text-tertiary); margin-bottom: 6px; }
.bubble-text { font-size: 13px; line-height: 1.7; color: var(--text-primary); }
.file-tag { font-size: 11px; color: #93c5fd; margin-top: 8px; }
.agent-block { width: 100%; }
.agent-head { display: flex; align-items: center; gap: 8px; margin-bottom: 10px; }
.agent-avatar { width: 26px; height: 26px; border-radius: 8px; display: flex; align-items: center; justify-content: center;
  font-size: 12px; background: rgba(59,130,246,0.25); color: #bfdbfe; }
.agent-avatar.validator { background: rgba(52,211,153,0.2); color: #a7f3d0; }
.agent-avatar.deliver { background: rgba(251,191,36,0.2); color: #fde68a; }
.agent-name { font-size: 12px; font-weight: 600; color: var(--text-primary); }
.agent-phase { font-size: 11px; color: var(--text-tertiary); margin-left: auto; }

.handoff-track { display: flex; flex-wrap: wrap; align-items: center; gap: 4px; padding: 12px 14px; border-radius: var(--r-md);
  background: rgba(255,255,255,0.06); border: 1px solid var(--glass-border); }
.hop { display: flex; align-items: center; gap: 4px; }
.hop-node { padding: 4px 10px; border-radius: var(--r-pill); background: rgba(59,130,246,0.18); font-size: 11px; color: #dbeafe; }
.hop-arrow { color: var(--text-tertiary); font-size: 12px; }

.card-inset { margin-top: 10px; padding: 14px; border-radius: var(--r-md); background: rgba(0,0,0,0.22); border: 1px solid rgba(255,255,255,0.08); }
.card-inset.ok { background: rgba(52,211,153,0.08); border-color: rgba(52,211,153,0.25); }
.inset-title { font-size: 12px; font-weight: 600; margin-bottom: 10px; color: var(--text-primary); }
.plan-row { display: flex; gap: 10px; padding: 5px 0; font-size: 11px; align-items: center; }
.plan-num { color: var(--text-tertiary); font-variant-numeric: tabular-nums; }
.plan-op { color: #93c5fd; font-weight: 600; }
.plan-reason { color: var(--text-tertiary); }
.err-row { font-size: 11px; color: #fca5a5; padding: 3px 0; }
.meta-row { font-size: 11px; color: var(--text-tertiary); margin-top: 8px; }

.result-card { margin-top: 10px; padding: 14px; border-radius: var(--r-md); background: rgba(255,255,255,0.06); border: 1px solid var(--glass-border); }
.result-preview { background: rgba(255,255,255,0.05); border-radius: var(--r-sm); overflow: hidden; margin-bottom: 12px; }
.result-preview img { width: 100%; display: block; }
.no-preview { padding: 40px; text-align: center; color: var(--text-tertiary); font-size: 12px; }
.result-meta { display: flex; gap: 24px; margin-bottom: 12px; }
.meta-item { font-size: 11px; color: var(--text-tertiary); }
.meta-item b { color: #fff; margin-left: 5px; }
.result-btns { display: flex; gap: 8px; }
.pill-btn { padding: 8px 16px; border-radius: var(--r-pill); font-size: 11px; cursor: pointer; text-decoration: none;
  background: rgba(255,255,255,0.12); border: 1px solid var(--glass-border); color: var(--text-primary); display: inline-block; }
.pill-btn.primary { background: linear-gradient(135deg,#3b82f6,#2563eb); border: none; color: #fff; }

/* 控制条 */
.control-bar { flex-shrink: 0; margin: 0 16px 6px; padding: 8px 10px; border-radius: var(--r-pill);
  background: rgba(255,255,255,0.1); border: 1px solid var(--glass-border); display: flex; align-items: center; gap: 8px; }
.ctrl-btn { width: 34px; height: 34px; border-radius: 50%; border: none; cursor: pointer; flex-shrink: 0;
  background: rgba(255,255,255,0.14); color: #fff; font-size: 16px; }
.file-mini { display: flex; align-items: center; gap: 6px; padding: 4px 10px; border-radius: var(--r-pill);
  background: rgba(255,255,255,0.1); font-size: 11px; color: #dbeafe; white-space: nowrap; }
.file-mini button { background: none; border: none; color: var(--text-tertiary); cursor: pointer; }
.cmd-input { flex: 1; background: transparent; border: none; outline: none; resize: none; color: #fff;
  font-size: 12px; font-family: inherit; min-height: 22px; max-height: 80px; padding: 4px 0; }
.cmd-input::placeholder { color: rgba(255,255,255,0.42); }
.send-btn { width: 34px; height: 34px; border-radius: 50%; border: none; cursor: pointer; flex-shrink: 0;
  background: linear-gradient(135deg,#3b82f6,#2563eb); color: #fff; font-size: 14px; }
.send-btn:disabled { background: rgba(255,255,255,0.14); color: var(--text-tertiary); cursor: not-allowed; }
.control-hint { flex-shrink: 0; text-align: center; font-size: 10px; color: rgba(255,255,255,0.38); padding-bottom: 12px; }

/* 右侧消息面板 */
.messages { position: absolute; right: 22px; top: 22px; bottom: 22px; width: 290px; border-radius: var(--r-xl);
  z-index: 5; display: flex; flex-direction: column; overflow: hidden; }
.msg-head { display: flex; align-items: center; justify-content: space-between; padding: 20px 18px 12px; font-size: 16px; font-weight: 600; color: #fff; }
.msg-more { background: none; border: none; color: var(--text-tertiary); cursor: pointer; font-size: 16px; }
.msg-search { margin: 0 14px 12px; padding: 8px 12px; border-radius: var(--r-sm); background: rgba(255,255,255,0.08); font-size: 11px; color: var(--text-tertiary); }
.msg-search span { margin-right: 6px; }
.msg-list { flex: 1; overflow-y: auto; padding: 0 10px; }
.msg-empty { font-size: 11px; color: var(--text-tertiary); text-align: center; padding: 30px 0; }
.msg-item { display: flex; gap: 9px; padding: 9px; border-radius: var(--r-sm); cursor: pointer; margin-bottom: 3px; }
.msg-item:hover, .msg-item.sel { background: rgba(255,255,255,0.1); }
.msg-avatar { width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg,#3b82f6,#1d4ed8); color: #fff; font-size: 14px; }
.msg-content { min-width: 0; flex: 1; }
.msg-line1 { display: flex; justify-content: space-between; align-items: center; font-size: 11px; }
.msg-line1 b { color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.msg-line1 span { color: var(--text-tertiary); font-size: 10px; flex-shrink: 0; }
.msg-line2 { font-size: 10px; color: var(--text-tertiary); margin-top: 4px; }
.msg-foot { padding: 12px 16px; border-top: 1px solid rgba(255,255,255,0.08); font-size: 10px; color: var(--text-tertiary); display: flex; align-items: center; gap: 6px; }
.foot-dot { width: 6px; height: 6px; border-radius: 50%; background: #34d399; }

.err-banner { position: absolute; left: 50%; bottom: 14px; transform: translateX(-50%); z-index: 20;
  padding: 8px 16px; border-radius: var(--r-pill); font-size: 11px; color: #fff; display: flex; align-items: center; gap: 8px; }
.err-banner button { background: rgba(255,255,255,0.14); border: none; color: #fff; border-radius: var(--r-pill); padding: 3px 10px; cursor: pointer; }
</style>
