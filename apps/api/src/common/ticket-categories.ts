// 工单问题分类枚举的中文联映射（与前端 lib/labels.ts 的 ticketCategoryLabels 保持一致，顺序即展示顺序）
import type { TicketCategory } from '@prisma/client'

export const TICKET_CATEGORY_LABELS: Record<TicketCategory, string> = {
  PRE_SALES: '售前咨询',
  TRAINING: '客户培训',
  POINTCLOUD_DEBUG: '点云调试',
  SDK_DEVELOPMENT: 'SDK 开发',
  HAND_EYE_CALIBRATION: '手眼标定',
  HARDWARE_FAILURE: '硬件故障',
  OTHER: '其他',
}

export const TICKET_CATEGORIES = Object.keys(TICKET_CATEGORY_LABELS) as TicketCategory[]

export const ticketCategoryLabel = (category: TicketCategory): string => TICKET_CATEGORY_LABELS[category]

/** 历史自由文本/工作类型标签 → 枚举代码（无法识别归 OTHER），用于 V1 迁移与历史事项转换 */
export const ticketCategoryFromLabel = (label: string): TicketCategory => {
  const found = (Object.entries(TICKET_CATEGORY_LABELS) as Array<[TicketCategory, string]>).find(([, text]) => text === label.trim())
  return found ? found[0] : 'OTHER'
}
