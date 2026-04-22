<template>
  <div class="customer-detail-page">
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

    <div class="content" v-loading="loading">
      <!-- 客户信息卡片 -->
      <el-card class="info-card" v-if="customer">
        <template #header>
          <div class="card-header">
            <div class="header-left">
              <h2>{{ customer.name }}</h2>
              <el-tag :type="activityType(customer.activity_level)" size="small">
                {{ activityText(customer.activity_level) }}
              </el-tag>
            </div>
            <div class="header-actions">
              <el-button type="primary" @click="showEditDialog">
                <el-icon><Edit /></el-icon>编辑
              </el-button>
              <el-button type="danger" @click="confirmDelete">
                <el-icon><Delete /></el-icon>删除
              </el-button>
            </div>
          </div>
        </template>

        <el-descriptions :column="4" border>
          <el-descriptions-item label="联系人">{{ customer.contact_person || '-' }}</el-descriptions-item>
          <el-descriptions-item label="电话">{{ customer.phone || '-' }}</el-descriptions-item>
          <el-descriptions-item label="邮箱">{{ customer.email || '-' }}</el-descriptions-item>
          <el-descriptions-item label="地区">{{ customer.region || '-' }}</el-descriptions-item>
          <el-descriptions-item label="行业">{{ customer.industry || '-' }}</el-descriptions-item>
          <el-descriptions-item label="创建时间">{{ formatTime(customer.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="最后联系">{{ formatTime(customer.last_contact_at) }}</el-descriptions-item>
        </el-descriptions>
      </el-card>

      <el-row :gutter="20" class="detail-row">
        <!-- 设备清单 -->
        <el-col :span="8">
          <el-card>
            <template #header>
              <div class="card-header">
                <span>设备清单</span>
                <el-button link type="primary" @click="showAddDevice = true">+ 添加设备</el-button>
              </div>
            </template>
            <el-empty v-if="!devices.length" description="暂无设备" />
            <el-timeline v-else>
              <el-timeline-item
                v-for="device in devices"
                :key="device.id"
                type="primary"
                :icon="Monitor"
              >
                <div class="device-item">
                  <div class="device-model">{{ device.model || '未命名设备' }}</div>
                  <div class="device-info">
                    <span v-if="device.serial_number">序列号: {{ device.serial_number }}</span>
                    <span v-if="device.firmware_version">固件: {{ device.firmware_version }}</span>
                  </div>
                </div>
              </el-timeline-item>
            </el-timeline>
          </el-card>
        </el-col>

        <!-- 互动时间轴 -->
        <el-col :span="16">
          <el-card>
            <template #header>
              <div class="card-header">
                <span>互动时间轴</span>
                <el-button type="primary" @click="showCreateTicket = true">
                  <el-icon><Plus /></el-icon>新工单
                </el-button>
              </div>
            </template>

            <el-empty v-if="!timeline.length" description="暂无互动记录" />
            <el-timeline v-else>
              <el-timeline-item
                v-for="item in timeline"
                :key="item.id + item.type"
                :type="timelineType(item.type, item.status)"
                :icon="timelineIcon(item.type)"
              >
                <div class="timeline-card" :class="item.type">
                  <div class="timeline-header">
                    <span class="timeline-type">{{ timelineTypeText(item.type, item.status) }}</span>
                    <span class="timeline-time">{{ relativeTime(item.created_at) }}</span>
                  </div>
                  <div class="timeline-content" v-if="item.title">
                    <router-link :to="`/tickets/${item.id}`" class="ticket-link">
                      {{ item.title }}
                    </router-link>
                  </div>
                  <div class="timeline-content" v-if="item.content">{{ item.content }}</div>
                </div>
              </el-timeline-item>
            </el-timeline>
          </el-card>
        </el-col>
      </el-row>
    </div>

    <!-- 编辑客户弹窗 -->
    <el-dialog v-model="editVisible" title="编辑客户" width="500px">
      <el-form :model="editForm" label-width="80px" ref="editFormRef">
        <el-form-item label="客户名称">
          <el-input v-model="editForm.name" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="editForm.contact_person" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="editForm.phone" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="editForm.email" />
        </el-form-item>
        <el-form-item label="地区">
          <el-input v-model="editForm.region" />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="editForm.industry" />
        </el-form-item>
        <el-form-item label="活跃度">
          <el-select v-model="editForm.activity_level" style="width: 100%">
            <el-option label="高" value="high" />
            <el-option label="中" value="medium" />
            <el-option label="低" value="low" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" @click="submitEdit" :loading="submitting">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Monitor } from '@element-plus/icons-vue'
import { getCustomerDetail, updateCustomer, deleteCustomer, createTicket } from '../api'

const route = useRoute()
const router = useRouter()
const loading = ref(false)

const customer = ref(null)
const devices = ref([])
const timeline = ref([])

const editVisible = ref(false)
const submitting = ref(false)
const editFormRef = ref(null)
const editForm = reactive({
  id: null,
  name: '',
  contact_person: '',
  phone: '',
  email: '',
  region: '',
  industry: '',
  activity_level: 'medium'
})

const loadData = async () => {
  loading.value = true
  try {
    const data = await getCustomerDetail(route.params.id)
    customer.value = data
    devices.value = data.devices || []
    timeline.value = data.timeline || []

    // 填充编辑表单
    Object.assign(editForm, data)
  } catch (e) {
    ElMessage.error('加载客户详情失败')
  } finally {
    loading.value = false
  }
}

const showEditDialog = () => {
  editVisible.value = true
}

const submitEdit = async () => {
  submitting.value = true
  try {
    await updateCustomer(editForm.id, { ...editForm })
    ElMessage.success('更新成功')
    editVisible.value = false
    loadData()
  } catch (e) {
    console.error('更新失败', e)
  } finally {
    submitting.value = false
  }
}

const confirmDelete = () => {
  ElMessageBox.confirm(
    `确定删除客户 "${customer.value.name}" 吗？`,
    '确认删除',
    { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
  ).then(async () => {
    await deleteCustomer(customer.value.id)
    ElMessage.success('删除成功')
    router.push('/customers')
  }).catch(() => {})
}

const activityType = (level) => {
  const map = { high: 'success', medium: 'warning', low: 'info' }
  return map[level] || 'info'
}

const activityText = (level) => {
  const map = { high: '高', medium: '中', low: '低' }
  return map[level] || level
}

const timelineType = (type, status) => {
  if (type === 'ticket') {
    const map = { pending: 'danger', processing: 'warning', waiting_feedback: 'info', resolved: 'success', closed: '' }
    return map[status] || 'primary'
  }
  if (type === 'system') return 'warning'
  return 'info'
}

const timelineIcon = (type) => {
  if (type === 'ticket') return 'Ticket'
  if (type === 'system') return 'Switch'
  return 'ChatLineRound'
}

const timelineTypeText = (type, status) => {
  if (type === 'ticket') {
    const map = { pending: '工单创建', processing: '处理中', waiting_feedback: '等待反馈', resolved: '已解决', closed: '已关闭' }
    return map[status] || '工单'
  }
  if (type === 'system') return '系统记录'
  return '跟进备注'
}

const relativeTime = (time) => {
  if (!time) return '-'
  const timeStr = time.toString()
  const utcTime = timeStr.endsWith('Z') ? timeStr : timeStr + '+00:00'
  const date = new Date(utcTime)
  const now = new Date()
  const diff = Math.floor((now - date) / 1000)

  if (diff < 60) return '刚刚'
  if (diff < 3600) return `${Math.floor(diff / 60)}分钟前`
  if (diff < 86400) return `${Math.floor(diff / 3600)}小时前`
  if (diff < 172800) return '昨天'
  if (diff < 604800) return `${Math.floor(diff / 86400)}天前`
  return date.toLocaleDateString('zh-CN')
}

const formatTime = (time) => {
  if (!time) return '-'
  const timeStr = time.toString()
  const utcTime = timeStr.endsWith('Z') ? timeStr : timeStr + '+00:00'
  return new Date(utcTime).toLocaleString('zh-CN', {
    year: 'numeric', month: '2-digit', day: '2-digit',
    hour: '2-digit', minute: '2-digit'
  })
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
/* ===== 全局基础 ===== */
.customer-detail-page {
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

.info-card {
  margin-bottom: 20px;
}

.info-card :deep(.el-card__header) {
  padding: 14px 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.header-left h2 {
  margin: 0;
  font-size: 20px;
  color: #1a1a2e;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.detail-row {
  margin-top: 16px;
}

.detail-row .el-card {
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}

.device-item {
  padding: 8px 0;
}

.device-model {
  font-weight: 600;
  color: #1a1a2e;
}

.device-info {
  font-size: 12px;
  color: #888;
  margin-top: 4px;
}

.device-info span {
  margin-right: 10px;
}

.timeline-card {
  padding: 12px 14px;
  border-radius: 8px;
  background: #f8f9fa;
  transition: all 0.25s ease;
}

.timeline-card:hover {
  background: #f0f4f8;
}

.timeline-card.ticket {
  background: #e8f4fd;
}

.timeline-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}

.timeline-type {
  font-weight: 600;
  font-size: 13px;
  color: #2d4a8a;
}

.timeline-time {
  font-size: 12px;
  color: #999;
}

.timeline-content {
  color: #444;
  font-size: 14px;
  line-height: 1.5;
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
</style>
