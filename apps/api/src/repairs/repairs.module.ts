import { Module } from '@nestjs/common';
import { NotificationsModule } from '../notifications/notifications.module.js';
import { RepairsController } from './repairs.controller.js';
import { RepairsExcelService } from './repairs-excel.service.js';
import { RepairsService } from './repairs.service.js';

@Module({ imports: [NotificationsModule], controllers: [RepairsController], providers: [RepairsService, RepairsExcelService], exports: [RepairsService] })
export class RepairsModule {}
