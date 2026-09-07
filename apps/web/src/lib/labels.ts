import type { DeviceStatus, LoanStatus, RepairStatus, Role, TicketPriority, TicketStatus, UserStatus, WorkItemPriority, WorkItemStatus } from '../types'

export const ticketStatusLabels: Record<TicketStatus, string> = { PENDING: '待处理', IN_PROGRESS: '处理中', WAITING_CUSTOMER: '等待客户', WAITING_RND: '等待研发', RESOLVED: '已解决', CLOSED: '已关闭' }
export const ticketPriorityLabels: Record<TicketPriority, string> = { LOW: '低', MEDIUM: '中', HIGH: '高', URGENT: '紧急' }
export const ticketSourceLabels: Record<string, string> = { CUSTOMER_INQUIRY: '客户咨询', PRE_SALES_SELECTION: '售前选型', AFTER_SALES_INCIDENT: '售后故障', ON_SITE_DEBUGGING: '现场调试', INTERNAL_TESTING: '内部测试', TRAINING: '培训', SDK_SOFTWARE: 'SDK与软件', OTHER: '其他' }
export const ticketEventTypeLabels: Record<string, string> = { CUSTOMER_REPLY: '客户回复', INTERNAL_NOTE: '内部备注', STATUS_CHANGE: '状态变更', ASSIGNMENT: '指派', ATTACHMENT: '附件', WORK_RECORD: '工作记录', RESOLUTION: '解决方案' }
export const workItemStatusLabels: Record<WorkItemStatus, string> = { TODO: '待办', IN_PROGRESS: '进行中', WAITING_FEEDBACK: '等待反馈', COMPLETED: '已完成', CANCELED: '已取消' }
export const workItemPriorityLabels: Record<WorkItemPriority, string> = ticketPriorityLabels
export const worklogStatusLabels: Record<string, string> = { DRAFT: '草稿', CONFIRMED: '已确认' }
export const worklogSourceLabels: Record<string, string> = { WEB: '网页录入', IMPORT: '导入', AI_DRAFT: 'AI草稿', DESKTOP: '桌面端' }
export const userStatusLabels: Record<UserStatus, string> = { PENDING: '待审批', ACTIVE: '正常', DISABLED: '已禁用' }
export const roleLabels: Record<Role, string> = { admin: '管理员', support: '技术支持', employee: '员工', customer: '客户' }
export const deviceStatusLabels: Record<DeviceStatus, string> = { IN_STOCK: '在库', LOANED: '借出', REPAIRING: '返修中', RETIRED: '报废' }
export const loanStatusLabels: Record<LoanStatus, string> = { ONGOING: '借出中', OVERDUE: '已逾期', RETURNED: '已归还', CANCELLED: '已取消' }
export const repairStatusLabels: Record<RepairStatus, string> = { RECEIVED: '已收货', DIAGNOSING: '检测中', REPAIRING: '维修中', SHIPPED: '已寄回', CLOSED: '已关闭' }
export const notificationSeverityLabels: Record<string, string> = { INFO: '提示', WARNING: '警告', CRITICAL: '紧急' }

const lookup = (labels: Record<string, string>, value: string | null | undefined): string => (value ? labels[value] ?? value : '-')

export const ticketStatusLabel = (status: string) => lookup(ticketStatusLabels, status)
export const ticketPriorityLabel = (priority: string) => lookup(ticketPriorityLabels, priority)
export const ticketSourceLabel = (source: string) => lookup(ticketSourceLabels, source)
export const ticketEventTypeLabel = (type: string) => lookup(ticketEventTypeLabels, type)
export const workItemStatusLabel = (status: string) => lookup(workItemStatusLabels, status)
export const workItemPriorityLabel = (priority: string) => lookup(workItemPriorityLabels, priority)
export const worklogStatusLabel = (status: string) => lookup(worklogStatusLabels, status)
export const worklogSourceLabel = (source: string) => lookup(worklogSourceLabels, source)
export const userStatusLabel = (status: string) => lookup(userStatusLabels, status)
export const roleLabel = (role: string) => lookup(roleLabels, role)
export const deviceStatusLabel = (status: string) => lookup(deviceStatusLabels, status)
export const loanStatusLabel = (status: string) => lookup(loanStatusLabels, status)
export const repairStatusLabel = (status: string) => lookup(repairStatusLabels, status)
export const notificationSeverityLabel = (severity: string) => lookup(notificationSeverityLabels, severity)

const statusChangeValues: Record<string, string> = { ...ticketStatusLabels, ...repairStatusLabels }
export function statusChangeLabel(content: string): string {
  const parts = content.split(/\s*(?:->|→)\s*/)
  if (parts.length < 2 || !parts.every((part) => statusChangeValues[part])) return content
  return parts.map((part) => statusChangeValues[part]).join(' → ')
}
