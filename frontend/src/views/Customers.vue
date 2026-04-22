<template>
  <div class="customers-page">
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
            <span>客户列表</span>
            <el-button type="primary" @click="showCreateDialog">
              <el-icon><Plus /></el-icon>新建客户
            </el-button>
          </div>
        </template>

        <!-- 搜索栏 -->
        <el-row :gutter="10" class="search-bar">
          <el-col :span="8">
            <el-input
              v-model="searchQuery"
              placeholder="搜索客户名称/联系人/电话"
              clearable
              @clear="loadCustomers"
              @keyup.enter="loadCustomers"
            >
              <template #prefix>
                <el-icon><Search /></el-icon>
              </template>
            </el-input>
          </el-col>
          <el-col :span="4">
            <el-button type="primary" @click="loadCustomers">搜索</el-button>
          </el-col>
        </el-row>

        <!-- 客户表格 -->
        <el-table :data="customers" style="width: 100%" v-loading="loading">
          <el-table-column prop="name" label="客户名称" min-width="150">
            <template #default="{ row }">
              <router-link :to="`/customers/${row.id}`" class="customer-link">
                {{ row.name }}
              </router-link>
            </template>
          </el-table-column>
          <el-table-column prop="contact_person" label="联系人" width="100" />
          <el-table-column prop="phone" label="电话" width="130" />
          <el-table-column prop="region" label="地区" width="100" />
          <el-table-column prop="industry" label="行业" width="100" />
          <el-table-column prop="activity_level" label="活跃度" width="90">
            <template #default="{ row }">
              <el-tag :type="activityType(row.activity_level)" size="small">
                {{ activityText(row.activity_level) }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column prop="last_contact_at" label="最后联系" width="150">
            <template #default="{ row }">
              {{ formatTime(row.last_contact_at) }}
            </template>
          </el-table-column>
          <el-table-column label="操作" width="150" fixed="right">
            <template #default="{ row }">
              <el-button link type="primary" @click="editCustomer(row)">编辑</el-button>
              <el-button link type="danger" @click="confirmDelete(row)">删除</el-button>
            </template>
          </el-table-column>
        </el-table>

        <!-- 分页 -->
        <el-pagination
          class="pagination"
          v-model:current-page="page"
          v-model:page-size="pageSize"
          :total="total"
          :page-sizes="[10, 20, 50]"
          layout="total, sizes, prev, pager, next"
          @change="loadCustomers"
        />
      </el-card>
    </div>

    <!-- 新建/编辑客户弹窗 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEdit ? '编辑客户' : '新建客户'"
      width="500px"
    >
      <el-form :model="form" label-width="80px" :rules="rules" ref="formRef">
        <el-form-item label="客户名称" prop="name">
          <el-input v-model="form.name" placeholder="客户名称" />
        </el-form-item>
        <el-form-item label="联系人">
          <el-input v-model="form.contact_person" placeholder="联系人姓名" />
        </el-form-item>
        <el-form-item label="电话">
          <el-input v-model="form.phone" placeholder="联系电话" />
        </el-form-item>
        <el-form-item label="邮箱">
          <el-input v-model="form.email" placeholder="邮箱地址" />
        </el-form-item>
        <el-form-item label="地区">
          <el-input v-model="form.region" placeholder="所在地区" />
        </el-form-item>
        <el-form-item label="行业">
          <el-input v-model="form.industry" placeholder="所属行业" />
        </el-form-item>
        <el-form-item label="活跃度">
          <el-select v-model="form.activity_level" style="width: 100%">
            <el-option label="高" value="high" />
            <el-option label="中" value="medium" />
            <el-option label="低" value="low" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" @click="submitForm" :loading="submitting">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getCustomers, createCustomer, updateCustomer, deleteCustomer } from '../api'

const loading = ref(false)
const customers = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const searchQuery = ref('')

const dialogVisible = ref(false)
const isEdit = ref(false)
const submitting = ref(false)
const formRef = ref(null)

const form = reactive({
  id: null,
  name: '',
  contact_person: '',
  phone: '',
  email: '',
  region: '',
  industry: '',
  activity_level: 'medium'
})

const rules = {
  name: [{ required: true, message: '请输入客户名称', trigger: 'blur' }]
}

const loadCustomers = async () => {
  loading.value = true
  try {
    const res = await getCustomers({
      q: searchQuery.value,
      page: page.value,
      page_size: pageSize.value
    })
    customers.value = res.items
    total.value = res.total
  } catch (e) {
    console.error('加载客户列表失败', e)
  } finally {
    loading.value = false
  }
}

const showCreateDialog = () => {
  isEdit.value = false
  resetForm()
  dialogVisible.value = true
}

const editCustomer = (row) => {
  isEdit.value = true
  Object.assign(form, row)
  dialogVisible.value = true
}

const resetForm = () => {
  form.id = null
  form.name = ''
  form.contact_person = ''
  form.phone = ''
  form.email = ''
  form.region = ''
  form.industry = ''
  form.activity_level = 'medium'
}

const submitForm = async () => {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return

  submitting.value = true
  try {
    if (isEdit.value) {
      await updateCustomer(form.id, { ...form })
      ElMessage.success('更新成功')
    } else {
      await createCustomer({ ...form })
      ElMessage.success('创建成功')
    }
    dialogVisible.value = false
    loadCustomers()
  } catch (e) {
    console.error('保存失败', e)
  } finally {
    submitting.value = false
  }
}

const confirmDelete = (row) => {
  ElMessageBox.confirm(
    `确定删除客户 "${row.name}" 吗？相关工单也将被删除`,
    '确认删除',
    { confirmButtonText: '删除', cancelButtonText: '取消', type: 'warning' }
  ).then(async () => {
    await deleteCustomer(row.id)
    ElMessage.success('删除成功')
    loadCustomers()
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

const formatTime = (time) => {
  if (!time) return '-'
  const timeStr = time.toString()
  const utcTime = timeStr.endsWith('Z') ? timeStr : timeStr + '+00:00'
  return new Date(utcTime).toLocaleString('zh-CN', {
    month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit'
  })
}

onMounted(() => {
  loadCustomers()
})
</script>

<style scoped>
/* ===== 全局基础 ===== */
.customers-page {
  min-height: 100vh;
  background: linear-gradient(135deg, #f0f4f8 0%, #e6eef7 100%);
}

/* ===== 导航栏（复用Dashboard样式） ===== */
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

.search-bar {
  margin-bottom: 20px;
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

.pagination {
  margin-top: 20px;
  justify-content: flex-end;
}
</style>
