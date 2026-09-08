import { describe, expect, it } from 'vitest'
import { statusChangeLabel, ticketEventTypeLabel, ticketStatusLabel } from './labels'

describe('labels', () => {
  it('映射已知枚举为中文，未知值原样返回', () => {
    expect(ticketStatusLabel('PENDING')).toBe('待处理')
    expect(ticketStatusLabel('UNKNOWN')).toBe('UNKNOWN')
    expect(ticketEventTypeLabel('WORK_RECORD')).toBe('工作记录')
    expect(ticketEventTypeLabel('CUSTOM')).toBe('CUSTOM')
  })
  it('状态变更内容转为中文箭头形式', () => {
    expect(statusChangeLabel('PENDING -> IN_PROGRESS')).toBe('待处理 → 处理中')
    expect(statusChangeLabel('RECEIVED -> DIAGNOSING')).toBe('已收货 → 检测中')
    expect(statusChangeLabel('普通文本')).toBe('普通文本')
    expect(statusChangeLabel('PENDING -> OTHER')).toBe('PENDING -> OTHER')
  })
})
