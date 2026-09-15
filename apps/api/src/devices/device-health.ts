/** 设备健康度：源自借测/维修周转启发式规则（参考设备管理工具 deviceHealth） */
export type DeviceHealth = 'OK' | 'ATTENTION' | 'CHECK';

export const deviceHealthLabels: Record<DeviceHealth, string> = { OK: '正常', ATTENTION: '关注', CHECK: '建议检查' };

/**
 * 规则：累计维修 ≥2 次或累计借测 ≥10 次 → 建议检查；
 * 维修 1 次或借测 ≥6 次 → 关注；否则正常。
 */
export function deviceHealth(loanCount: number, repairCount: number): DeviceHealth {
  if (repairCount >= 2 || loanCount >= 10) return 'CHECK';
  if (repairCount === 1 || loanCount >= 6) return 'ATTENTION';
  return 'OK';
}
