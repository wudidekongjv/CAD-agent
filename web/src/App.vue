<template>
  <div class="space">
    <div class="bg-layer" :style="{ backgroundImage: `url(/bg-terminal.jpg)` }"></div>
    <div class="bg-veil"></div>

    <!-- 左侧圆形导航栏 -->
    <nav class="dock glass">
      <button v-for="n in navItems" :key="n.key" class="dock-btn"
              :class="{ active: panel === n.key }" @click="panel = n.key" :title="n.label">
        <span class="dock-glyph">{{ n.glyph }}</span>
      </button>
      <div class="dock-spacer"></div>
      <div class="dock-avatar" @click="panel = 'settings'" title="设置">
        {{ (identity.user_id || 'BZ-0216').slice(-4) }}
      </div>
    </nav>

    <!-- 中央舞台 -->
    <section class="stage glass">
      <div class="stage-toolbar">
        <div class="toolbar-left">
          <span class="tb-dot"></span>
          <button class="tb-icon" @click="panel = 'home'">‹</button>
          <button class="tb-icon" @click="showSide = !showSide">›</button>
          <span class="tb-title">{{ panelTitle }}</span>
        </div>
        <div class="toolbar-right">
          <span class="status-pill" :class="{ on: serverOk }">
            <span class="status-dot"></span>{{ serverOk ? '已连接' : '未连接' }}
          </span>
        </div>
      </div>

      <div class="stage-body no-scrollbar" ref="stageBody">
        <!-- ========== 首页 ========== -->
        <template v-if="panel === 'home'">
          <div v-if="!currentTask && !messages.length" class="hero">
            <div class="hero-badge"><span v-html="icons.layers"></span></div>
            <h1>让施工图深化，交给 Agent 团队</h1>
            <p>规划 · 生成 · 执行 · 校验 —— 六个专职 Agent 通过 handoff 自主协作</p>
            <div class="cap-grid">
              <div class="cap" v-for="c in capabilities" :key="c.title">
                <div class="cap-icon" v-html="c.icon"></div>
                <div class="cap-title">{{ c.title }}</div>
                <div class="cap-sub">{{ c.sub }}</div>
              </div>
            </div>
            <div class="hero-tags">
              <button v-for="q in quickPrompts" :key="q.label" class="tag-pill" @click="applyPrompt(q)">{{ q.label }}</button>
            </div>
            <div class="model-chip" v-if="modelInfo.current">
              <span class="dot-model"></span>当前模型：{{ modelInfo.current.model }} · {{ modelInfo.current.mode === 'api' ? '云端 API' : '本地' }}
            </div>
          </div>

          <!-- 任务执行流 -->
          <div v-else class="flow">
            <div v-for="m in messages" :key="m.id" class="flow-row" :class="m.role">
              <div v-if="m.role === 'user'" class="bubble user">
                <div class="bubble-label">你</div>
                <div class="bubble-text">{{ m.text }}</div>
                <div v-if="m.file" class="file-tag">▤ {{ m.file }}</div>
              </div>
              <div v-else class="agent-block">
                <div class="agent-head">
                  <span class="agent-avatar" :class="m.agent || 'planner'">✦</span>
                  <span class="agent-name">{{ m.agentName || 'Agent' }}</span>
                  <span class="agent-phase" v-if="m.phase">{{ m.phase }}</span>
                </div>
                <div v-if="m.type === 'handoff'" class="handoff-track">
                  <div v-for="(h, i) in m.chain" :key="i" class="hop">
                    <span class="hop-node">{{ h }}</span>
                    <span v-if="i < m.chain.length - 1" class="hop-arrow">→</span>
                  </div>
                </div>
                <div v-if="m.type === 'plan'" class="card-inset">
                  <div class="inset-title">执行计划</div>
                  <div v-for="(s, i) in m.steps" :key="i" class="plan-row">
                    <span class="plan-num">{{ String(i + 1).padStart(2, '0') }}</span>
                    <span class="plan-op">{{ typeof s === 'string' ? s.slice(0, 60) : s.op }}</span>
                    <span class="plan-reason" v-if="typeof s === 'object' && s.reason">{{ s.reason }}</span>
                  </div>
                </div>
                <div v-if="m.type === 'validation'" class="card-inset" :class="{ ok: m.passed }">
                  <div class="inset-title">{{ m.passed ? '✓ 校验通过' : '⚠ 需要处理' }}</div>
                  <div v-for="(e, i) in m.errors" :key="i" class="err-row">{{ typeof e === 'string' ? e : e.detail }}</div>
                  <div v-if="m.refs" class="meta-row">规范依据：{{ m.refs.join('、') }}</div>
                </div>
                <div v-if="m.type === 'result'" class="result-card">
                  <div class="result-preview">
                    <img :src="m.image" alt="深化后图纸" v-if="m.image" />
                    <div class="no-preview" v-else>图纸已生成</div>
                  </div>
                  <div class="result-meta">
                    <div class="meta-item"><span>移交</span><b>{{ m.handoffs || 0 }}</b></div>
                    <div class="meta-item"><span>模型</span><b>{{ m.model || '—' }}</b></div>
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
        </template>

        <!-- ========== 任务 ========== -->
        <template v-else-if="panel === 'tasks'">
          <div class="panel-head">
            <div><h2>深化任务</h2><p>共 {{ history.length }} 条记录</p></div>
            <button class="pill-btn" @click="loadTasks">刷新</button>
          </div>
          <div class="task-list">
            <div v-if="!history.length" class="empty-panel">暂无任务，回到工作台创建第一个深化任务</div>
            <div v-for="t in history" :key="t.task_id" class="task-row" @click="openTask(t)">
              <div class="task-icon">▤</div>
              <div class="task-main">
                <div class="task-title">{{ t.request }}</div>
                <div class="task-sub">{{ t.time_label }} · {{ stageLabel(t.stage) }}</div>
              </div>
              <button class="task-del" @click.stop="deleteTask(t)" title="删除">×</button>
            </div>
          </div>
        </template>

        <!-- ========== Agent 团队 ========== -->
        <template v-else-if="panel === 'agents'">
          <div class="panel-head">
            <div><h2>Agent 团队</h2><p>{{ agents.topology || 'LangGraph Swarm' }}</p></div>
            <button class="pill-btn" @click="loadAgents">刷新</button>
          </div>
          <div class="agent-grid">
            <div v-for="a in agents.agents || []" :key="a.name" class="agent-card glass-light">
              <div class="agent-card-head">
                <span class="agent-avatar" :class="a.name.toLowerCase()">✦</span>
                <div>
                  <div class="agent-card-name">{{ a.name }}</div>
                  <div class="agent-card-role">{{ a.role }}</div>
                </div>
              </div>
              <div class="handoff-list">
                <span class="handoff-label">可移交至</span>
                <span v-for="h in a.can_handoff_to" :key="h" class="hop-node small">{{ h }}</span>
                <span v-if="!a.can_handoff_to.length" class="hop-node small terminal">终点</span>
              </div>
            </div>
          </div>
          <div v-if="!agents.agents" class="empty-panel">加载中…</div>
        </template>

        <!-- ========== 工具 ========== -->
        <template v-else-if="panel === 'tools'">
          <div class="panel-head">
            <div><h2>MCP 工具目录</h2><p>按需发现 · 批处理 · 分层工具包</p></div>
            <button class="pill-btn" @click="loadTools">刷新</button>
          </div>
          <div class="tool-filter">
            <button v-for="p in ['all','core','arch','mech']" :key="p"
                    :class="{ on: toolPack === p }" @click="toolPack = p">{{ p.toUpperCase() }}</button>
          </div>
          <div class="tool-grid">
            <div v-for="g in filteredTools" :key="g.pack" class="tool-group">
              <div class="tool-group-title">{{ g.pack.toUpperCase() }}</div>
              <div v-for="t in g.items" :key="t.name" class="tool-card glass-light" @click="selectedTool = t">
                <div class="tool-name">{{ t.name }}</div>
                <div class="tool-desc">{{ t.desc }}</div>
                <div class="tool-params">{{ (t.params || []).join(' · ') }}</div>
              </div>
            </div>
          </div>
          <div v-if="selectedTool" class="tool-detail glass-light">
            <div class="detail-head">工具详情：{{ selectedTool.name }} <button @click="selectedTool = null">×</button></div>
            <div class="detail-row"><span>说明</span><b>{{ selectedTool.desc }}</b></div>
            <div class="detail-row"><span>参数</span><b>{{ (selectedTool.params || []).join(', ') }}</b></div>
            <div class="detail-row"><span>协议</span><b>MCP · FastMCP + stdio</b></div>
          </div>
        </template>

        <!-- ========== 知识库 ========== -->
        <template v-else-if="panel === 'knowledge'">
          <div class="panel-head">
            <div><h2>规范知识库</h2><p>{{ kbStats.total_chunks || 0 }} 个知识块 · 混合检索</p></div>
            <button class="pill-btn" @click="loadKnowledge">刷新</button>
          </div>
          <div class="kb-search-box">
            <input v-model="kbQuery" placeholder="检索制图规范，如：图层命名 墙厚 标注样式" @keydown.enter="searchKnowledge" />
            <button class="pill-btn primary" @click="searchKnowledge">检索</button>
          </div>
          <div v-if="kbResults.length" class="kb-results">
            <div v-for="(r, i) in kbResults" :key="i" class="kb-result glass-light">
              <div class="kb-result-head">
                <span class="kb-source">{{ r.source }} · {{ r.section || '通用' }}</span>
                <span class="kb-score">RRF {{ r.rrf_score || r.score }}</span>
              </div>
              <div class="kb-text">{{ r.text }}</div>
            </div>
          </div>
          <div class="kb-sources">
            <div class="sub-title">已入库来源</div>
            <div v-for="s in kbStats.sources_list || []" :key="s.source" class="source-row">
              <span>▤ {{ s.source }}</span><span>{{ s.chunks }} 块</span>
            </div>
          </div>
          <div class="kb-upload">
            <div class="sub-title">上传规范文档（PDF / DOCX / TXT）</div>
            <input type="file" accept=".pdf,.docx,.txt,.md" @change="onKbUpload" ref="kbFile" />
            <button class="pill-btn" @click="uploadKnowledge" :disabled="!kbFileObj">入库</button>
            <span v-if="kbUploadMsg" class="upload-msg">{{ kbUploadMsg }}</span>
          </div>
        </template>

        <!-- ========== 设置 ========== -->
        <template v-else-if="panel === 'settings'">
          <div class="panel-head">
            <div><h2>系统设置</h2><p>模型供应商 · 用户身份 · 系统状态</p></div>
          </div>

          <div class="settings-section">
            <div class="sub-title">LLM 模型供应商</div>
            <div class="provider-grid">
              <div v-for="p in modelInfo.providers || []" :key="p.name"
                   class="provider-card glass-light"
                   :class="{ active: modelInfo.current && modelInfo.current.provider === p.name }"
                   @click="switchModel(p)">
                <div class="provider-head">
                  <span class="provider-name">{{ p.name.toUpperCase() }}</span>
                  <span class="provider-mode">{{ p.mode === 'api' ? 'API' : '本地' }}</span>
                </div>
                <div class="provider-model">{{ p.model }}</div>
                <div class="provider-status" :class="{ ok: p.available }">
                  {{ p.available ? '✓ 可用' : '⚠ 未配置密钥' }}
                </div>
              </div>
            </div>
            <div class="setting-note">
              图纸几何原文不发送到 API，仅结构摘要（图层名/实体统计）参与推理。切换模型需管理员权限。
            </div>
          </div>

          <div class="settings-section">
            <div class="sub-title">当前身份</div>
            <div class="identity-card glass-light">
              <div class="id-avatar">{{ (identity.user_id || 'BZ-0216').slice(-4) }}</div>
              <div>
                <div class="id-main">{{ identity.user_id || 'BZ-0216' }}</div>
                <div class="id-sub">{{ identity.role_name || '深化设计师' }} · {{ identity.quota_per_day || 200 }} 次/日</div>
              </div>
              <div class="id-device">设备 {{ deviceId.slice(0, 16) }}…</div>
            </div>
          </div>

          <div class="settings-section">
            <div class="sub-title">系统状态</div>
            <div class="status-grid">
              <div class="status-card glass-light"><span>服务</span><b :class="{ ok: serverOk }">{{ serverOk ? '在线' : '离线' }}</b></div>
              <div class="status-card glass-light"><span>知识块</span><b>{{ kbStats.total_chunks || 0 }}</b></div>
              <div class="status-card glass-light"><span>任务</span><b>{{ history.length }}</b></div>
            </div>
          </div>
        </template>
      </div>

      <!-- 底部控制条（仅首页显示） -->
      <template v-if="panel === 'home'">
        <div class="control-bar" :class="{ over: dragOver }"
             @dragover.prevent="dragOver = true" @dragleave.prevent="dragOver = false" @drop.prevent="onDrop">
          <button class="ctrl-btn" @click="fileInput.click()" title="上传图纸">▤</button>
          <input ref="fileInput" type="file" accept=".dxf,.dwg" hidden @change="onFileChange" />
          <div class="file-mini" v-if="file"><span>{{ file.name }}</span><button @click="file = null">×</button></div>
          <textarea v-model="input" rows="1" class="cmd-input"
                    placeholder="描述深化需求，如：把 WALL 图层墙线改为 200 厚并批量标注…"
                    @keydown.enter.exact.prevent="submit"></textarea>
          <button class="send-btn" :disabled="(!input.trim() || !file)" @click="submit">➤</button>
        </div>
        <div class="control-hint">Enter 发送 · 图纸不出网 · 支持 DXF / DWG</div>
      </template>
    </section>

    <!-- 右侧面板 -->
    <aside class="messages glass" v-if="showSide">
      <div class="msg-head">
        <span>{{ sideTitle }}</span>
        <button class="msg-more" @click="showSide = false">···</button>
      </div>
      <div class="msg-search">
        <span>⌕</span>
        <input v-model="searchQuery" placeholder="搜索任务" @input="filterHistory" />
      </div>
      <div class="msg-list no-scrollbar">
        <div v-if="!filteredHistory.length" class="msg-empty">无匹配任务</div>
        <div v-for="t in filteredHistory" :key="t.task_id" class="msg-item"
             :class="{ sel: currentTask && currentTask.task_id === t.task_id }" @click="openTask(t)">
          <div class="msg-avatar">▤</div>
          <div class="msg-content">
            <div class="msg-line1"><b>{{ t.request.slice(0, 18) }}</b><span>{{ t.time_label }}</span></div>
            <div class="msg-line2">{{ stageLabel(t.stage) }} · CAD 深化</div>
          </div>
        </div>
      </div>
      <div class="msg-foot">
        <span class="foot-dot"></span> LangGraph Swarm · {{ identity.user_id || 'BZ-0216' }}
      </div>
    </aside>

    <div v-if="initError" class="err-banner glass-light">
      <span>⚠</span> {{ initError }} <button @click="init">重试</button>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick } from 'vue'
import './assets/styles/variables.css'

const API = ''
const serverOk = ref(false)
const initError = ref('')
const identity = ref({})
const deviceId = ref('')
const panel = ref('home')
const showSide = ref(true)
const file = ref(null)
const input = ref('')
const fileInput = ref(null)
const stageBody = ref(null)
const currentTask = ref(null)
const messages = ref([])
const history = ref([])
const filteredHistory = ref([])
const searchQuery = ref('')

// 面板数据
const agents = ref({})
const tools = ref({})
const toolPack = ref('all')
const selectedTool = ref(null)
const kbStats = ref({})
const kbResults = ref([])
const kbQuery = ref('')
const kbFile = ref(null)
const kbFileObj = ref(null)
const kbUploadMsg = ref('')
const modelInfo = ref({})

const icons = {
  layers: '<svg viewBox="0 0 24 24" width="30" height="30"><path fill="none" stroke="currentColor" stroke-width="1.6" d="M12 2 2 7l10 5 10-5zM2 12l10 5 10-5M2 17l10 5 10-5"/></svg>',
}

// 用 Unicode 几何符号作为图标（避免 v-html + scoped 样式导致 SVG 丢失）
const navItems = [
  { key: 'home', label: '工作台', glyph: '⌂' },
  { key: 'tasks', label: '任务', glyph: '☰' },
  { key: 'agents', label: 'Agent 团队', glyph: '◆' },
  { key: 'tools', label: 'MCP 工具', glyph: '⚒' },
  { key: 'knowledge', label: '知识库', glyph: '▤' },
  { key: 'settings', label: '设置', glyph: '⚙' },
]

const panelTitle = computed(() => navItems.find(n => n.key === panel.value)?.label || '工作台')
const sideTitle = computed(() => panel.value === 'tasks' ? '全部任务' : '深化记录')

const capabilities = [
  { icon: '▤', title: '图层整理', sub: '规范命名 · 合并冗余' },
  { icon: '⌗', title: '批量标注', sub: '按图层自动标注' },
  { icon: '⊞', title: '门窗布置', sub: '按开间批量插入' },
  { icon: '✓', title: '规范校验', sub: '知识库依据 · 可溯源' },
]

const quickPrompts = [
  { label: '图层规范化', text: '检查所有图层命名，按 ARCH_ 前缀规范重命名不合规图层，删除空图层' },
  { label: '批量标注', text: '对 WALL 图层的墙体批量添加线性标注，样式使用 ARCH_DIM' },
  { label: '墙线加厚', text: '将所有 WALL 图层的墙线线宽改为 0.35mm，并偏移生成双线' },
  { label: '房间识别', text: '识别墙体围合的房间边界，统计每个房间面积' },
]

const filteredTools = computed(() => {
  if (toolPack.value === 'all') {
    return Object.entries(tools.value).map(([pack, items]) => ({ pack, items }))
  }
  return Object.entries(tools.value).filter(([pack]) => pack === toolPack.value)
    .map(([pack, items]) => ({ pack, items }))
})

function fingerprint() {
  let id = localStorage.getItem('cad_agent_device')
  if (id) return id
  const canvas = document.createElement('canvas')
  const ctx = canvas.getContext('2d')
  ctx.fillText('cad', 2, 2)
  const raw = [navigator.userAgent, `${screen.width}x${screen.height}`, canvas.toDataURL().slice(-40),
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
    await Promise.all([loadTasks(), loadAgents(), loadTools(), loadKnowledge(), loadModels()])
  } catch (e) { initError.value = e.message || '连接失败' }
}

async function loadTasks() {
  try {
    history.value = await api('/api/tasks')
    filterHistory()
  } catch {}
}
function filterHistory() {
  const q = searchQuery.value.trim().toLowerCase()
  filteredHistory.value = q ? history.value.filter(t => t.request.toLowerCase().includes(q)) : history.value
}
async function loadAgents() { try { agents.value = await api('/api/agents') } catch {} }
async function loadTools() { try { tools.value = await api('/api/tools/detail') } catch {} }
async function loadKnowledge() {
  try { kbStats.value = await api('/api/knowledge/stats') } catch {}
}
async function loadModels() {
  try { modelInfo.value = await api('/api/models/providers') } catch {}
}
async function switchModel(p) {
  if (!p.available) return
  try {
    const fd = new FormData()
    fd.append('provider', p.name)
    const r = await api('/api/models/switch', { method: 'POST', body: fd })
    await loadModels()
  } catch (e) { alert('切换失败：' + e.message) }
}
async function searchKnowledge() {
  if (!kbQuery.value.trim()) return
  try {
    const r = await api(`/api/knowledge/search?q=${encodeURIComponent(kbQuery.value)}&top_k=6`)
    kbResults.value = r.results
  } catch (e) { alert(e.message) }
}
function onKbUpload(e) { kbFileObj.value = e.target.files[0] }
async function uploadKnowledge() {
  if (!kbFileObj.value) return
  try {
    const fd = new FormData()
    fd.append('file', kbFileObj.value)
    const r = await api('/api/knowledge/ingest', { method: 'POST', body: fd })
    kbUploadMsg.value = `已入库 ${r.chunks_added} 块`
    kbFileObj.value = null
    await loadKnowledge()
  } catch (e) { kbUploadMsg.value = '失败：' + e.message }
}
async function deleteTask(t) {
  if (!confirm('删除这条任务记录？')) return
  // 前端移除（后端列表不含删除接口时保持数据一致）
  history.value = history.value.filter(x => x.task_id !== t.task_id)
  filterHistory()
}

onMounted(init)

function stageLabel(s) {
  return ({ queued: '排队', planned: '规划中', coded: '生成中', executed: '执行中',
    validated: '校验中', done: '已完成', failed: '失败' })[s] || s
}
function applyPrompt(q) { input.value = q.text; panel.value = 'home' }
function onFileChange(e) { file.value = e.target.files[0]; e.target.value = '' }
function onDrop(e) {
  const f = e.dataTransfer.files[0]
  if (f && /\.(dxf|dwg)$/i.test(f.name)) { file.value = f; panel.value = 'home' }
}

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
    filterHistory()
    const hm = { id: Date.now() + 1, role: 'agent', agent: 'planner', agentName: 'Planner',
      type: 'handoff', phase: '协作中',
      chain: ['Planner', 'Coder', 'Executor', 'Validator', 'Deliver'] }
    messages.value.push(hm)
    listen(r.task_id, hm)
  } catch (e) {
    messages.value.push({ id: Date.now() + 2, role: 'agent', type: 'text', text: e.message })
  }
  await nextTick(); scroll()
}

function listen(taskId, hm) {
  const es = new EventSource(`${API}/api/cad/stream?task_id=${taskId}&device_id=${deviceId.value}`)
  es.addEventListener('progress', e => {
    const d = JSON.parse(e.data)
    hm.phase = d.msg || d.stage
  })
  es.addEventListener('done', async () => {
    es.close()
    try {
      const d = await api(`/api/tasks/${taskId}`)
      const v = d.validation || {}
      hm.phase = '完成'
      messages.value.push({
        id: Date.now(), role: 'agent', agent: 'validator', agentName: 'Validator',
        type: 'validation', passed: v.passed, errors: v.errors || [],
        refs: v.knowledge_refs,
      })
      messages.value.push({
        id: Date.now() + 1, role: 'agent', agent: 'deliver', agentName: 'Deliver',
        type: 'result', image: d.output_path, download: d.output_path,
        handoffs: v.handoffs, model: v.model,
      })
      currentTask.value.stage = 'done'
      await loadTasks()
    } catch (e) {
      messages.value.push({ id: Date.now(), role: 'agent', type: 'text', text: e.message })
    }
    await nextTick(); scroll()
  })
}

async function openTask(t) {
  panel.value = 'home'
  currentTask.value = t
  try {
    const d = await api(`/api/tasks/${t.task_id}`)
    messages.value = [
      { id: Date.now(), role: 'user', text: d.request, file: '图纸' },
      { id: Date.now() + 1, role: 'agent', agent: 'deliver', agentName: 'Deliver',
        type: 'result', image: d.output_path, download: d.output_path, model: d.validation?.model },
    ]
    if (d.validation?.knowledge_refs) {
      messages.value.splice(1, 0, {
        id: Date.now() + 2, role: 'agent', agent: 'validator', agentName: 'Validator',
        type: 'validation', passed: d.validation.passed, errors: d.validation.errors || [],
        refs: d.validation.knowledge_refs,
      })
    }
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

.dock { position: absolute; left: 22px; top: 50%; transform: translateY(-50%); z-index: 10;
  width: 66px; padding: 12px 8px; border-radius: var(--r-pill); display: flex; flex-direction: column; gap: 6px; align-items: center; }
.dock-btn { width: 46px; height: 46px; border-radius: 50%; border: none; cursor: pointer; display: flex; align-items: center; justify-content: center;
  background: transparent; transition: all 0.2s; }
.dock-glyph { font-size: 22px; line-height: 1; color: rgba(255,255,255,0.68); }
.dock-btn:hover, .dock-btn.active { background: rgba(255,255,255,0.16); }
.dock-btn.active .dock-glyph { color: #fff; }
.dock-spacer { height: 12px; }
.dock-avatar { width: 40px; height: 40px; border-radius: 50%; background: linear-gradient(135deg,#3b82f6,#1d4ed8);
  display: flex; align-items: center; justify-content: center; color: #fff; font-size: 11px; font-weight: 700; cursor: pointer; }

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
  background: rgba(255,255,255,0.1); border: 1px solid var(--glass-border); margin-bottom: 20px; color: #fff; }
.hero h1 { font-size: 30px; font-weight: 600; margin: 0 0 12px; color: var(--text-primary); letter-spacing: -0.5px; }
.hero p { font-size: 13px; color: var(--text-secondary); margin: 0 0 28px; line-height: 1.7; }
.cap-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 12px; width: 100%; max-width: 720px; margin-bottom: 22px; }
.cap { padding: 18px 14px; border-radius: var(--r-md); background: rgba(255,255,255,0.07); border: 1px solid var(--glass-border); text-align: left; }
.cap-icon { font-size: 22px; color: #fff; margin-bottom: 10px; }
.cap-title { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.cap-sub { font-size: 11px; color: var(--text-tertiary); margin-top: 4px; }
.hero-tags { display: flex; gap: 8px; flex-wrap: wrap; justify-content: center; }
.tag-pill { padding: 8px 16px; border-radius: var(--r-pill); border: 1px solid var(--glass-border);
  background: rgba(255,255,255,0.08); color: var(--text-secondary); font-size: 12px; cursor: pointer; }
.tag-pill:hover { background: rgba(255,255,255,0.18); color: #fff; }
.model-chip { margin-top: 18px; font-size: 11px; color: var(--text-tertiary); display: flex; align-items: center; gap: 6px; }
.dot-model { width: 6px; height: 6px; border-radius: 50%; background: #34d399; }

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
.hop-node.small { font-size: 10px; padding: 3px 8px; }
.hop-node.terminal { background: rgba(251,191,36,0.18); color: #fde68a; }
.hop-arrow { color: var(--text-tertiary); font-size: 12px; }
.card-inset { margin-top: 10px; padding: 14px; border-radius: var(--r-md); background: rgba(0,0,0,0.22); border: 1px solid rgba(255,255,255,0.08); }
.card-inset.ok { background: rgba(52,211,153,0.08); border-color: rgba(52,211,153,0.25); }
.inset-title { font-size: 12px; font-weight: 600; margin-bottom: 10px; color: var(--text-primary); }
.plan-row { display: flex; gap: 10px; padding: 5px 0; font-size: 11px; align-items: center; }
.plan-num { color: var(--text-tertiary); }
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
.pill-btn:disabled { opacity: 0.5; cursor: not-allowed; }

/* 面板通用 */
.panel-head { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 22px; }
.panel-head h2 { font-size: 20px; margin: 0 0 6px; color: var(--text-primary); }
.panel-head p { font-size: 11px; color: var(--text-tertiary); margin: 0; }
.empty-panel { padding: 50px; text-align: center; color: var(--text-tertiary); font-size: 12px; }
.sub-title { font-size: 12px; font-weight: 600; color: var(--text-secondary); margin: 20px 0 10px; }

/* 任务面板 */
.task-list { display: flex; flex-direction: column; gap: 6px; }
.task-row { display: flex; align-items: center; gap: 12px; padding: 12px 14px; border-radius: var(--r-md);
  background: rgba(255,255,255,0.06); border: 1px solid var(--glass-border); cursor: pointer; }
.task-row:hover { background: rgba(255,255,255,0.12); }
.task-icon { width: 34px; height: 34px; border-radius: 9px; background: rgba(59,130,246,0.18); color: #93c5fd;
  display: flex; align-items: center; justify-content: center; }
.task-main { flex: 1; min-width: 0; }
.task-title { font-size: 12px; color: var(--text-primary); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.task-sub { font-size: 10px; color: var(--text-tertiary); margin-top: 4px; }
.task-del { background: none; border: none; color: var(--text-tertiary); cursor: pointer; font-size: 16px; }

/* Agent 面板 */
.agent-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }
.agent-card { padding: 16px; }
.agent-card-head { display: flex; gap: 10px; align-items: center; margin-bottom: 12px; }
.agent-card-name { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.agent-card-role { font-size: 10px; color: var(--text-tertiary); margin-top: 3px; }
.handoff-list { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }
.handoff-label { font-size: 10px; color: var(--text-tertiary); }

/* 工具面板 */
.tool-filter { display: flex; gap: 6px; margin-bottom: 14px; }
.tool-filter button { padding: 6px 14px; border-radius: var(--r-pill); font-size: 10px; cursor: pointer;
  background: rgba(255,255,255,0.08); border: 1px solid var(--glass-border); color: var(--text-secondary); }
.tool-filter button.on { background: rgba(59,130,246,0.3); color: #fff; }
.tool-group { margin-bottom: 18px; }
.tool-group-title { font-size: 11px; color: #93c5fd; font-weight: 600; margin-bottom: 8px; }
.tool-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.tool-card { padding: 12px; cursor: pointer; }
.tool-card:hover { background: rgba(59,130,246,0.15); }
.tool-name { font-size: 12px; font-weight: 600; color: var(--text-primary); }
.tool-desc { font-size: 10px; color: var(--text-secondary); margin-top: 4px; }
.tool-params { font-size: 9px; color: var(--text-tertiary); margin-top: 6px; }
.tool-detail { margin-top: 14px; padding: 14px; }
.detail-head { display: flex; justify-content: space-between; font-size: 12px; font-weight: 600; margin-bottom: 10px; }
.detail-head button { background: none; border: none; color: var(--text-tertiary); cursor: pointer; }
.detail-row { display: flex; gap: 14px; font-size: 11px; padding: 4px 0; }
.detail-row span { color: var(--text-tertiary); width: 50px; }
.detail-row b { color: var(--text-secondary); font-weight: 400; }

/* 知识库 */
.kb-search-box { display: flex; gap: 8px; margin-bottom: 14px; }
.kb-search-box input { flex: 1; padding: 10px 14px; border-radius: var(--r-sm); background: rgba(255,255,255,0.08);
  border: 1px solid var(--glass-border); color: #fff; font-size: 12px; outline: none; }
.kb-results { display: flex; flex-direction: column; gap: 8px; margin-bottom: 18px; }
.kb-result { padding: 12px; }
.kb-result-head { display: flex; justify-content: space-between; font-size: 10px; margin-bottom: 6px; }
.kb-source { color: #93c5fd; }
.kb-score { color: var(--text-tertiary); }
.kb-text { font-size: 11px; color: var(--text-secondary); line-height: 1.6; }
.kb-sources { margin-bottom: 18px; }
.source-row { display: flex; justify-content: space-between; padding: 7px 10px; font-size: 11px; color: var(--text-secondary);
  background: rgba(255,255,255,0.05); border-radius: 6px; margin-bottom: 4px; }
.kb-upload { padding: 14px; border-radius: var(--r-md); background: rgba(255,255,255,0.05); }
.kb-upload input { font-size: 11px; color: var(--text-secondary); margin-right: 8px; }
.upload-msg { font-size: 11px; color: #6ee7b7; margin-left: 8px; }

/* 设置 */
.settings-section { margin-bottom: 24px; }
.provider-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.provider-card { padding: 14px; cursor: pointer; }
.provider-card.active { border-color: rgba(59,130,246,0.6); background: rgba(59,130,246,0.15); }
.provider-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.provider-name { font-size: 12px; font-weight: 700; color: var(--text-primary); }
.provider-mode { font-size: 9px; padding: 2px 7px; border-radius: var(--r-pill); background: rgba(255,255,255,0.12); color: var(--text-secondary); }
.provider-model { font-size: 11px; color: #93c5fd; margin-bottom: 6px; }
.provider-status { font-size: 10px; color: #fbbf24; }
.provider-status.ok { color: #34d399; }
.setting-note { font-size: 10px; color: var(--text-tertiary); margin-top: 10px; line-height: 1.6; }
.identity-card { display: flex; align-items: center; gap: 12px; padding: 14px; }
.id-avatar { width: 40px; height: 40px; border-radius: 50%; background: linear-gradient(135deg,#3b82f6,#1d4ed8);
  display: flex; align-items: center; justify-content: center; font-size: 11px; font-weight: 700; color: #fff; }
.id-main { font-size: 13px; font-weight: 600; color: var(--text-primary); }
.id-sub { font-size: 10px; color: var(--text-tertiary); margin-top: 3px; }
.id-device { margin-left: auto; font-size: 10px; color: var(--text-tertiary); }
.status-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
.status-card { padding: 14px; display: flex; flex-direction: column; gap: 6px; }
.status-card span { font-size: 10px; color: var(--text-tertiary); }
.status-card b { font-size: 16px; color: var(--text-primary); }
.status-card b.ok { color: #34d399; }

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

/* 右侧 */
.messages { position: absolute; right: 22px; top: 22px; bottom: 22px; width: 290px; border-radius: var(--r-xl);
  z-index: 5; display: flex; flex-direction: column; overflow: hidden; }
.msg-head { display: flex; align-items: center; justify-content: space-between; padding: 20px 18px 12px; font-size: 16px; font-weight: 600; color: #fff; }
.msg-more { background: none; border: none; color: var(--text-tertiary); cursor: pointer; font-size: 16px; }
.msg-search { margin: 0 14px 12px; padding: 8px 12px; border-radius: var(--r-sm); background: rgba(255,255,255,0.08); display: flex; align-items: center; gap: 6px; }
.msg-search span { color: var(--text-tertiary); }
.msg-search input { flex: 1; background: transparent; border: none; outline: none; color: #fff; font-size: 11px; }
.msg-search input::placeholder { color: var(--text-tertiary); }
.msg-list { flex: 1; overflow-y: auto; padding: 0 10px; }
.msg-empty { font-size: 11px; color: var(--text-tertiary); text-align: center; padding: 30px 0; }
.msg-item { display: flex; gap: 9px; padding: 9px; border-radius: var(--r-sm); cursor: pointer; margin-bottom: 3px; }
.msg-item:hover, .msg-item.sel { background: rgba(255,255,255,0.1); }
.msg-avatar { width: 34px; height: 34px; border-radius: 50%; flex-shrink: 0; display: flex; align-items: center; justify-content: center;
  background: linear-gradient(135deg,#3b82f6,#1d4ed8); color: #fff; font-size: 14px; }
.msg-content { min-width: 0; flex: 1; }
.msg-line1 { display: flex; justify-content: space-between; font-size: 11px; }
.msg-line1 b { color: #fff; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.msg-line1 span { color: var(--text-tertiary); font-size: 10px; flex-shrink: 0; }
.msg-line2 { font-size: 10px; color: var(--text-tertiary); margin-top: 4px; }
.msg-foot { padding: 12px 16px; border-top: 1px solid rgba(255,255,255,0.08); font-size: 10px; color: var(--text-tertiary); display: flex; align-items: center; gap: 6px; }
.foot-dot { width: 6px; height: 6px; border-radius: 50%; background: #34d399; }

.err-banner { position: absolute; left: 50%; bottom: 14px; transform: translateX(-50%); z-index: 20;
  padding: 8px 16px; border-radius: var(--r-pill); font-size: 11px; color: #fff; display: flex; align-items: center; gap: 8px; }
.err-banner button { background: rgba(255,255,255,0.14); border: none; color: #fff; border-radius: var(--r-pill); padding: 3px 10px; cursor: pointer; }
</style>
