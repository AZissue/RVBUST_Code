import { Body, Controller, Delete, Get, Param, Patch, Post, Query } from '@nestjs/common';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import { CreateWorkItemDto, UpdateWorkItemDto } from './dto/work-item.dto.js';
import { WorkitemsService } from './workitems.service.js';

@Roles('admin', 'support', 'employee')
@Controller('work-items')
export class WorkitemsController {
  constructor(private readonly workitems: WorkitemsService) {}
  @Get() list(@CurrentUser() user: AuthUser, @Query('mine') mine?: string) { return this.workitems.list(user, mine === '1'); }
  @Get(':id') get(@CurrentUser() user: AuthUser, @Param('id') id: string) { return this.workitems.get(user, id); }
  @Post() create(@CurrentUser() user: AuthUser, @Body() dto: CreateWorkItemDto) { return this.workitems.create(user, dto); }
  @Patch(':id') update(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: UpdateWorkItemDto) { return this.workitems.update(user, id, dto); }
  @Delete(':id') remove(@CurrentUser() user: AuthUser, @Param('id') id: string) { return this.workitems.remove(user, id); }
}
