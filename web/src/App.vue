<template>
  <div class="app">
    <!-- 侧栏 -->
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-icon">▤</div>
        <span class="brand-name">CAD Agent</span>
      </div>

      <button class="new-task" @click="newTask">
        <span>＋</span> 新建深化任务
      </button>

      <div class="history-label">深化记录</div>
      <div class="history-list">
        <div v-if="initError" class="history-empty">未连接，无法加载</div>
        <div v-else-if="!history.length" class="history-empty">暂无深化记录</div>
        <div v-for="t in history" :key="t.task_id" class="history-item"
             :class="{ active: currentTask && currentTask.task_id === t.task_id }"
             @click="loadTask(t)">
          <div class="history-icon">▤</div>
          <div class="history-info">
            <div class="history-title">{{ t.request }}</div>
            <div class="history-time">{{ t.time_label }} · {{ stageLabel(t.stage) }}</div>
          </div>
        </div>
      </div>

      <div class="user-card">
        <div class="user-avatar">{{ (identity.user_id || 'BZ-0216').slice(-4) }}</div>
        <div class="user-info">
          <div class="user-id">{{ identity.user_id || 'BZ-0216' }}</div>
          <div class="user-role">{{ identity.role_name || '深化设计师' }} · {{ identity.quota_per_day || 200 }} 次/日</div>
        </div>
      </div>
    </aside>

    <!-- 主区 -->
    <main class="main">
      <header class="topbar">
        <span class="topbar-title">施工图深化工作台</span>
        <div class="topbar-right">
          <span class="dot" :class="{ on: serverOk }"></span>
          <span class="status">{{ serverOk ? '局域网已连接' : '未连接' }}</span>
        </div>
      </header>

      <div v-if="initError" class="conn-banner">
        <span>⚠</span> {{ initError }}
        <button @click="init">重试</button>
      </div>

      <div class="content" ref="contentEl">
        <!-- 空状态 -->
        <div v-if="!currentTask && !messages.length" class="hero">
          <div class="hero-logo">▤</div>
          <h1>让施工图深化，交给 Agent</h1>
          <p class="hero-sub">上传 DXF 图纸，用自然语言描述深化需求；规划、生成、执行、校验四步自动完成</p>

          <div class=" capability-grid">
            <div class="cap-card glass-card" v-for="c in capabilities" :key="c.title">
              <div class="cap-icon">{{ c.icon }}</div>
              <div class="cap-title">{{ c.title }}</div>
              <div class="cap-desc">{{ c.desc }}</div>
            </div>
          </div>

          <div class="quick-tags">
            <button v-for="q in quickPrompts" :key="q.label" class="quick-tag" @click="input = q.text">
              {{ q.label }}
            </button>
          </div>
        </div>

        <!-- 对话/执行流程 -->
        <div v-else class="conversation">
          <div v-for="m in messages" :key="m.id" class="msg" :class="m.role">
            <div v-if="m.role === 'user'" class="user-msg glass-card">
              <div class="msg-text">{{ m.text }}</div>
              <div v-if="m.file" class="msg-file">▤ {{ m.file }}</div>
            </div>
            <div v-else class="agent-msg glass-card">
              <div class="agent-head">
                <span class="agent-icon">▤</span>
                <span>CAD Agent</span>
                <span class="stage-tag">{{ m.stageLabel }}</span>
              </div>

              <!-- 四节点流水线 -->
              <div v-if="m.type === 'pipeline'" class="pipeline">
                <div v-for="(n, i) in nodes" :key="n.key" class="node"
                     :class="{ done: i < m.step, active: i === m.step, wait: i > m.step }">
                  <div class="node-dot">{{ i < m.step ? '✓' : i + 1 }}</div>
                  <div class="node-name">{{ n.label }}</div>
                  <div class="node-desc">{{ n.desc }}</div>
                </div>
              </div>

              <!-- 计划展示 -->
              <div v-if="m.type === 'plan'" class="plan-box">
                <div class="plan-title">执行计划（{{ m.steps.length }} 步）</div>
                <div v-for="(s, i) in m.steps" :key="i" class="plan-step">
                  <span class="step-num">{{ i + 1 }}</span>
                  <span class="step-op">{{ s.op }}</span>
                  <span class="step-reason">{{ s.reason }}</span>
                </div>
              </div>

              <!-- 校验结果 -->
              <div v-if="m.type === 'validation'" class="validation-box" :class="{ pass: m.passed }">
                <div class="val-title">{{ m.passed ? '✓ 校验通过' : '⚠ 发现问题，正在重新规划' }}</div>
                <div v-for="(e, i) in m.errors" :key="i" class="val-error">{{ e }}</div>
              </div>

              <!-- 最终结果 -->
              <div v-if="m.type === 'result'" class="result-box">
                <div v-if="m.image" class="drawing-preview">
                  <img :src="m.image" alt="深化后图纸" />
                </div>
                <div class="result-info">
                  <div class="result-stat"><span>处理实体</span><b>{{ m.entities || '—' }}</b></div>
                  <div class="result-stat"><span>使用后端</span><b>{{ m.backend || 'auto' }}</b></div>
                  <div class="result-stat"><span>校验</span><b>{{ m.passed ? '通过' : '需复核' }}</b></div>
                </div>
                <div class="result-actions">
                  <a :href="m.download" download class="btn primary">下载 DXF</a>
                  <button class="btn" @click="referenceDrawing(m.download)">引用此图</button>
                </div>
              </div>

              <div v-if="m.type === 'text'" class="agent-text">{{ m.text }}</div>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-dock" :class="{ over: dragOver }"
           @dragover.prevent="dragOver = true" @dragleave.prevent="dragOver = false" @drop.prevent="onDrop">
        <div v-if="dragOver" class="drop-overlay">松开上传 DXF 图纸</div>

        <div v-if="file" class="file-chip">
          <span class="chip-icon">▤</span>
          <span>{{ file.name }}</span>
          <button @click="file = null">×</button>
        </div>

        <div class="input-box glass-card-strong">
          <button class="icon-btn" @click="fileInput.click()" title="上传图纸">▤</button>
          <input ref="fileInput" type="file" accept=".dxf,.dwg" hidden @change="onFileChange" />
          <textarea v-model="input" rows="1" placeholder="描述深化需求，如：把所有 WALL 图层墙线改为 200 厚并批量标注…"
                    :disabled="!serverOk"
                    @keydown.enter.exact.prevent="submit"></textarea>
          <button class="send" :disabled="!serverOk || (!input.trim() || !file)" @click="submit">➤</button>
        </div>
        <div class="input-hint">Enter 发送 · 支持 DXF / DWG（DWG 自动转 DXF）</div>
      </div>
    </main>
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
const file = ref(null)
const input = ref('')
const fileInput = ref(null)
const contentEl = ref(null)
const dragOver = ref(false)
const currentTask = ref(null)
const messages = ref([])
const history = ref([])

const nodes = [
  { key: 'planner', label: 'Planner', desc: '解析需求 · 读取图纸' },
  { key: 'coder', label: 'Coder', desc: '生成 CAD 操作' },
  { key: 'executor', label: 'Executor', desc: '副本上执行' },
  { key: 'validator', label: 'Validator', desc: '规则 + 语义校验' },
]

const capabilities = [
  { icon: '▤', title: '图层整理', desc: '批量规范图层命名、合并冗余图层' },
  { icon: '⌗', title: '批量标注', desc: '按图层与构件类型自动生成尺寸标注' },
  { icon: '⊞', title: '门窗布置', desc: '按开间与规范批量插入门窗图块' },
  { icon: '✓', title: '规范校验', desc: '出图前自动检查图层与标注合规性' },
]

const quickPrompts = [
  { label: '图层规范化', text: '检查所有图层命名，按 ARCH_ 前缀规范重命名不合规图层，删除空图层' },
  { label: '批量标注', text: '对 WALL 图层的墙体批量添加线性标注，标注样式使用 ARCH_DIM' },
  { label: '墙线加厚', text: '将所有 WALL 图层的墙线线宽改为 0.35mm，并偏移生成双线' },
  { label: '房间识别', text: '识别墙体围合的房间边界，统计每个房间的面积' },
]

function fingerprint() {
  let id = localStorage.getItem('cad_agent_device')
  if (id) return id
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  ctx.fillText('cad-agent', 2, 2)
  const sig = canvas.toDataURL().slice(-48)
  const raw = [navigator.userAgent, navigator.language,
    `${screen.width}x${screen.height}`, String(new Date().getTimezoneOffset()), sig,
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
  } catch (e) {
    initError.value = e.message || '连接失败'
  }
}

onMounted(init)

function stageLabel(s) {
  return ({ queued: '排队中', planned: '已规划', coded: '生成中', executed: '执行中',
    validated: '校验中', done: '已完成', failed: '失败' })[s] || s
}

function onFileChange(e) { file.value = e.target.files[0]; e.target.value = '' }
function onDrop(e) {
  dragOver.value = false
  const f = e.dataTransfer.files[0]
  if (f && /\.(dxf|dwg)$/i.test(f.name)) file.value = f
}
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

    messages.value.push({ id: Date.now() + 1, role: 'agent', type: 'pipeline', step: 0, stageLabel: '规划中' })
    const pipe = messages.value[messages.value.length - 1]

    listen(r.task_id, pipe)
  } catch (e) {
    messages.value.push({ id: Date.now() + 2, role: 'agent', type: 'text', stageLabel: '错误', text: e.message })
  }
  await nextTick(); scroll()
}

function listen(taskId, pipe) {
  const es = new EventSource(`${API}/api/cad/stream?task_id=${taskId}&device_id=${deviceId.value}`)
  es.addEventListener('progress', (e) => {
    const d = JSON.parse(e.data)
    const map = { planner: 0, coder: 1, executor: 2, validator: 3 }
    if (map[d.stage] !== undefined) pipe.step = Math.max(pipe.step, map[d.stage] + 1)
    pipe.stageLabel = d.msg || d.stage
  })
  es.addEventListener('done', async () => {
    es.close()
    try {
      const detail = await api(`/api/tasks/${taskId}`)
      const v = detail.validation || {}
      pipe.step = 4
      pipe.stageLabel = '完成'
      messages.value.push({
        id: Date.now(), role: 'agent', type: 'plan', stageLabel: '执行计划',
        steps: detail.messages.filter(m => m.role === 'planner'),
      })
      messages.value.push({
        id: Date.now() + 1, role: 'agent', type: 'validation', stageLabel: '校验',
        passed: v.passed, errors: v.errors || [],
      })
      messages.value.push({
        id: Date.now() + 2, role: 'agent', type: 'result', stageLabel: '交付',
        image: detail.output_path, download: detail.output_path,
        entities: detail.drawing_info?.total_entities, backend: 'auto', passed: v.passed,
      })
      currentTask.value.stage = 'done'
    } catch (e) {
      messages.value.push({ id: Date.now(), role: 'agent', type: 'text', stageLabel: '错误', text: e.message })
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
      { id: Date.now() + 1, role: 'agent', type: 'result', stageLabel: '历史结果',
        image: d.output_path, download: d.output_path, passed: d.validation?.passed },
    ]
  } catch (e) {
    messages.value = [{ id: Date.now(), role: 'agent', type: 'text', stageLabel: '错误', text: e.message }]
  }
  await nextTick(); scroll()
}

function referenceDrawing(url) {
  messages.value.push({ id: Date.now(), role: 'user', text: '基于这张深化后的图纸继续处理', file: url })
  input.value?.focus?.()
}

function scroll() { if (contentEl.value) contentEl.value.scrollTop = contentEl.value.scrollHeight }
</script>

<style scoped>
.app { display: flex; height: 100vh; width: 100%;
  background: linear-gradient(135deg, var(--bg-start), var(--bg-end));
  color: var(--text-main); font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }

/* 侧栏 */
.sidebar { width: 268px; flex-shrink: 0; display: flex; flex-direction: column;
  background: rgba(255,255,255,0.42); backdrop-filter: blur(20px);
  border-right: 1px solid rgba(255,255,255,0.6); }
.brand { display: flex; align-items: center; gap: 10px; padding: 20px 18px; border-bottom: 1px solid rgba(255,255,255,0.5); }
.brand-icon { width: 32px; height: 32px; border-radius: 9px; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg, #2563eb, #0ea5e9); color: #fff; font-size: 17px; }
.brand-name { font-size: 16px; font-weight: 700; color: #1e3a8a; }
.new-task { margin: 16px 14px 8px; padding: 11px; border-radius: 12px; cursor: pointer;
  background: linear-gradient(135deg, rgba(37,99,235,0.9), rgba(14,165,233,0.85)); color: #fff;
  border: 1px solid rgba(255,255,255,0.4); font-size: 13px; box-shadow: 0 4px 12px rgba(37,99,235,0.25); }
.new-task:hover { filter: brightness(1.08); }
.new-task span { font-size: 16px; margin-right: 4px; }
.history-label { font-size: 11px; color: var(--text-tertiary); padding: 14px 18px 8px; text-transform: uppercase; letter-spacing: 1px; }
.history-list { flex: 1; overflow-y: auto; padding: 0 10px; }
.history-empty { font-size: 12px; color: var(--text-tertiary); padding: 20px; text-align: center; }
.history-item { display: flex; gap: 10px; padding: 10px; border-radius: 10px; cursor: pointer; margin-bottom: 4px; }
.history-item:hover { background: rgba(255,255,255,0.5); }
.history-item.active { background: rgba(37,99,235,0.1); }
.history-icon { width: 30px; height: 30px; border-radius: 8px; background: rgba(37,99,235,0.12);
  color: #2563eb; display: flex; align-items: center; justify-content: center; flex-shrink: 0; }
.history-info { min-width: 0; }
.history-title { font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; color: var(--text-main); }
.history-time { font-size: 10px; color: var(--text-tertiary); margin-top: 3px; }
.user-card { display: flex; align-items: center; gap: 10px; padding: 16px; border-top: 1px solid rgba(255,255,255,0.5); }
.user-avatar { width: 34px; height: 34px; border-radius: 50%; background: linear-gradient(135deg,#3b82f6,#1d4ed8);
  color: #fff; display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 600; }
.user-id { font-size: 12px; font-weight: 700; }
.user-role { font-size: 10px; color: var(--text-tertiary); margin-top: 2px; }

/* 主区 */
.main { flex: 1; display: flex; flex-direction: column; min-width: 0; }
.topbar { height: 56px; flex-shrink: 0; display: flex; align-items: center; justify-content: space-between;
  padding: 0 26px; background: rgba(255,255,255,0.35); border-bottom: 1px solid rgba(255,255,255,0.5); }
.topbar-title { font-size: 14px; font-weight: 600; color: #1e3a8a; }
.topbar-right { display: flex; align-items: center; gap: 7px; font-size: 11px; color: var(--text-secondary); }
.dot { width: 7px; height: 7px; border-radius: 50%; background: #f59e0b; }
.dot.on { background: #22c55e; box-shadow: 0 0 8px rgba(34,197,94,0.6); }
.conn-banner { padding: 8px 26px; background: rgba(245,158,11,0.12); border-bottom: 1px solid rgba(245,158,11,0.25);
  font-size: 11px; color: #92400e; display: flex; gap: 8px; align-items: center; }
.conn-banner button { margin-left: auto; padding: 3px 10px; border-radius: 5px; cursor: pointer;
  background: rgba(245,158,11,0.2); border: 1px solid rgba(245,158,11,0.4); color: #92400e; font-size: 11px; }
.content { flex: 1; overflow-y: auto; padding: 30px 26px; }

/* Hero */
.hero { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; }
.hero-logo { font-size: 40px; color: #2563eb; margin-bottom: 14px; text-shadow: 0 4px 16px rgba(37,99,235,0.3); }
.hero h1 { font-size: 28px; margin: 0 0 10px; color: #1e3a8a; }
.hero-sub { font-size: 13px; color: var(--text-secondary); max-width: 560px; line-height: 1.7; margin: 0 0 28px; }
.capability-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; max-width: 860px; width: 100%; margin-bottom: 24px; }
.cap-card { padding: 18px 14px; text-align: left; }
.cap-icon { font-size: 22px; color: #2563eb; margin-bottom: 8px; }
.cap-title { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
.cap-desc { font-size: 11px; color: var(--text-tertiary); line-height: 1.5; }
.quick-tags { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; }
.quick-tag { padding: 8px 14px; font-size: 12px; cursor: pointer; border-radius: 18px;
  background: rgba(255,255,255,0.55); border: 1px solid rgba(37,99,235,0.2); color: #1e40af; }
.quick-tag:hover { background: rgba(37,99,235,0.1); }

/* 对话 */
.conversation { max-width: 900px; margin: 0 auto; }
.msg { display: flex; margin-bottom: 20px; }
.msg.user { justify-content: flex-end; }
.msg.agent { justify-content: flex-start; }
.user-msg { padding: 12px 16px; max-width: 72%; border-radius: 16px 16px 4px 16px; background: rgba(37,99,235,0.12); }
.msg-text { font-size: 13px; line-height: 1.6; }
.msg-file { font-size: 11px; color: #2563eb; margin-top: 6px; }
.agent-msg { padding: 14px 16px; width: 100%; border-radius: 16px 16px 16px 4px; }
.agent-head { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 12px; font-weight: 600; color: #1e3a8a; }
.agent-icon { width: 22px; height: 22px; border-radius: 6px; background: rgba(37,99,235,0.15); display: flex; align-items: center; justify-content: center; }
.stage-tag { margin-left: auto; font-size: 11px; font-weight: 400; color: var(--text-tertiary); }

.pipeline { display: flex; gap: 8px; }
.node { flex: 1; padding: 10px; border-radius: 10px; background: rgba(148,163,184,0.1); border: 1px solid transparent; }
.node.active { background: rgba(37,99,235,0.12); border-color: rgba(37,99,235,0.4); }
.node.done { background: rgba(34,197,94,0.1); }
.node-dot { width: 20px; height: 20px; border-radius: 50%; display: flex; align-items: center; justify-content: center;
  font-size: 10px; background: rgba(148,163,184,0.2); margin-bottom: 6px; }
.node.active .node-dot { background: #2563eb; color: #fff; }
.node.done .node-dot { background: #22c55e; color: #fff; }
.node-name { font-size: 12px; font-weight: 600; }
.node-desc { font-size: 10px; color: var(--text-tertiary); margin-top: 2px; }

.plan-box { margin-top: 12px; padding: 12px; border-radius: 10px; background: rgba(255,255,255,0.5); }
.plan-title { font-size: 12px; font-weight: 600; margin-bottom: 8px; }
.plan-step { display: flex; gap: 8px; align-items: center; padding: 5px 0; font-size: 11px; }
.step-num { width: 18px; height: 18px; border-radius: 50%; background: rgba(37,99,235,0.15); color: #2563eb;
  display: flex; align-items: center; justify-content: center; font-size: 9px; }
.step-op { font-weight: 600; color: #1e40af; }
.step-reason { color: var(--text-tertiary); }

.validation-box { margin-top: 12px; padding: 10px 12px; border-radius: 10px; background: rgba(245,158,11,0.1); font-size: 11px; }
.validation-box.pass { background: rgba(34,197,94,0.1); }
.val-title { font-weight: 600; }
.val-error { color: #b45309; margin-top: 4px; }

.result-box { margin-top: 12px; }
.drawing-preview { background: rgba(255,255,255,0.7); border-radius: 10px; padding: 10px; margin-bottom: 10px; }
.drawing-preview img { width: 100%; display: block; border-radius: 6px; }
.result-info { display: flex; gap: 16px; margin-bottom: 10px; }
.result-stat { font-size: 11px; color: var(--text-secondary); }
.result-stat b { color: #1e40af; margin-left: 4px; }
.result-actions { display: flex; gap: 8px; }
.btn { padding: 8px 14px; border-radius: 8px; font-size: 11px; cursor: pointer; text-decoration: none;
  background: rgba(255,255,255,0.7); border: 1px solid rgba(37,99,235,0.25); color: #1e40af; display: inline-block; }
.btn.primary { background: linear-gradient(135deg,#2563eb,#0ea5e9); color: #fff; border: none; }
.agent-text { font-size: 12px; line-height: 1.7; color: var(--text-secondary); }

/* 输入 */
.input-dock { flex-shrink: 0; padding: 12px 26px 18px; position: relative;
  background: linear-gradient(180deg, transparent, rgba(216,229,244,0.7) 40%); }
.drop-overlay { position: absolute; inset: 0 26px 18px; border: 2px dashed #2563eb; border-radius: 14px;
  background: rgba(37,99,235,0.08); display: flex; align-items: center; justify-content: center;
  color: #1e40af; font-size: 13px; z-index: 10; pointer-events: none; }
.file-chip { display: inline-flex; align-items: center; gap: 7px; padding: 5px 10px; margin-bottom: 8px;
  background: rgba(255,255,255,0.7); border-radius: 8px; font-size: 11px; border: 1px solid rgba(37,99,235,0.2); }
.chip-icon { color: #2563eb; }
.file-chip button { background: none; border: none; cursor: pointer; color: #94a3b8; font-size: 14px; }
.input-box { max-width: 900px; margin: 0 auto; display: flex; align-items: flex-end; gap: 8px; padding: 10px 12px; }
.icon-btn { background: rgba(37,99,235,0.1); border: none; border-radius: 8px; width: 32px; height: 32px;
  cursor: pointer; color: #2563eb; font-size: 16px; flex-shrink: 0; }
.input-box textarea { flex: 1; background: transparent; border: none; outline: none; resize: none;
  color: var(--text-main); font-size: 13px; line-height: 1.55; font-family: inherit; min-height: 22px; max-height: 110px; padding: 6px 0; }
.input-box textarea::placeholder { color: #94a3b8; }
.send { width: 32px; height: 32px; border-radius: 8px; border: none; cursor: pointer; flex-shrink: 0;
  background: linear-gradient(135deg,#2563eb,#0ea5e9); color: #fff; }
.send:disabled { background: #cbd5e1; cursor: not-allowed; }
.input-hint { max-width: 900px; margin: 6px auto 0; font-size: 10px; color: var(--text-tertiary); text-align: center; }
</style>
