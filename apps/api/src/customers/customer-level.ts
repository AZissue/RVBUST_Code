import type { CustomerLevel } from '@prisma/client';

export type EffectiveCustomerLevel = 'S' | 'A' | 'B' | 'C';
export type CustomerLevelSource = 'manual' | 'locked' | 'auto';

export interface CustomerLevelInput {
  /** 数据库存储的手动等级（S 为手动指定；A/B/C/D 在未锁定时作为历史值忽略） */
  storedLevel: CustomerLevel | null;
  /** 手动固定后不再随工单量升降 */
  levelLocked: boolean;
  /** 近三个自然月的工单数（不含回收站）：[当月, 上月, 上上月] */
  monthlyTicketCounts: [number, number, number];
}

export interface CustomerLevelResult {
  level: EffectiveCustomerLevel;
  source: CustomerLevelSource;
}

/**
 * 客户分级规则：
 * - S：大客户/长期复购，只能手动指定；
 * - A：潜在大客户，连续 3 个自然月每月工单都突破 10 单；支持手动固定，固定后不再降级；
 * - B：当月工单突破 10 单；
 * - C：默认（新客户/售前咨询为主，单月不超过 10 单）。
 * 未锁定的 A/B/C 随工单量动态升降；历史遗留的 D 按 C 处理。
 */
export function computeCustomerLevel({ storedLevel, levelLocked, monthlyTicketCounts }: CustomerLevelInput): CustomerLevelResult {
  if (storedLevel === 'S') return { level: 'S', source: 'manual' };
  if (levelLocked && storedLevel) {
    return { level: storedLevel === 'D' ? 'C' : storedLevel, source: 'locked' };
  }
  const [current, previous, beforePrevious] = monthlyTicketCounts;
  if (current > 10 && previous > 10 && beforePrevious > 10) return { level: 'A', source: 'auto' };
  if (current > 10) return { level: 'B', source: 'auto' };
  return { level: 'C', source: 'auto' };
}

/** 返回 [当月, 上月, 上上月] 的 'YYYY-MM' 键（本地时区） */
export function recentMonthKeys(now: Date): [string, string, string] {
  const key = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  return [key(now), key(new Date(now.getFullYear(), now.getMonth() - 1, 1)), key(new Date(now.getFullYear(), now.getMonth() - 2, 1))];
}
