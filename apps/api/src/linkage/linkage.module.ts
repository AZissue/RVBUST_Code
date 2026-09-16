import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module.js';
import { LoansModule } from '../loans/loans.module.js';
import { NotificationsModule } from '../notifications/notifications.module.js';
import { RepairsModule } from '../repairs/repairs.module.js';
import { LinkageConfigController } from './linkage-config.controller.js';
import { LinkageConfigService } from './linkage-config.service.js';
import { LinkageListener } from './linkage.listener.js';
import { LinkageNotifyService } from './linkage-notify.service.js';
import { LinkageService } from './linkage.service.js';
import { LinkageTasks } from './linkage.tasks.js';

/** 工单 ↔ 借测/维修联动编排：复用 loans/repairs 的建单逻辑，loans/repairs 模块互相不感知；监听器统一消费领域事件做双向时间线同步与联动通知 */
@Module({
  imports: [AuthModule, LoansModule, RepairsModule, NotificationsModule],
  controllers: [LinkageConfigController],
  providers: [LinkageService, LinkageListener, LinkageConfigService, LinkageNotifyService, LinkageTasks],
  exports: [LinkageService, LinkageConfigService],
})
export class LinkageModule {}
