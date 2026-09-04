import { Body, Controller, Delete, Get, Param, Patch, Post } from '@nestjs/common';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import { CreateWorklogDraftsDto, CreateWorklogDto, UpdateWorklogDto } from './dto/worklog.dto.js';
import { WorklogsService } from './worklogs.service.js';

@Roles('admin', 'support', 'employee')
@Controller('worklogs')
export class WorklogsController {
  constructor(private readonly worklogs: WorklogsService) {}
  @Get() list(@CurrentUser() user: AuthUser) { return this.worklogs.list(user); }
  @Post() create(@CurrentUser() user: AuthUser, @Body() dto: CreateWorklogDto) { return this.worklogs.create(user, dto); }
  @Post('drafts') createDrafts(@CurrentUser() user: AuthUser, @Body() dto: CreateWorklogDraftsDto) { return this.worklogs.createDrafts(user, dto); }
  @Post('drafts/:batchId/confirm') confirmDrafts(@CurrentUser() user: AuthUser, @Param('batchId') batchId: string) { return this.worklogs.confirmDrafts(user, batchId); }
  @Patch(':id') update(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: UpdateWorklogDto) { return this.worklogs.update(user, id, dto); }
  @Delete(':id') remove(@CurrentUser() user: AuthUser, @Param('id') id: string) { return this.worklogs.remove(user, id); }
}
