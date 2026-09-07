import { Module } from '@nestjs/common';
import { NotificationsModule } from '../notifications/notifications.module.js';
import { RepairsController } from './repairs.controller.js';
import { RepairsService } from './repairs.service.js';

@Module({ imports: [NotificationsModule], controllers: [RepairsController], providers: [RepairsService], exports: [RepairsService] })
export class RepairsModule {}
