// 工单问题分类白名单（与前端 lib/labels.ts 的 TICKET_CATEGORIES 保持一致，顺序即展示顺序）
export const TICKET_CATEGORIES = ['售前咨询', '客户培训', '点云调试', 'SDK 开发', '手眼标定', '硬件故障', '其他'] as const
export type TicketCategory = (typeof TICKET_CATEGORIES)[number]
export const isTicketCategory = (value: string): value is TicketCategory =>
  (TICKET_CATEGORIES as readonly string[]).includes(value)
