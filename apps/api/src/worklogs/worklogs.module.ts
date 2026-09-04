import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module.js';
import { WorklogsController } from './worklogs.controller.js';
import { WorklogsService } from './worklogs.service.js';

@Module({ imports: [AuthModule], controllers: [WorklogsController], providers: [WorklogsService] })
export class WorklogsModule {}

