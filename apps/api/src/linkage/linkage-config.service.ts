import { Injectable } from '@nestjs/common';
import type { Prisma } from '@prisma/client';
import { PrismaService } from '../prisma/prisma.service.js';

/** linkage 系统配置项的 SystemSetting key */
export const LINKAGE_SETTING_KEYS = {
  defaultCreate: 'linkage.defaultCreate',
  infoCompleteTimeoutHours: 'linkage.infoCompleteTimeoutHours',
  repairFollowupTimeoutHours: 'linkage.repairFollowupTimeoutHours',
  notifyOnOverdue: 'linkage.notifyOnOverdue',
} as const;

export interface LinkageConfig {
  defaultCreate: { loan: boolean; repair: boolean };
  infoCompleteTimeoutHours: number;
  repairFollowupTimeoutHours: number;
  notifyOnOverdue: boolean;
}

const DEFAULTS: LinkageConfig = {
  defaultCreate: { loan: false, repair: false },
  infoCompleteTimeoutHours: 24,
  repairFollowupTimeoutHours: 48,
  notifyOnOverdue: true,
};

const asRecord = (value: Prisma.JsonValue | null | undefined): Record<string, unknown> =>
  value && typeof value === 'object' && !Array.isArray(value) ? (value as Record<string, unknown>) : {};

const asPositiveInt = (value: unknown, fallback: number): number => {
  const num = Number(value);
  return Number.isFinite(num) && num > 0 ? Math.floor(num) : fallback;
};

/** 读 SystemSetting 中的 linkage 配置，缺 key / 非法值用默认值兜底；cron 与监听器共用 */
@Injectable()
export class LinkageConfigService {
  constructor(private readonly prisma: PrismaService) {}

  async getAll(): Promise<LinkageConfig> {
    const rows = await this.prisma.systemSetting.findMany({ where: { key: { in: Object.values(LINKAGE_SETTING_KEYS) } } });
    const byKey = new Map(rows.map((row) => [row.key, row.value]));
    const raw = asRecord(byKey.get(LINKAGE_SETTING_KEYS.defaultCreate));
    return {
      defaultCreate: { loan: Boolean(raw.loan), repair: Boolean(raw.repair) },
      infoCompleteTimeoutHours: asPositiveInt(byKey.get(LINKAGE_SETTING_KEYS.infoCompleteTimeoutHours), DEFAULTS.infoCompleteTimeoutHours),
      repairFollowupTimeoutHours: asPositiveInt(byKey.get(LINKAGE_SETTING_KEYS.repairFollowupTimeoutHours), DEFAULTS.repairFollowupTimeoutHours),
      notifyOnOverdue: byKey.get(LINKAGE_SETTING_KEYS.notifyOnOverdue) === undefined ? DEFAULTS.notifyOnOverdue : Boolean(byKey.get(LINKAGE_SETTING_KEYS.notifyOnOverdue)),
    };
  }

  /** 供「新建工单默认联动」使用：只读 defaultCreate，缺 key 返回 { loan: false, repair: false } */
  async getDefaultCreate(): Promise<LinkageConfig['defaultCreate']> {
    return (await this.getAll()).defaultCreate;
  }
}
