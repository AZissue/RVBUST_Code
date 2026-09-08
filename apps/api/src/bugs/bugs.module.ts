import { Module } from '@nestjs/common';
import { NotificationsModule } from '../notifications/notifications.module.js';
import { BugsController } from './bugs.controller.js';
import { BugsService } from './bugs.service.js';

@Module({ imports: [NotificationsModule], controllers: [BugsController], providers: [BugsService], exports: [BugsService] })
export class BugsModule {}
