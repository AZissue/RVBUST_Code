import request from './request'

// ==================== 首页工作台 ====================
export const getDashboardStats = () => request.get('/dashboard/stats')
export const getTodoList = (assignee) => request.get('/dashboard/todos', { params: { assignee } })
export const quickCreateTicket = (data) => request.post('/tickets/quick', data)

// ==================== 客户管理 ====================
export const getCustomers = (params) => request.get('/customers', { params })
export const searchCustomers = (q) => request.get('/customers/search', { params: { q } })
export const getCustomerDetail = (id) => request.get(`/customers/${id}`)
export const createCustomer = (data) => request.post('/customers', data)
export const updateCustomer = (id, data) => request.put(`/customers/${id}`, data)
export const deleteCustomer = (id) => request.delete(`/customers/${id}`)

// ==================== 工单管理 ====================
export const getTickets = (params) => request.get('/tickets', { params })
export const getTicketDetail = (id) => request.get(`/tickets/${id}`)
export const createTicket = (data) => request.post('/tickets', data)
export const updateTicket = (id, data) => request.put(`/tickets/${id}`, data)
export const updateTicketStatus = (id, status) => request.put(`/tickets/${id}/status`, { status })
export const deleteTicket = (id) => request.delete(`/tickets/${id}`)

// ==================== 跟进记录 ====================
export const createFollowUp = (data) => request.post('/follow_ups', data)

// ==================== 数据导入导出 ====================
export const exportJson = () => request.get('/data/export/json', { responseType: 'blob' })
export const exportCsv = () => request.get('/data/export/csv', { responseType: 'blob' })
export const exportCustomersCsv = () => request.get('/data/export/customers/csv', { responseType: 'blob' })
export const importJson = (file) => {
  const formData = new FormData()
  formData.append('file', file)
  return request.post('/data/import/json', formData, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

// ==================== 提醒通知 ====================
export const getReminders = (params) => request.get('/reminders', { params })
export const getReminderStats = (assignee) => request.get('/reminders/stats', { params: { assignee } })
