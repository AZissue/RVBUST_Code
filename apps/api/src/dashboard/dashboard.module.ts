import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module.js';
import { LinkageModule } from '../linkage/linkage.module.js';
import { DashboardController } from './dashboard.controller.js';
import { DashboardService } from './dashboard.service.js';

@Module({ imports: [AuthModule, LinkageModule], controllers: [DashboardController], providers: [DashboardService] })
export class DashboardModule {}

