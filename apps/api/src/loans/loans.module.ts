import { Module } from '@nestjs/common';
import { NotificationsModule } from '../notifications/notifications.module.js';
import { LoansController } from './loans.controller.js';
import { LoansService } from './loans.service.js';

@Module({ imports: [NotificationsModule], controllers: [LoansController], providers: [LoansService], exports: [LoansService] })
export class LoansModule {}
