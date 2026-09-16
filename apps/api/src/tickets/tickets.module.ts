import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module.js';
import { TicketsController } from './tickets.controller.js';
import { TicketsService } from './tickets.service.js';
import { TicketsExcelService } from './tickets-excel.service.js';
import { QuickTicketsService } from './quick-tickets.service.js';
import { QUICK_INPUT_PARSER, RuleBasedParser } from './quick-input.parser.js';
import { LinkageModule } from '../linkage/linkage.module.js';
import { NotificationsModule } from '../notifications/notifications.module.js';

@Module({ imports: [AuthModule, NotificationsModule, LinkageModule], controllers: [TicketsController], providers: [TicketsService, QuickTicketsService, TicketsExcelService, { provide: QUICK_INPUT_PARSER, useClass: RuleBasedParser }], exports: [TicketsService] })
export class TicketsModule {}
