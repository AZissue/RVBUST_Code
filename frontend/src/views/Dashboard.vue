<template>
  <div class="dashboard">
    <!-- 顶部导航栏 -->
    <div class="top-nav-bar">
      <div class="nav-menu">
        <router-link to="/" :class="['nav-item', { active: $route.path === '/' }]">
          <el-icon><HomeFilled /></el-icon>工作台
        </router-link>
        <router-link to="/customers" :class="['nav-item', { active: $route.path.startsWith('/customers') }]">
          <el-icon><UserFilled /></el-icon>客户
        </router-link>
        <router-link to="/tickets" :class="['nav-item', { active: $route.path.startsWith('/tickets') }]">
          <el-icon><Tickets /></el-icon>工单
        </router-link>
      </div>
      <div class="nav-right">
        <el-dropdown trigger="click">
          <el-button circle class="nav-icon-btn" :icon="Download" />
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item @click="handleExportJson">
                <el-icon><Document /></el-icon>导出完整备份 (JSON)
              </el-dropdown-item>
              <el-dropdown-item @click="handleExportCsv">
                <el-icon><Grid /></el-icon>导出工单表格 (CSV)
              </el-dropdown-item>
              <el-dropdown-item @click="handleExportCustomersCsv">
                <el-icon><UserFilled /></el-icon>导出客户列表 (CSV)
              </el-dropdown-item>
              <el-dropdown-item divided @click="handleImportClick">
                <el-icon><Upload /></el-icon>导入备份 (JSON)
              </el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
        <el-badge :value="reminderCount" :hidden="reminderCount === 0" class="reminder-badge">
          <el-button circle class="nav-icon-btn" :icon="Bell" @click="showReminders = true" />
        </el-badge>
      </div>
    </div>

    <div class="content">
      <!-- 统计卡片 -->
      <el-row :gutter="16" class="stats-row">
        <el-col :xs="12" :sm="6" :md="6">
          <div class="stat-card stat-pending" @click="$router.push('/tickets?status=pending')">
            <div class="stat-icon-wrap">
              <el-icon><WarningFilled /></el-icon>
            </div>
            <div class="stat-value" :class="{ 'is-zero': stats.pending_count === 0 }">{{ stats.pending_count }}</div>
            <div class="stat-label">待处理</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="6">
          <div class="stat-card stat-processing" @click="$router.push('/tickets?status=processing')">
            <div class="stat-icon-wrap">
              <el-icon><Loading /></el-icon>
            </div>
            <div class="stat-value" :class="{ 'is-zero': stats.processing_count === 0 }">{{ stats.processing_count }}</div>
            <div class="stat-label">处理中</div>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="6">
          <div class="stat-card stat-waiting" :class="{ 'has-data': stats.waiting_feedback_count > 0 }" @click="$router.push('/tickets?status=waiting_feedback')">
            <div class="stat-icon-wrap">
              <el-icon><Timer /></el-icon>
            </div>
            <div class="stat-value" :class="{ 'is-zero': stats.waiting_feedback_count === 0 }">{{ stats.waiting_feedback_count }}</div>
            <div class="stat-label">等反馈</div>
            <el-button v-if="stats.waiting_feedback_count > 0" size="small" class="urge-btn" @click.stop="showUrgeDialog = true">
              催办
            </el-button>
          </div>
        </el-col>
        <el-col :xs="12" :sm="6" :md="6">
          <div class="stat-card stat-resolved">
            <div class="stat-icon-wrap">
              <el-icon><CircleCheckFilled /></el-icon>
            </div>
            <div class="stat-value" :class="{ 'is-zero': stats.resolved_today_count === 0 }">{{ stats.resolved_today_count }}</div>
            <div class="stat-label">今日已解决</div>
          </div>
        </el-col>
      </el-row>

      <!-- 主内容区 -->
      <el-row :gutter="16" class="main-row">
        <!-- 快速记录 -->
        <el-col :xs="24" :md="12">
          <el-card class="record-card" shadow="never">
            <template #header>
              <div class="section-title">
                <el-icon><Lightning /></el-icon>
                <span>快速记录</span>
              </div>
            </template>

            <!-- 智能解析（可折叠） -->
            <div class="ai-section" v-if="!aiExpanded">
              <div class="ai-collapsed-bar" @click="aiExpanded = true">
                <el-icon><MagicStick /></el-icon>
                <span>✨ 粘贴描述自动解析</span>
                <el-icon class="expand-icon"><ArrowDown /></el-icon>
              </div>
            </div>
            <div class="ai-section" v-else>
              <el-input
                v-model="aiInput"
                type="textarea"
                :rows="3"
                placeholder="粘贴一段客户描述，自动提取客户/问题/负责人..."
              />
              <div class="ai-actions">
                <el-button size="small" @click="aiExpanded = false">取消</el-button>
                <el-button type="warning" size="small" @click="parseAiInput" :loading="aiParsing">
                  <el-icon><MagicStick /></el-icon> 智能解析
                </el-button>
              </div>
            </div>

            <el-divider v-if="aiExpanded" content-position="left">或手动填写</el-divider>

            <el-form :model="form" label-position="top" ref="formRef" class="record-form">
              <el-form-item label="客户" required>
                <div class="customer-input-wrap">
                  <el-autocomplete
                    v-model="form.customer_name"
                    :fetch-suggestions="searchCustomer"
                    :placeholder="'🔍 输入客户名称搜索...'"
                    :trigger-on-focus="false"
                    clearable
                    style="width: 100%"
                    @select="onCustomerSelect"
                    @keyup.enter="handleCustomerEnter"
                  >
                    <template #default="{ item }">
                      <div class="suggest-item">
                        <div class="suggest-main">
                          <span class="suggest-name">{{ item.name }}</span>
                          <span class="suggest-meta">{{ item.region }}｜{{ item.contact_person }}</span>
                        </div>
                      </div>
                    </template>
                  </el-autocomplete>
                  <el-tag v-if="selectedCustomer" type="success" size="small" class="customer-tag" closable @close="clearCustomer">
                    {{ selectedCustomer.name }} ✓
                  </el-tag>
                </div>
              </el-form-item>

              <el-form-item label="类型">
                <el-select v-model="form.category" placeholder="选择问题类型" style="width: 100%" @change="onCategoryChange">
                  <el-option label="硬件故障" value="硬件故障" />
                  <el-option label="软件使用" value="软件使用" />
                  <el-option label="咨询" value="咨询" />
                  <el-option label="投诉" value="投诉" />
                  <el-option label="其他" value="其他" />
                </el-select>
              </el-form-item>

              <el-form-item label="标题">
                <el-input v-model="form.title" :placeholder="titlePlaceholder" />
              </el-form-item>

              <el-form-item label="描述">
                <el-input
                  v-model="form.description"
                  type="textarea"
                  :rows="3"
                  placeholder="详细描述问题现象、已尝试的解决方案..."
                />
              </el-form-item>

              <el-row :gutter="12">
                <el-col :span="12">
                  <el-form-item label="负责人">
                    <el-select v-model="form.assignee" placeholder="选择" style="width: 100%">
                      <el-option v-for="name in assignees" :key="name" :label="name" :value="name" />
                    </el-select>
                  </el-form-item>
                </el-col>
                <el-col :span="12">
                  <el-form-item label="优先级">
                    <el-select v-model="form.priority" style="width: 100%">
                      <el-option label="紧急" value="urgent" />
                      <el-option label="高" value="high" />
                      <el-option label="普通" value="normal" />
                      <el-option label="低" value="low" />
                    </el-select>
                  </el-form-item>
                </el-col>
              </el-row>

              <el-form-item class="form-actions">
                <el-button type="primary" @click="submitForm" :loading="submitting">
                  保存并继续
                </el-button>
                <el-button @click="submitAndClose">保存并关闭</el-button>
              </el-form-item>
            </el-form>
          </el-card>
        </el-col>

        <!-- 我的待办 -->
        <el-col :xs="24" :md="12">
          <el-card class="todo-card" shadow="never">
            <template #header>
              <div class="section-title">
                <el-icon><List /></el-icon>
                <span>我的待办</span>
                <el-select v-model="currentAssignee" placeholder="全部负责人" size="small" clearable @change="loadTodos" class="assignee-filter">
                  <el-option v-for="name in assignees" :key="name" :label="name" :value="name" />
                </el-select>
                <el-button size="small" circle @click="loadTodos">
                  <el-icon><Refresh /></el-icon>
                </el-button>
              </div>
            </template>

            <!-- 空状态 -->
            <div v-if="todoList.length === 0 && !loading" class="empty-state">
              <div class="empty-icon">🎉</div>
              <div class="empty-text">今日待办已清空</div>
              <div class="empty-sub">喝杯咖啡吧</div>
              <el-button type="primary" size="small" @click="focusCustomerInput">记一条工单</el-button>
            </div>

            <!-- 待办卡片列表 -->
            <div v-else class="todo-list" v-loading="loading">
              <div
                v-for="item in todoList"
                :key="item.id"
                class="todo-item"
                :class="{ 'is-urgent': item.priority === 'urgent', 'is-high': item.priority === 'high', 'is-overdue': item.is_overday }"
              >
                <div class="todo-priority-bar" :class="item.priority"></div>
                <div class="todo-content">
                  <div class="todo-main">
                    <div class="todo-title-row">
                      <span class="todo-title">{{ item.title }}</span>
                      <span v-if="item.is_overday" class="overday-tag">🔥</span>
                    </div>
                    <div class="todo-meta">
                      <span class="todo-customer">{{ item.customer_name }}</span>
                      <span class="divider">｜</span>
                      <span class="todo-assignee">{{ item.assignee || '未分配' }}</span>
                      <span class="divider">｜</span>
                      <span class="todo-time">{{ formatTime(item.created_at) }}</span>
                    </div>
                    <div v-if="item.status === 'waiting_feedback'" class="todo-waiting">
                      ⏳ 已等待 {{ getWaitingDays(item) }} 天
                    </div>
                  </div>
                  <el-button size="small" type="primary" plain @click="$router.push(`/tickets/${item.id}`)">
                    处理
                  </el-button>
                </div>
              </div>
            </div>

            <!-- 今日统计 -->
            <div class="daily-stats" v-if="todoList.length > 0">
              <div class="daily-title">今日统计</div>
              <div class="daily-grid">
                <div class="daily-item">
                  <div class="daily-num">{{ todayResolved }}</div>
                  <div class="daily-label">已处理</div>
                </div>
                <div class="daily-item">
                  <div class="daily-num">{{ todayPending }}</div>
                  <div class="daily-label">待处理</div>
                </div>
                <div class="daily-item">
                  <div class="daily-num">{{ avgHandleTime }}h</div>
                  <div class="daily-label">平均时长</div>
                </div>
              </div>
            </div>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 保存成功提示 -->
    <transition name="slide-fade">
      <div v-if="saveSuccess" class="success-toast">
        <div class="toast-content">
          <el-icon class="toast-icon"><CircleCheckFilled /></el-icon>
          <span>工单 #{{ savedTicketId }} 已创建</span>
        </div>
        <div class="toast-actions">
          <el-button link size="small" @click="$router.push(`/tickets/${savedTicketId}`)">查看</el-button>
          <el-button link size="small" @click="focusCustomerInput">再记一条</el-button>
        </div>
      </div>
    </transition>

    <!-- 催办弹窗 -->
    <el-dialog v-model="showUrgeDialog" title="催办" width="360px">
      <div class="urge-options">
        <el-radio-group v-model="urgeMethod">
          <el-radio label="notify">系统内通知</el-radio>
          <el-radio label="copy">复制催办文案</el-radio>
        </el-radio-group>
        <div v-if="urgeMethod === 'copy'" class="urge-text">
          您好，关于您反馈的XX问题，目前已等待{{ stats.waiting_feedback_count }}天未收到回复，请尽快提供相关信息以便我们继续处理。
        </div>
      </div>
      <template #footer>
        <el-button @click="showUrgeDialog = false">取消</el-button>
        <el-button type="primary" @click="handleUrge">确认催办</el-button>
      </template>
    </el-dialog>

    <!-- 消息中心抽屉 -->
    <el-drawer v-model="showReminders" title="消息中心" size="400px">
      <div class="reminder-list">
        <el-empty v-if="reminders.length === 0" description="暂无提醒消息" />
        <div v-for="item in reminders" :key="item.id" class="reminder-item" :class="item.level" @click="goToTicket(item.ticket_id)">
          <div class="reminder-header">
            <el-tag :type="item.level" size="small">{{ item.type === 'overdue' ? '超时' : '催办' }}</el-tag>
            <span class="reminder-time">{{ formatTime(item.created_at) }}</span>
          </div>
          <div class="reminder-message">{{ item.message }}</div>
        </div>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import {
  HomeFilled, UserFilled, Tickets, Download, Bell, Document, Grid, Upload,
  WarningFilled, Loading, Timer, CircleCheckFilled, MagicStick, Lightning,
  List, Refresh, ArrowDown
} from '@element-plus/icons-vue'
import {
  getDashboardStats, getTodoList, quickCreateTicket,
  searchCustomers, getReminders, getReminderStats,
  exportJson, exportCsv, exportCustomersCsv, importJson
} from '../api'

const router = useRouter()
const loading = ref(false)
const submitting = ref(false)
const stats = reactive({ pending_count: 0, processing_count: 0, waiting_feedback_count: 0, resolved_today_count: 0 })
const todoList = ref([])
const assignees = ['张三', '李四', '王五', '赵六', '钱七']
const currentAssignee = ref('')

// 智能解析
const aiExpanded = ref(false)
const aiInput = ref('')
const aiParsing = ref(false)

// 表单
const formRef = ref(null)
const form = reactive({
  customer_name: '',
  title: '',
  category: '',
  description: '',
  assignee: '',
  priority: 'normal'
})
const selectedCustomer = ref(null)
const titlePlaceholder = ref('一句话概括问题...')

// 保存提示
const saveSuccess = ref(false)
const savedTicketId = ref(null)

// 催办
const showUrgeDialog = ref(false)
const urgeMethod = ref('notify')

// 消息中心
const showReminders = ref(false)
const reminders = ref([])
const reminderCount = ref(0)

// 今日统计
const todayResolved = ref(0)
const todayPending = ref(0)
const avgHandleTime = ref(0)

// 监听类型变化，动态修改标题placeholder
const onCategoryChange = (cat) => {
  const placeholders = {
    '硬件故障': '例如：相机无法开机/连接超时...',
    '软件使用': '例如：SDK调用返回错误码...',
    '咨询': '例如：咨询保修政策/升级方案...',
    '投诉': '例如：对售后服务不满意...',
    '其他': '一句话概括问题...'
  }
  titlePlaceholder.value = placeholders[cat] || '一句话概括问题...'
}

// 加载统计
const loadStats = async () => {
  try {
    const data = await getDashboardStats()
    Object.assign(stats, data)
    todayResolved.value = data.resolved_today_count || 0
    todayPending.value = data.pending_count || 0
  } catch (e) { console.error(e) }
}

// 加载待办
const loadTodos = async () => {
  loading.value = true
  try {
    const res = await getTodoList(currentAssignee.value || undefined)
    todoList.value = res || []
    // 标记超24小时的
    todoList.value.forEach(item => {
      const created = new Date(item.created_at)
      const now = new Date()
      item.is_overday = (now - created) > 24 * 3600 * 1000
    })
  } catch (e) {
    console.error(e)
  } finally {
    loading.value = false
  }
}

// 客户搜索
const searchCustomer = async (query, cb) => {
  if (!query || query.length < 1) { cb([]); return }
  try {
    const results = await searchCustomers(query)
    cb(results.map(r => ({ value: r.name, ...r })))
  } catch (e) { cb([]) }
}

const onCustomerSelect = (item) => {
  form.customer_name = item.name
  selectedCustomer.value = item
}

const clearCustomer = () => {
  selectedCustomer.value = null
  form.customer_name = ''
}

const handleCustomerEnter = () => {
  if (!selectedCustomer.value && form.customer_name) {
    ElMessage.info('新客户，保存时将自动创建')
  }
}

// 智能解析
const parseAiInput = () => {
  const text = aiInput.value.trim()
  if (!text) { ElMessage.warning('请输入描述'); return }
  aiParsing.value = true
  setTimeout(() => {
    const result = _parseTicketText(text)
    if (result.customer_name) { form.customer_name = result.customer_name; selectedCustomer.value = { name: result.customer_name } }
    if (result.category) form.category = result.category
    if (result.title) form.title = result.title
    if (result.assignee) form.assignee = result.assignee
    if (result.priority) form.priority = result.priority
    form.description = result.description
    aiParsing.value = false
    aiExpanded.value = false
    ElMessage.success('解析完成，已自动填充')
    onCategoryChange(form.category)
  }, 500)
}

const _parseTicketText = (text) => {
  const result = { customer_name: '', category: '', title: '', description: text, assignee: '', priority: 'normal' }
  const companyMatch = text.match(/([\u4e00-\u9fa5]{2,}(?:公司|科技|工作室|研究院))/)
  if (companyMatch) result.customer_name = companyMatch[1]
  
  const catMap = { '硬件故障': ['硬件','指示灯','电源','USB','不亮','连不上'], '软件使用': ['软件','SDK','API','升级','报错'], '咨询': ['咨询','了解','想知道','怎么'], '投诉': ['投诉','不满','退货'] }
  for (const [cat, keys] of Object.entries(catMap)) {
    if (keys.some(k => text.includes(k))) { result.category = cat; break }
  }
  
  const priMap = { 'urgent': ['紧急','急用','马上','立刻'], 'high': ['尽快','严重','重要'] }
  for (const [pri, keys] of Object.entries(priMap)) {
    if (keys.some(k => text.includes(k))) { result.priority = pri; break }
  }
  
  assignees.forEach(name => { if (text.includes(name)) result.assignee = name })
  
  const titleMatch = text.match(/(?:反馈|反映|说|报)\s*(.+?)(?:，|,|。|；|;|麻烦|请|$)/)
  if (titleMatch) result.title = titleMatch[1].trim().slice(0, 40)
  else result.title = text.slice(0, 40)
  
  return result
}

// 提交表单
const submitForm = async () => {
  if (!form.customer_name || !form.title || !form.category) {
    ElMessage.warning('请填写客户、类型和标题')
    return
  }
  submitting.value = true
  try {
    const res = await quickCreateTicket({ ...form })
    savedTicketId.value = res.ticket_id
    showSaveSuccess()
    resetForm()
    loadStats()
    loadTodos()
  } catch (e) { console.error(e) }
  finally { submitting.value = false }
}

const submitAndClose = async () => {
  await submitForm()
  if (saveSuccess.value) {
    setTimeout(() => router.push('/tickets'), 500)
  }
}

const showSaveSuccess = () => {
  saveSuccess.value = true
  setTimeout(() => { saveSuccess.value = false }, 4000)
}

const resetForm = () => {
  form.customer_name = ''; form.title = ''; form.category = ''; form.description = ''
  form.assignee = currentAssignee.value; form.priority = 'normal'
  selectedCustomer.value = null; aiInput.value = ''
}

const focusCustomerInput = () => {
  const input = document.querySelector('.record-form input')
  if (input) input.focus()
}

// 催办
const handleUrge = () => {
  if (urgeMethod.value === 'copy') {
    const text = `您好，关于您反馈的问题，目前已等待${stats.waiting_feedback_count}天未收到回复，请尽快提供相关信息以便我们继续处理。`
    navigator.clipboard?.writeText(text)
    ElMessage.success('催办文案已复制')
  } else {
    ElMessage.success('系统通知已发送')
  }
  showUrgeDialog.value = false
}

// 消息中心
const loadReminders = async () => {
  try {
    const data = await getReminders({ assignee: currentAssignee.value || undefined })
    reminders.value = data.items || []
    reminderCount.value = data.unread_count || 0
  } catch (e) {}
}

const loadReminderStats = async () => {
  try {
    const data = await getReminderStats(currentAssignee.value || undefined)
    reminderCount.value = data.count || 0
  } catch (e) {}
}

const goToTicket = (id) => {
  showReminders.value = false
  router.push(`/tickets/${id}`)
}

// 等待天数
const getWaitingDays = (item) => {
  const created = new Date(item.created_at)
  return Math.floor((new Date() - created) / (24 * 3600 * 1000))
}

// 导出导入
const handleExportJson = async () => {
  try { downloadBlob(await exportJson(), `backup_${nowStr()}.json`); ElMessage.success('导出成功') } catch { ElMessage.error('导出失败') }
}
const handleExportCsv = async () => {
  try { downloadBlob(await exportCsv(), `tickets_${nowStr()}.csv`); ElMessage.success('导出成功') } catch { ElMessage.error('导出失败') }
}
const handleExportCustomersCsv = async () => {
  try { downloadBlob(await exportCustomersCsv(), `customers_${nowStr()}.csv`); ElMessage.success('导出成功') } catch { ElMessage.error('导出失败') }
}
const downloadBlob = (blob, filename) => {
  const url = URL.createObjectURL(blob); const a = document.createElement('a')
  a.href = url; a.download = filename; document.body.appendChild(a); a.click(); document.body.removeChild(a); URL.revokeObjectURL(url)
}
const nowStr = () => new Date().toISOString().slice(0,19).replace(/:/g,'')

const handleImportClick = () => { /* TODO */ }

// 格式化
const formatTime = (time) => {
  if (!time) return '-'
  const timeStr = time.toString()
  const utcTime = timeStr.endsWith('Z') ? timeStr : timeStr + '+00:00'
  const date = new Date(utcTime)
  const now = new Date()
  const diff = Math.floor((now - date) / 1000)
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  if (diff < 172800) return '昨天'
  return date.toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

// 优先级样式
const priorityType = (p) => ({ urgent: 'danger', high: 'warning', normal: 'info', low: 'success' }[p] || 'info')
const priorityText = (p) => ({ urgent: '紧急', high: '高', normal: '普通', low: '低' }[p] || p)
const statusType = (s) => ({ pending: 'danger', processing: 'warning', waiting_feedback: 'info', resolved: 'success', closed: '' }[s] || '')
const statusText = (s) => ({ pending: '待处理', processing: '处理中', waiting_feedback: '等反馈', resolved: '已解决', closed: '已关闭' }[s] || s)

onMounted(() => {
  loadStats(); loadTodos(); loadReminders(); loadReminderStats()
  setInterval(loadReminderStats, 30000)
})
</script>

<style scoped>
/* ===== 全局 ===== */
.dashboard {
  min-height: 100vh;
  background: linear-gradient(135deg, #f5f7fa 0%, #eef1f6 100%);
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

/* ===== 导航栏 ===== */
.top-nav-bar {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 20px;
  height: 52px;
  background: linear-gradient(90deg, #1a2a6c 0%, #2d4a8a 50%, #3a5ab0 100%);
  box-shadow: 0 2px 8px rgba(26, 42, 108, 0.2);
}

.nav-menu {
  display: flex;
  gap: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 7px 14px;
  border-radius: 6px;
  color: rgba(255,255,255,0.75);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s;
}

.nav-item:hover { color: #fff; background: rgba(255,255,255,0.1); }
.nav-item.active { color: #fff; background: rgba(255,255,255,0.2); }

.nav-right { display: flex; align-items: center; gap: 8px; }

.nav-icon-btn {
  background: rgba(255,255,255,0.12) !important;
  border: none !important;
  color: #fff !important;
}
.nav-icon-btn:hover { background: rgba(255,255,255,0.25) !important; }

/* ===== 内容区 ===== */
.content {
  padding: 16px 20px 30px;
  max-width: 1440px;
  margin: 0 auto;
}

/* ===== 统计卡片 ===== */
.stats-row { margin-bottom: 16px; }

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 8px;
  border-radius: 12px;
  cursor: pointer;
  transition: all 0.3s;
  background: #fff;
  box-shadow: 0 2px 8px rgba(0,0,0,0.06);
  border: 1px solid transparent;
  position: relative;
}

.stat-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(0,0,0,0.1);
}

.stat-icon-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 40px;
  height: 40px;
  border-radius: 10px;
  font-size: 20px;
  margin-bottom: 8px;
}

.stat-value {
  font-size: 32px;
  font-weight: 700;
  line-height: 1;
  color: #1a1a2e;
}

.stat-value.is-zero { color: #bbb; }

.stat-label {
  font-size: 13px;
  color: #888;
  margin-top: 4px;
  font-weight: 500;
}

.stat-pending .stat-icon-wrap { background: #fff0f0; color: #ff6b6b; }
.stat-processing .stat-icon-wrap { background: #fff8e6; color: #ffa726; }
.stat-waiting .stat-icon-wrap { background: #e8f4fd; color: #42a5f5; }
.stat-resolved .stat-icon-wrap { background: #e8f8e8; color: #66bb6a; }

.stat-waiting.has-data {
  border-color: #42a5f5;
  box-shadow: 0 0 0 2px rgba(66, 165, 245, 0.15), 0 4px 12px rgba(66, 165, 245, 0.1);
}

.urge-btn {
  position: absolute;
  bottom: 8px;
  right: 8px;
  padding: 2px 10px;
  font-size: 12px;
}

/* ===== 主内容区 ===== */
.main-row { margin: 0 -8px; }
.main-row > .el-col { padding: 0 8px; }

.record-card, .todo-card {
  border-radius: 12px;
  height: 100%;
}

.record-card :deep(.el-card__header), .todo-card :deep(.el-card__header) {
  padding: 12px 16px;
  border-bottom: 1px solid #f0f0f0;
}

.record-card :deep(.el-card__body), .todo-card :deep(.el-card__body) {
  padding: 16px;
}

.section-title {
  display: flex;
  align-items: center;
  gap: 6px;
  font-weight: 600;
  font-size: 15px;
  color: #1a1a2e;
}

.section-title .el-icon { color: #3a5ab0; }

.assignee-filter { width: 120px; margin-left: auto; margin-right: 8px; }

/* ===== 智能解析 ===== */
.ai-section { margin-bottom: 12px; }

.ai-collapsed-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 14px;
  background: #fffbf0;
  border: 1px dashed #e6a23c;
  border-radius: 8px;
  cursor: pointer;
  color: #e6a23c;
  font-size: 13px;
  transition: all 0.2s;
}

.ai-collapsed-bar:hover {
  background: #fff5d6;
  border-style: solid;
}

.expand-icon { margin-left: auto; }

.ai-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
  margin-top: 8px;
}

/* ===== 表单 ===== */
.record-form .el-form-item { margin-bottom: 14px; }
.record-form .el-form-item__label {
  font-weight: 600;
  color: #555;
  font-size: 13px;
  padding-bottom: 2px;
}

.customer-input-wrap { position: relative; }

.customer-tag {
  position: absolute;
  right: 30px;
  top: 50%;
  transform: translateY(-50%);
}

.suggest-item { padding: 4px 0; }
.suggest-main {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.suggest-name { font-weight: 600; color: #1a1a2e; }
.suggest-meta { font-size: 12px; color: #999; margin-left: 8px; }

.form-actions {
  margin-top: 20px;
  margin-bottom: 0 !important;
  padding-top: 12px;
  border-top: 1px solid #f0f0f0;
}

/* ===== 待办列表 ===== */
.todo-list { display: flex; flex-direction: column; gap: 10px; }

.todo-item {
  display: flex;
  background: #fff;
  border-radius: 10px;
  overflow: hidden;
  box-shadow: 0 1px 4px rgba(0,0,0,0.04);
  transition: all 0.25s;
  border: 1px solid #f0f0f0;
}

.todo-item:hover {
  box-shadow: 0 4px 12px rgba(0,0,0,0.08);
  transform: translateX(2px);
}

.todo-priority-bar {
  width: 4px;
  flex-shrink: 0;
}

.todo-priority-bar.urgent { background: #ff6b6b; }
.todo-priority-bar.high { background: #ffa726; }
.todo-priority-bar.normal { background: #ccc; }
.todo-priority-bar.low { background: #66bb6a; }

.todo-content {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  flex: 1;
  gap: 10px;
}

.todo-main { flex: 1; min-width: 0; }

.todo-title-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 4px;
}

.todo-title {
  font-weight: 600;
  font-size: 14px;
  color: #1a1a2e;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.todo-meta {
  font-size: 12px;
  color: #888;
  display: flex;
  align-items: center;
  gap: 4px;
}

.todo-meta .divider { color: #ddd; }

.todo-customer { font-weight: 500; color: #666; }

.todo-waiting {
  font-size: 12px;
  color: #42a5f5;
  margin-top: 2px;
}

.overday-tag { font-size: 14px; }

/* 今日统计 */
.daily-stats {
  margin-top: 16px;
  padding: 14px;
  background: #f8f9fa;
  border-radius: 10px;
}

.daily-title {
  font-size: 12px;
  font-weight: 600;
  color: #888;
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.daily-grid {
  display: flex;
  gap: 16px;
}

.daily-item {
  text-align: center;
  flex: 1;
}

.daily-num {
  font-size: 22px;
  font-weight: 700;
  color: #1a1a2e;
}

.daily-label {
  font-size: 12px;
  color: #888;
  margin-top: 2px;
}

/* 空状态 */
.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 40px 20px;
  text-align: center;
}

.empty-icon { font-size: 48px; margin-bottom: 12px; }
.empty-text { font-size: 16px; font-weight: 600; color: #1a1a2e; margin-bottom: 4px; }
.empty-sub { font-size: 13px; color: #888; margin-bottom: 16px; }

/* 保存成功提示 */
.success-toast {
  position: fixed;
  bottom: 24px;
  right: 24px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.15);
  padding: 14px 18px;
  z-index: 2000;
  min-width: 240px;
}

.toast-content {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
  color: #1a1a2e;
  margin-bottom: 8px;
}

.toast-icon { color: #66bb6a; font-size: 18px; }

.toast-actions {
  display: flex;
  justify-content: flex-end;
  gap: 8px;
}

.slide-fade-enter-active { transition: all 0.3s ease; }
.slide-fade-leave-active { transition: all 0.3s ease; }
.slide-fade-enter-from, .slide-fade-leave-to { transform: translateX(20px); opacity: 0; }

/* 催办弹窗 */
.urge-options { padding: 10px 0; }
.urge-text {
  margin-top: 12px;
  padding: 12px;
  background: #f8f9fa;
  border-radius: 8px;
  font-size: 13px;
  color: #666;
  line-height: 1.6;
}

/* 消息中心 */
.reminder-list { padding: 4px; }
.reminder-item {
  padding: 12px 14px;
  margin-bottom: 8px;
  border-radius: 8px;
  cursor: pointer;
  transition: all 0.2s;
  background: #f8f9fa;
  border-left: 3px solid #ccc;
}
.reminder-item:hover { background: #f0f4f8; }
.reminder-item.danger { border-left-color: #ff6b6b; background: #fff5f5; }
.reminder-item.warning { border-left-color: #ffa726; background: #fffbf0; }
.reminder-header { display: flex; justify-content: space-between; margin-bottom: 4px; }
.reminder-time { font-size: 12px; color: #999; }
.reminder-message { font-size: 13px; color: #444; line-height: 1.5; }

/* 响应式 */
@media (max-width: 768px) {
  .content { padding: 12px; }
  .stats-row { margin-bottom: 12px; }
  .stat-card { padding: 12px 4px; }
  .stat-value { font-size: 24px; }
  .main-row > .el-col { padding: 0; margin-bottom: 12px; }
  .assignee-filter { width: 100px; }
}
</style>