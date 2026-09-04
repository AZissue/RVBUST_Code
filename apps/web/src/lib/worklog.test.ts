import { describe, expect, it } from 'vitest'
import { splitWorklogDrafts } from './worklog'

describe('splitWorklogDrafts', () => {
  it('splits one raw entry into multiple reviewable facts', () => {
    expect(splitWorklogDrafts('完成SDK教程；排查M2600无点云。调整巨帧后恢复。')).toEqual([
      '完成SDK教程',
      '排查M2600无点云',
      '调整巨帧后恢复',
    ])
  })

  it('removes blank fragments', () => {
    expect(splitWorklogDrafts('会议\n\n 文档整理；')).toEqual(['会议', '文档整理'])
  })
})
