// 服务端错误提示中的状态/枚举中文映射（展示层文案，与前端 lib/labels.ts 对应）
const STATUS_LABELS: Record<string, string> = {
  // TicketStatus
  PENDING: '待处理',
  IN_PROGRESS: '处理中',
  WAITING_CUSTOMER: '等待客户',
  WAITING_RND: '等待研发',
  RESOLVED: '已解决',
  CLOSED: '已关闭',
  // DeviceStatus
  IN_STOCK: '在库',
  LOANED: '借出',
  REPAIRING: '返修中',
  RETIRED: '报废',
  // LoanStatus
  ONGOING: '借出中',
  OVERDUE: '已逾期',
  RETURNED: '已归还',
  CANCELLED: '已取消',
  // RepairStatus
  RECEIVED: '已收货',
  DIAGNOSING: '检测中',
  SHIPPED: '已寄回',
  // UserStatus
  ACTIVE: '正常',
  DISABLED: '已禁用',
};

/** 把状态枚举值翻译成中文；未知值原样返回 */
export function zhStatus(status: string): string {
  return STATUS_LABELS[status] ?? status;
}

const USER_STATUS_LABELS: Record<string, string> = {
  PENDING: '待审批',
  ACTIVE: '正常',
  DISABLED: '已禁用',
};

/** 用户状态专用映射（PENDING 在用户语境是"待审批"） */
export function zhUserStatus(status: string): string {
  return USER_STATUS_LABELS[status] ?? status;
}
