import { describe, expect, it } from 'vitest';
import { computeCustomerLevel, recentMonthKeys } from './customer-level.js';

const base = { storedLevel: null, levelLocked: false };

describe('computeCustomerLevel', () => {
  it('无工单的新客户默认为 C', () => {
    expect(computeCustomerLevel({ ...base, monthlyTicketCounts: [0, 0, 0] })).toEqual({ level: 'C', source: 'auto' });
  });

  it('当月不超过 10 单保持 C', () => {
    expect(computeCustomerLevel({ ...base, monthlyTicketCounts: [10, 0, 0] })).toEqual({ level: 'C', source: 'auto' });
  });

  it('当月突破 10 单升级为 B', () => {
    expect(computeCustomerLevel({ ...base, monthlyTicketCounts: [11, 0, 0] })).toEqual({ level: 'B', source: 'auto' });
  });

  it('连续三个月每月都突破 10 单升级为 A', () => {
    expect(computeCustomerLevel({ ...base, monthlyTicketCounts: [11, 12, 13] })).toEqual({ level: 'A', source: 'auto' });
  });

  it('仅两个月达标仍为 B', () => {
    expect(computeCustomerLevel({ ...base, monthlyTicketCounts: [11, 11, 3] })).toEqual({ level: 'B', source: 'auto' });
  });

  it('A 未固定时活动量下降会降级回 B/C', () => {
    expect(computeCustomerLevel({ ...base, monthlyTicketCounts: [0, 11, 11] })).toEqual({ level: 'C', source: 'auto' });
  });

  it('手动指定的 S 不受工单量影响', () => {
    expect(computeCustomerLevel({ storedLevel: 'S', levelLocked: false, monthlyTicketCounts: [0, 0, 0] })).toEqual({ level: 'S', source: 'manual' });
  });

  it('固定的 A 活动量下降后仍为 A', () => {
    expect(computeCustomerLevel({ storedLevel: 'A', levelLocked: true, monthlyTicketCounts: [0, 0, 0] })).toEqual({ level: 'A', source: 'locked' });
  });

  it('历史遗留的 D 锁定后按 C 处理', () => {
    expect(computeCustomerLevel({ storedLevel: 'D', levelLocked: true, monthlyTicketCounts: [11, 11, 11] })).toEqual({ level: 'C', source: 'locked' });
  });
});

describe('recentMonthKeys', () => {
  it('跨年返回正确的三个自然月键', () => {
    expect(recentMonthKeys(new Date(2026, 0, 15))).toEqual(['2026-01', '2025-12', '2025-11']);
  });
});
