import { Module } from '@nestjs/common';
import { WorktypesController } from './worktypes.controller.js';
import { WorktypesService } from './worktypes.service.js';

@Module({ controllers: [WorktypesController], providers: [WorktypesService] })
export class WorktypesModule {}
