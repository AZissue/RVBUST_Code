<template>
  <div class="tickets-page">
    <!-- 顶部导航栏 -->
    <div class="top-nav">
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
    </div>

    <div class="content">
      <el-card>
        <template #header>
          <div class="card-header">
            <div class="header-left">
              <el-radio-group v-model="viewMode" size="small">
                <el-radio-button label="list">列表视图</el-radio-button>
                <el-radio-button label="kanban">看板视图</el-radio-button>
              </el-radio-group>
            </div>
            <el-button type="primary" @click="showCreateDialog">
              <el-icon><Plus /></el-icon>新建工单
            </el-button>
          </div>
        </template>

        <!-- 筛选栏 -->
        <el-row :gutter="10" class="filter-bar">
          <el-col :span="4">
            <el-select v-model="filters.status" placeholder="状态" clearable @change="loadTickets">
              <el-option label="待处理" value="pending" />
              <el-option label="处理中" value="processing" />
              <el-option label="等待反馈" value="waiting_feedback" />
              <el-option label="已解决" value="resolved" />
              <el-option label="已关闭" value="closed" />
            </el-select>
          </el-col>
          <el-col :span="4">
            <el-select v-model="filters.priority" placeholder="优先级" clearable @change="loadTickets">
              <el-option label="紧急" value="urgent" />
              <el-option label="高" value="high" />
              <el-option label="普通" value="normal" />
              <el-option label="低" value="low" />
            </el-select>
          </el-col>
          <el-col :span="4">
            <el-select v-model="filters.assignee" placeholder="负责人" clearable @change="loadTickets">
              <el-option v-for="name in assignees" :key="name" :label="name" :value="name" />
            </el-select>
          </el-col>
          <el-col :span="6">
            <el-input v-model="filters.q" placeholder="搜索工单标题/客户" clearable @clear="loadTickets" @keyup.enter="loadTickets">
              <template #prefix><el-icon><Search /></el-icon></template>
            </el-input>
          </el-col>
          <el-col :span="2">
            <el-button type="primary" @click="loadTickets">搜索</el-button>
          </el-col>
        </el-row>

        <!-- 列表视图 -->
        <div v-if="viewMode === 'list'">
          <el-table :data="tickets" style="width: 100%" v-loading="loading">
            <el-table-column prop="id" label="编号" width="70" />
            <el-table-column prop="title" label="标题" min-width="180">
              <template #default="{ row }">
                <router-link :to="`/tickets/${row.id}`" class="ticket-link">{{ row.title }}</router-link>
              </template>
            </el-table-column>
            <el-table-column prop="customer_name" label="客户" width="120" />
            <el-table-column prop="category" label="类型" width="100" />
            <el-table-column prop="status" label="状态" width="100">
              <template #default="{ row }">
                <el-tag :type="statusType(row.status)" size="small">{{ statusText(row.status) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="priority" label="优先级" width="80">
              <template #default="{ row }">
                <el-tag :type="priorityType(row.priority)" size="small" effect="dark">{{ priorityText(row.priority) }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="assignee" label="负责人" width="90" />
            <el-table-column prop="created_at" label="创建时间" width="150">
              <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="120" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" @click="viewTicket(row)">查看</el-button>
              </template>
            </el-table-column>
          </el-table>

          <el-pagination
            class="pagination"
            v-model:current-page="page"
            v-model:page-size="pageSize"
            :total="total"
            :page-sizes="[10, 20, 50]"
            layout="total, sizes, prev, pager, next"
            @change="loadTickets"
          />
        </div>

        <!-- 看板视图 -->
        <div v-else class="kanban-board">
          <div class="kanban-column" v-for="col in kanbanColumns" :key="col.status">
            <div class="column-header" :class="col.status">
              <span>{{ col.title }}</span>
              <el-tag size="small" :type="col.tagType">{{ col.count }}</el-tag>
            </div>
            <div class="column-body">
              <el-card
                v-for="ticket in col.tickets"
                :key="ticket.id"
                class="kanban-card"
                shadow="hover"
                draggable="true"
                @dragstart="onDragStart(ticket)"
                @dragend="onDragEnd"
              >
                <div class="card-priority">
                  <el-tag :type="priorityType(ticket.priority)" size="small" effect="dark">{{ priorityText(ticket.priority) }}</el-tag>
                </div>
                <div class="card-title">{{ ticket.title }}</div>
                <div class="card-info">
                  <span>{{ ticket.customer_name }}</span>
                  <span>{{ ticket.assignee }}</span>
                </div>
              </el-card>
              <div
                class="drop-zone"
                :class="{ active: dragOverColumn === col.status }"
                @dragover.prevent="dragOverColumn = col.status"
                @dragleave="dragOverColumn = null"
                @drop="onDrop(col.status)"
              >
                拖拽到此处
              </div>
            </div>
          </div>
        </div>
      </el-card>
    </div>

    <!-- 新建工单弹窗 -->
    <el-dialog v-model="createVisible" title="新建工单" width="600px">
      <el-form :model="form" label-width="80px" :rules="rules" ref="formRef">
        <el-form-item label="客户" prop="customer_id">
          <el-autocomplete
            v-model="customerSearch"
            :fetch-suggestions="searchCustomer"
            placeholder="搜索客户"
            :trigger-on-focus="false"
            clearable
            style="width: 100%"
            @select="onCustomerSelect"
          />
        </el-form-item>
        <el-form-item label="标题" prop="title">
          <el-input v-model="form.title" placeholder="问题标题" />
        </el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.category" placeholder="选择问题类型" style="width: 100%">
            <el-option label="硬件故障" value="硬件故障" />
            <el-option label="软件使用" value="软件使用" />
            <el-option label="咨询" value="咨询" />
            <el-option label="投诉" value="投诉" />
            <el-option label="其他" value="其他" />
          </el-select>
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="form.description" type="textarea" :rows="3" placeholder="详细描述..." />
        </el-form-item>
        <el-row :gutter="10">
          <el-col :span="12">
            <el-form-item label="负责人">
              <el-select v-model="form.assignee" placeholder="负责人" style="width: 100%">
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
      </el-form>
      <template #footer>
        <el-button @click="createVisible = false">取消</el-button>
        <el-button type="primary" @click="submitCreate" :loading="submitting">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getTickets, createTicket, updateTicketStatus, searchCustomers } from '../api'

const router = useRouter()
const loading = ref(false)
const tickets = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const viewMode = ref('list')
const assignees = ['张三', '李四', '王五', '赵六', '钱七']

const filters = reactive({
  status: '',
  priority: '',
  assignee: '',
  q: ''
})

// 看板
const kanbanColumns = ref([
  { status: 'pending', title: '待处理', tagType: 'danger', count: 0, tickets: [] },
  { status: 'processing', title: '处理中', tagType: 'warning', count: 0, tickets: [] },
  { status: 'waiting_feedback', title: '等待反馈', tagType: 'info', count: 0, tickets: [] },
  { status: 'resolved', title: '已解决', tagType: 'success', count: 0, tickets: [] }
])

const dragTicket = ref(null)
const dragOverColumn = ref(null)

// 新建工单
const createVisible = ref(false)
const submitting = ref(false)
const customerSearch = ref('')
const formRef = ref(null)
const form = reactive({
  customer_id: null,
  title: '',
  category: '',
  description: '',
  assignee: '',
  priority: 'normal'
})

const rules = {
  customer_id: [{ required: true, message: '请选择客户', trigger: 'change' }],
  title: [{ required: true, message: '请输入标题', trigger: 'blur' }]
}

const loadTickets = async () => {
  loading.value = true
  try {
    const params = {
      page: page.value,
      page_size: pageSize.value,
      ...filters
    }
    const res = await getTickets(params)
    tickets.value = res.items
    total.value = res.total

    // 更新看板数据
    updateKanban(res.items)
  } catch (e) {
    console.error('加载工单失败', e)
  } finally {
    loading.value = false
  }
}

const updateKanban = (allTickets) => {
  // 如果是看板模式，需要加载所有状态的数据
  // 这里简化处理：仅基于当前筛选结果分组
  kanbanColumns.value.forEach(col => {
    col.tickets = allTickets.filter(t => t.status === col.status)
    col.count = col.tickets.length
  })
}

// 看板拖拽
const onDragStart = (ticket) => {
  dragTicket.value = ticket
}

const onDragEnd = () => {
  dragOverColumn.value = null
}

const onDrop = async (newStatus) => {
  if (!dragTicket.value || dragTicket.value.status === newStatus) return

  try {
    await updateTicketStatus(dragTicket.value.id, newStatus)
    ElMessage.success('状态更新成功')
    dragTicket.value.status = newStatus
    loadTickets()
  } catch (e) {
    ElMessage.error('状态更新失败')
  }
  dragTicket.value = null
  dragOverColumn.value = null
}

// 新建工单
const showCreateDialog = () => {
  createVisible.value = true
  resetForm()
}

const resetForm = () => {
  form.customer_id = null
  form.title = ''
  form.category = ''
  form.description = ''
  form.assignee = ''
  form.priority = 'normal'
  customerSearch.value = ''
}

const searchCustomer = async (query, cb) => {
  if (!query || query.length < 1) { cb([]); return }
  try {
    const results = await searchCustomers(query)
    cb(results.map(r => ({ value: r.name, ...r })))
  } catch (e) { cb([]) }
}

const onCustomerSelect = (item) => {
  form.customer_id = item.id
  customerSearch.value = item.name
}

const submitCreate = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    await createTicket({ ...form })
    ElMessage.success('工单创建成功')
    createVisible.value = false
    loadTickets()
  } catch (e) {
    console.error('创建失败', e)
  } finally {
    submitting.value = false
  }
}

const viewTicket = (row) => {
  router.push(`/tickets/${row.id}`)
}

// 格式化
const statusType = (s) => {
  const map = { pending: 'danger', processing: 'warning', waiting_feedback: 'info', resolved: 'success', closed: '' }
  return map[s] || ''
}
const statusText = (s) => {
  const map = { pending: '待处理', processing: '处理中', waiting_feedback: '等待反馈', resolved: '已解决', closed: '已关闭' }
  return map[s] || s
}
const priorityType = (p) => {
  const map = { urgent: 'danger', high: 'warning', normal: 'info', low: 'success' }
  return map[p] || 'info'
}
const priorityText = (p) => {
  const map = { urgent: '紧急', high: '高', normal: '普通', low: '低' }
  return map[p] || p
}
const formatTime = (time) => {
  if (!time) return '-'
  const timeStr = time.toString()
  const utcTime = timeStr.endsWith('Z') ? timeStr : timeStr + '+00:00'
  return new Date(utcTime).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}

onMounted(() => {
  loadTickets()
})
</script>

<style scoped>
/* ===== 全局基础 ===== */
.tickets-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #f0f4f8 0%, #e6eef7 100%);
}

/* ===== 导航栏 ===== */
.top-nav {
  position: sticky;
  top: 0;
  z-index: 100;
  display: flex;
  align-items: center;
  padding: 0 24px;
  height: 56px;
  background: linear-gradient(90deg, #1a2a6c 0%, #2d4a8a 50%, #3a5ab0 100%);
  box-shadow: 0 2px 12px rgba(26, 42, 108, 0.25);
}

.nav-menu {
  display: flex;
  gap: 4px;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 8px 16px;
  border-radius: 6px;
  color: rgba(255,255,255,0.75);
  text-decoration: none;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.25s ease;
}

.nav-item:hover {
  color: #fff;
  background: rgba(255,255,255,0.1);
}

.nav-item.active {
  color: #fff;
  background: rgba(255,255,255,0.2);
  box-shadow: 0 0 0 1px rgba(255,255,255,0.15);
}

.nav-item .el-icon {
  font-size: 16px;
}

.content {
  padding: 20px 24px 40px;
  max-width: 1440px;
  margin: 0 auto;
}

.content > .el-card {
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-header span {
  font-weight: 600;
  font-size: 15px;
  color: #1a1a2e;
}

.filter-bar {
  margin-bottom: 20px;
}

.ticket-link {
  color: #2d4a8a;
  text-decoration: none;
  font-weight: 600;
}

.ticket-link:hover {
  color: #1a2a6c;
  text-decoration: underline;
}

.pagination {
  margin-top: 20px;
  justify-content: flex-end;
}

/* 看板样式 */
.kanban-board {
  display: flex;
  gap: 16px;
  overflow-x: auto;
  padding-bottom: 10px;
}

.kanban-column {
  flex: 1;
  min-width: 260px;
  background: #f8f9fa;
  border-radius: 12px;
  padding: 14px;
  border: 1px solid #eee;
}

.column-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 12px;
  font-weight: 700;
  border-radius: 8px;
  margin-bottom: 12px;
  font-size: 14px;
}

.column-header.pending { background: #fff0f0; color: #ff6b6b; }
.column-header.processing { background: #fff8e6; color: #ffa726; }
.column-header.waiting_feedback { background: #e8f4fd; color: #42a5f5; }
.column-header.resolved { background: #e8f8e8; color: #66bb6a; }

.column-body {
  min-height: 300px;
}

.kanban-card {
  margin-bottom: 10px;
  cursor: grab;
  border-radius: 8px;
  box-shadow: 0 1px 4px rgba(0,0,0,0.06);
  border: none;
}

.kanban-card:active {
  cursor: grabbing;
}

.card-priority {
  margin-bottom: 8px;
}

.card-title {
  font-weight: 600;
  margin-bottom: 8px;
  color: #1a1a2e;
  font-size: 14px;
}

.card-info {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
  color: #888;
}

.drop-zone {
  border: 2px dashed #e0e0e0;
  border-radius: 8px;
  padding: 24px;
  text-align: center;
  color: #aaa;
  margin-top: 10px;
  transition: all 0.3s;
  font-size: 13px;
}

.drop-zone.active {
  border-color: #42a5f5;
  background: #e8f4fd;
  color: #42a5f5;
}
</style>
