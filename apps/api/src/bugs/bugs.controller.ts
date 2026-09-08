import { Body, Controller, Get, Param, Patch, Post, Query } from '@nestjs/common';
import type { BugStatus } from '@prisma/client';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import { BugsService } from './bugs.service.js';
import { CreateBugDto, UpdateBugStatusDto } from './dto/bug.dto.js';

@Controller('bugs')
export class BugsController {
  constructor(private readonly bugs: BugsService) {}

  @Get() list(@CurrentUser() user: AuthUser, @Query('status') status?: BugStatus, @Query('mine') mine?: string) {
    return this.bugs.list(user, { status, mine: mine === '1' });
  }

  @Get(':id') get(@Param('id') id: string) { return this.bugs.get(id); }

  @Post() create(@CurrentUser() user: AuthUser, @Body() dto: CreateBugDto) { return this.bugs.create(user, dto); }

  @Roles('admin') @Patch(':id/status') updateStatus(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: UpdateBugStatusDto) {
    return this.bugs.updateStatus(user, id, dto);
  }
}
