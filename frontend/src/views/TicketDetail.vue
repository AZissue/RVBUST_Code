<template>
  <div class="ticket-detail-page">
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
      <template v-if="ticket">
        <!-- 工单头部信息 -->
        <el-card class="ticket-header">
          <div class="header-top">
            <div class="header-left">
              <h2>#{{ ticket.id }} {{ ticket.title }}</h2>
              <div class="header-tags">
                <el-tag :type="statusType(ticket.status)" size="large" effect="dark">
                  {{ statusText(ticket.status) }}
                </el-tag>
                <el-tag :type="priorityType(ticket.priority)" effect="dark">
                  {{ priorityText(ticket.priority) }}
                </el-tag>
                <el-tag type="info">{{ ticket.category }}</el-tag>
              </div>
            </div>
            <div class="header-actions">
              <el-button
                v-if="ticket.status === 'pending'"
                type="primary"
                @click="changeStatus('processing')"
              >
                开始处理
              </el-button>
              <el-button
                v-if="ticket.status === 'processing'"
                type="warning"
                @click="changeStatus('waiting_feedback')"
              >
                等待客户反馈
              </el-button>
              <el-button
                v-if="['processing', 'waiting_feedback'].includes(ticket.status)"
                type="success"
                @click="showResolveDialog"
              >
                标记已解决
              </el-button>
              <el-button
                v-if="ticket.status === 'resolved'"
                @click="changeStatus('closed')"
              >
                关闭工单
              </el-button>
            </div>
          </div>

          <el-descriptions :column="4" border class="header-info">
            <el-descriptions-item label="客户">
              <router-link :to="`/customers/${ticket.customer_id}`" class="customer-link">
                {{ ticket.customer?.name || '-' }}
              </router-link>
            </el-descriptions-item>
            <el-descriptions-item label="负责人">{{ ticket.assignee || '-' }}</el-descriptions-item>
            <el-descriptions-item label="创建时间">{{ formatTime(ticket.created_at) }}</el-descriptions-item>
            <el-descriptions-item label="解决时间">{{ formatTime(ticket.resolved_at) || '-' }}</el-descriptions-item>
          </el-descriptions>
        </el-card>

        <el-row :gutter="20" class="detail-row">
          <!-- 左侧：问题描述和解决方案 -->
          <el-col :span="14">
            <el-card>
              <template #header>
                <span>问题描述</span>
              </template>
              <div class="description-content">{{ ticket.description || '暂无描述' }}</div>
            </el-card>

            <el-card class="solution-card" v-if="ticket.status === 'resolved' || ticket.status === 'closed'">
              <template #header>
                <span>解决方案</span>
              </template>
              <div class="solution-content">{{ ticket.solution || '未填写解决方案' }}</div>
            </el-card>

            <!-- 添加跟进记录 -->
            <el-card class="follow-up-card">
              <template #header>
                <span>添加跟进记录</span>
              </template>
              <el-input
                v-model="followContent"
                type="textarea"
                :rows="3"
                placeholder="输入跟进内容..."
              />
              <div class="follow-actions">
                <el-button type="primary" @click="submitFollowUp" :loading="followSubmitting">
                  提交记录
                </el-button>
              </div>
            </el-card>
          </el-col>

          <!-- 右侧：跟进时间轴 -->
          <el-col :span="10">
            <el-card>
              <template #header>
                <span>跟进记录</span>
              </template>
              <el-empty v-if="!followUps.length" description="暂无跟进记录" />
              <el-timeline v-else>
                <el-timeline-item
                  v-for="item in followUps"
                  :key="item.id"
                  :type="item.type === 'system' ? 'warning' : 'primary'"
                  :icon="item.type === 'system' ? 'Switch' : 'ChatLineRound'"
                >
                  <div class="follow-item">
                    <div class="follow-header">
                      <span class="follow-type">{{ item.type === 'system' ? '系统' : (item.created_by || '技术员') }}</span>
                      <span class="follow-time">{{ formatTime(item.created_at) }}</span>
                    </div>
                    <div class="follow-content">{{ item.content }}</div>
                  </div>
                </el-timeline-item>
              </el-timeline>
            </el-card>
          </el-col>
        </el-row>
      </template>
    </div>

    <!-- 解决工单弹窗 -->
    <el-dialog v-model="resolveVisible" title="标记工单已解决" width="500px">
      <el-form label-width="80px">
        <el-form-item label="解决方案">
          <el-input
            v-model="solution"
            type="textarea"
            :rows="4"
            placeholder="填写解决方案..."
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="resolveVisible = false">取消</el-button>
        <el-button type="success" @click="resolveTicket" :loading="submitting">确认解决</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getTicketDetail, updateTicketStatus, updateTicket, createFollowUp } from '../api'

const route = useRoute()
const router = useRouter()
const loading = ref(false)
const ticket = ref(null)
const followUps = ref([])

const followContent = ref('')
const followSubmitting = ref(false)

const resolveVisible = ref(false)
const solution = ref('')
const submitting = ref(false)

const loadData = async () => {
  loading.value = true
  try {
    const data = await getTicketDetail(route.params.id)
    ticket.value = data
    followUps.value = data.follow_ups || []
  } catch (e) {
    ElMessage.error('加载工单详情失败')
  } finally {
    loading.value = false
  }
}

const changeStatus = async (status) => {
  try {
    await updateTicketStatus(ticket.value.id, status)
    ElMessage.success('状态更新成功')
    loadData()
  } catch (e) {
    ElMessage.error('状态更新失败')
  }
}

const showResolveDialog = () => {
  solution.value = ticket.value.solution || ''
  resolveVisible.value = true
}

const resolveTicket = async () => {
  submitting.value = true
  try {
    // 先更新解决方案
    if (solution.value) {
      await updateTicket(ticket.value.id, { solution: solution.value })
    }
    // 再更新状态
    await updateTicketStatus(ticket.value.id, 'resolved')
    ElMessage.success('工单已标记为已解决')
    resolveVisible.value = false
    loadData()
  } catch (e) {
    ElMessage.error('操作失败')
  } finally {
    submitting.value = false
  }
}

const submitFollowUp = async () => {
  if (!followContent.value.trim()) {
    ElMessage.warning('请输入跟进内容')
    return
  }

  followSubmitting.value = true
  try {
    await createFollowUp({
      ticket_id: ticket.value.id,
      content: followContent.value,
      type: 'comment',
      created_by: ticket.value.assignee || '技术员'
    })
    ElMessage.success('跟进记录已添加')
    followContent.value = ''
    loadData()
  } catch (e) {
    console.error('添加失败', e)
  } finally {
    followSubmitting.value = false
  }
}

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
.ticket-detail-page {
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

.ticket-header {
  margin-bottom: 20px;
}

.header-top {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 15px;
}

.header-left h2 {
  margin: 0 0 10px 0;
  font-size: 20px;
  color: #1a1a2e;
}

.header-tags {
  display: flex;
  gap: 8px;
}

.header-actions {
  display: flex;
  gap: 10px;
}

.header-info {
  margin-top: 10px;
}

.customer-link {
  color: #2d4a8a;
  text-decoration: none;
  font-weight: 600;
}

.customer-link:hover {
  color: #1a2a6c;
  text-decoration: underline;
}

.detail-row {
  margin-top: 16px;
}

.detail-row .el-card {
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0,0,0,0.06);
}

.description-content,
.solution-content {
  line-height: 1.8;
  color: #444;
  white-space: pre-wrap;
  font-size: 14px;
}

.solution-card,
.follow-up-card {
  margin-top: 16px;
}

.follow-actions {
  margin-top: 15px;
  text-align: right;
}

.follow-item {
  padding: 8px 0;
}

.follow-header {
  display: flex;
  justify-content: space-between;
  margin-bottom: 6px;
}

.follow-type {
  font-weight: 600;
  font-size: 13px;
  color: #2d4a8a;
}

.follow-time {
  font-size: 12px;
  color: #999;
}

.follow-content {
  color: #444;
  line-height: 1.5;
  font-size: 14px;
}
</style>
