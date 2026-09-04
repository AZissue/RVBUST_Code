import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module.js';
import { WorkitemsController } from './workitems.controller.js';
import { WorkitemsService } from './workitems.service.js';

@Module({ imports: [AuthModule], controllers: [WorkitemsController], providers: [WorkitemsService] })
export class WorkitemsModule {}
