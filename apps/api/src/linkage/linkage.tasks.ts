import { Injectable, Logger } from '@nestjs/common';
import { Cron } from '@nestjs/schedule';
import { LoanStatus, RepairStatus } from '@prisma/client';
import { NOTIFICATION_TYPES } from '../common/notification-types.js';
import { PrismaService } from '../prisma/prisma.service.js';
import { LinkageConfigService } from './linkage-config.service.js';
import { LinkageNotifyService } from './linkage-notify.service.js';

const HOUR_MS = 60 * 60 * 1000;
/** 同一单据同一时机的超时提醒，去重窗口（近 N 小时内已发过则跳过） */
const REMIND_DEDUPE_HOURS = 20;

/** 联动超时提醒定时任务：借测信息完善超时、维修无跟进超时（每小时整点跑一次） */
@Injectable()
export class LinkageTasks {
  private readonly logger = new Logger(LinkageTasks.name);

  constructor(
    private readonly prisma: PrismaService,
    private readonly config: LinkageConfigService,
    private readonly linkageNotify: LinkageNotifyService,
  ) {}

  @Cron('0 * * * *')
  async checkTimeouts() {
    await Promise.all([this.checkLoanInfoTimeout(), this.checkRepairFollowupTimeout()]);
  }

  /** 借测信息完善超时：排队中且未完善信息、创建超过阈值小时，提醒工单负责人（无负责人退化为创建人） */
  private async checkLoanInfoTimeout() {
    const cfg = await this.config.getAll();
    const deadline = new Date(Date.now() - cfg.infoCompleteTimeoutHours * HOUR_MS);
    const loans = await this.prisma.loanOrder.findMany({
      where: { status: LoanStatus.QUEUED, infoComplete: false, deletedAt: null, createdAt: { lt: deadline } },
      select: { id: true, loanNo: true, ticketId: true },
    });
    for (const loan of loans) {
      try {
        if (!loan.ticketId) continue;
        const ownerId = await this.linkageNotify.ticketOwnerId(loan.ticketId);
        if (!ownerId) continue;
        const dedupeKeyPrefix = `link-loan-info-timeout:${loan.id}:${ownerId}`;
        if (await this.linkageNotify.hasNotifiedSince(ownerId, NOTIFICATION_TYPES.LINK_INFO_TIMEOUT, dedupeKeyPrefix, new Date(Date.now() - REMIND_DEDUPE_HOURS * HOUR_MS))) continue;
        await this.linkageNotify.notifyUnreadOnce({
          recipientId: ownerId, ticketId: loan.ticketId, type: NOTIFICATION_TYPES.LINK_INFO_TIMEOUT, severity: 'WARNING',
          title: '借测单信息待完善', body: `借测单 ${loan.loanNo} 信息超过 ${cfg.infoCompleteTimeoutHours} 小时未完善，请尽快补全并评分（/loans/${loan.id}）。`,
          dedupeKey: dedupeKeyPrefix,
        });
      } catch (error) {
        this.logger.error(`借测信息超时提醒失败（${loan.loanNo}）`, error instanceof Error ? error.stack : String(error));
      }
    }
  }

  /** 维修无跟进超时：受理/诊断/维修中且最新 RepairEvent 或 FollowUp 创建时间超过阈值小时；通知维修单负责人，无负责人通知所有 admin */
  private async checkRepairFollowupTimeout() {
    const cfg = await this.config.getAll();
    const deadline = new Date(Date.now() - cfg.repairFollowupTimeoutHours * HOUR_MS);
    const repairs = await this.prisma.repairOrder.findMany({
      where: { status: { in: [RepairStatus.RECEIVED, RepairStatus.DIAGNOSING, RepairStatus.REPAIRING] }, deletedAt: null },
      select: { id: true, repairNo: true, assigneeId: true, ticketId: true, createdAt: true },
    });
    for (const repair of repairs) {
      try {
        const [latestEvent, latestFollowUp] = await Promise.all([
          this.prisma.repairEvent.findFirst({ where: { repairOrderId: repair.id }, orderBy: { createdAt: 'desc' }, select: { createdAt: true } }),
          this.prisma.followUp.findFirst({ where: { repairOrderId: repair.id }, orderBy: { createdAt: 'desc' }, select: { createdAt: true } }),
        ]);
        const lastActivity = [latestEvent?.createdAt, latestFollowUp?.createdAt, repair.createdAt]
          .filter((date): date is Date => Boolean(date))
          .reduce((max, date) => (date > max ? date : max), new Date(0));
        if (lastActivity >= deadline) continue;
        const recipients = repair.assigneeId ? [repair.assigneeId] : await this.linkageNotify.adminIds();
        for (const recipientId of recipients) {
          const dedupeKeyPrefix = `link-repair-no-followup:${repair.id}:${recipientId}`;
          if (await this.linkageNotify.hasNotifiedSince(recipientId, NOTIFICATION_TYPES.LINK_REPAIR_NO_FOLLOWUP, dedupeKeyPrefix, new Date(Date.now() - REMIND_DEDUPE_HOURS * HOUR_MS))) continue;
          await this.linkageNotify.notifyUnreadOnce({
            recipientId, ticketId: repair.ticketId, type: NOTIFICATION_TYPES.LINK_REPAIR_NO_FOLLOWUP, severity: 'WARNING',
            title: '维修单长时间无跟进', body: `维修单 ${repair.repairNo} 超过 ${cfg.repairFollowupTimeoutHours} 小时无跟进，请及时更新进展（/repairs，单号 ${repair.repairNo}）。`,
            dedupeKey: dedupeKeyPrefix,
          });
        }
      } catch (error) {
        this.logger.error(`维修跟进超时提醒失败（${repair.repairNo}）`, error instanceof Error ? error.stack : String(error));
      }
    }
  }
}
