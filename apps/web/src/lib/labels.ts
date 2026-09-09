import type { BugStatus, DeviceOwnerType, DeviceStatus, LoanStatus, RepairStatus, Role, TicketAssistStatus, TicketCategory, TicketPriority, TicketStatus, UserStatus, WorkItemPriority, WorkItemStatus } from '../types'

export const ticketStatusLabels: Record<TicketStatus, string> = { PENDING: '待处理', IN_PROGRESS: '处理中', WAITING_CUSTOMER: '等待客户', WAITING_RND: '等待研发', RESOLVED: '已解决', CLOSED: '已关闭' }
export const ticketPriorityLabels: Record<TicketPriority, string> = { LOW: '低', MEDIUM: '中', HIGH: '高', URGENT: '紧急' }
export const ticketCategoryLabels: Record<TicketCategory, string> = { PRE_SALES: '售前咨询', TRAINING: '客户培训', POINTCLOUD_DEBUG: '点云调试', SDK_DEVELOPMENT: 'SDK 开发', HAND_EYE_CALIBRATION: '手眼标定', HARDWARE_FAILURE: '硬件故障', OTHER: '其他' }
export const TICKET_CATEGORIES = Object.keys(ticketCategoryLabels) as TicketCategory[]
export const ticketCategoryLabel = (category: string) => ticketCategoryLabels[category as TicketCategory] ?? category
export const ticketEventTypeLabels: Record<string, string> = { CUSTOMER_REPLY: '客户回复', INTERNAL_NOTE: '跟进记录', STATUS_CHANGE: '状态变更', ASSIGNMENT: '指派', ATTACHMENT: '附件', WORK_RECORD: '工作记录', RESOLUTION: '解决方案', ASSIST_REQUEST: '协助邀请', ASSIST_ACCEPT: '接受协助', ASSIST_REJECT: '驳回协助', DELETE: '移入回收站', RESTORE: '恢复工单' }
export const ticketAssistStatusLabels: Record<TicketAssistStatus, string> = { PENDING: '待处理', ACCEPTED: '已接受', REJECTED: '已驳回', CANCELLED: '已撤销' }
export const workItemStatusLabels: Record<WorkItemStatus, string> = { TODO: '待办', IN_PROGRESS: '进行中', WAITING_FEEDBACK: '等待反馈', COMPLETED: '已完成', CANCELED: '已取消' }
export const workItemPriorityLabels: Record<WorkItemPriority, string> = ticketPriorityLabels
export const worklogStatusLabels: Record<string, string> = { DRAFT: '草稿', CONFIRMED: '已确认' }
export const worklogSourceLabels: Record<string, string> = { WEB: '网页录入', IMPORT: '导入', AI_DRAFT: 'AI草稿', DESKTOP: '桌面端' }
export const userStatusLabels: Record<UserStatus, string> = { PENDING: '待审批', ACTIVE: '正常', DISABLED: '已禁用' }
export const roleLabels: Record<Role, string> = { admin: '管理员', support: '技术支持', employee: '员工', customer: '客户' }
export const deviceStatusLabels: Record<DeviceStatus, string> = { IN_STOCK: '在库', LOANED: '借测中', REPAIRING: '返修中', RETIRED: '已报废' }
export const deviceOwnerLabels: Record<DeviceOwnerType, string> = { COMPANY: '公司样机', CUSTOMER: '客户资产' }
export const loanStatusLabels: Record<LoanStatus, string> = { ONGOING: '借出中', OVERDUE: '已逾期', RETURNED: '已归还', CANCELLED: '已取消' }
export const repairStatusLabels: Record<RepairStatus, string> = { RECEIVED: '已收货', DIAGNOSING: '检测中', REPAIRING: '维修中', SHIPPED: '已寄回', CLOSED: '已关闭' }
export const bugStatusLabels: Record<BugStatus, string> = { OPEN: '待处理', IN_PROGRESS: '修复中', FIXED: '已修复' }
export const notificationSeverityLabels: Record<string, string> = { INFO: '提示', WARNING: '警告', CRITICAL: '紧急' }

const lookup = (labels: Record<string, string>, value: string | null | undefined): string => (value ? labels[value] ?? value : '-')

export const ticketStatusLabel = (status: string) => lookup(ticketStatusLabels, status)
export const ticketPriorityLabel = (priority: string) => lookup(ticketPriorityLabels, priority)
export const ticketEventTypeLabel = (type: string) => lookup(ticketEventTypeLabels, type)
export const ticketAssistStatusLabel = (status: string) => lookup(ticketAssistStatusLabels, status)
export const workItemStatusLabel = (status: string) => lookup(workItemStatusLabels, status)
export const workItemPriorityLabel = (priority: string) => lookup(workItemPriorityLabels, priority)
export const worklogStatusLabel = (status: string) => lookup(worklogStatusLabels, status)
export const worklogSourceLabel = (source: string) => lookup(worklogSourceLabels, source)
export const userStatusLabel = (status: string) => lookup(userStatusLabels, status)
export const roleLabel = (role: string) => lookup(roleLabels, role)
export const deviceStatusLabel = (status: string) => lookup(deviceStatusLabels, status)
export const deviceOwnerLabel = (ownerType: string) => lookup(deviceOwnerLabels, ownerType)
// 按归属区分状态文案：IN_STOCK 公司样机为"公司库存"，客户资产为"客户使用中"
export function deviceStatusLabelByOwner(status: string, ownerType?: DeviceOwnerType | null): string {
  if (status === 'IN_STOCK') return ownerType === 'COMPANY' ? '公司库存' : '客户使用中'
  return lookup(deviceStatusLabels, status)
}
export const loanStatusLabel = (status: string) => lookup(loanStatusLabels, status)
export const repairStatusLabel = (status: string) => lookup(repairStatusLabels, status)
export const bugStatusLabel = (status: string) => lookup(bugStatusLabels, status)
export const notificationSeverityLabel = (severity: string) => lookup(notificationSeverityLabels, severity)

const statusChangeValues: Record<string, string> = { ...ticketStatusLabels, ...repairStatusLabels }
export function statusChangeLabel(content: string): string {
  const parts = content.split(/\s*(?:->|→)\s*/)
  if (parts.length < 2 || !parts.every((part) => statusChangeValues[part])) return content
  return parts.map((part) => statusChangeValues[part]).join(' → ')
}
