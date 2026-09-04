import { Body, Controller, Delete, Get, Param, Patch, Post, Query } from '@nestjs/common';
import { TicketStatus } from '@prisma/client';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import { ChangeStatusDto } from './dto/change-status.dto.js';
import { CreateTicketEventDto } from './dto/ticket-event.dto.js';
import { CreateTicketDto, UpdateTicketDto } from './dto/ticket.dto.js';
import { TicketsService } from './tickets.service.js';
import { QuickTicketsService } from './quick-tickets.service.js';
import { ParseQuickTicketDto, SimilarTicketsDto, UpdateQuickTicketDto, ConvertWorkItemDto } from './dto/quick-ticket.dto.js';

@Controller('tickets')
export class TicketsController {
  constructor(private readonly tickets: TicketsService, private readonly quick: QuickTicketsService) {}
  @Get() list(@CurrentUser() user: AuthUser, @Query('search') search?: string, @Query('status') status?: TicketStatus, @Query('mine') mine?: string) { return this.tickets.list(user, search, status, mine === '1'); }
  @Roles('admin', 'support', 'employee') @Post('quick/parse') parse(@CurrentUser() user: AuthUser, @Body() dto: ParseQuickTicketDto) { return this.quick.parse(user, dto.rawText); }
  @Roles('admin', 'support', 'employee') @Post('quick/similar') similar(@CurrentUser() user: AuthUser, @Body() dto: SimilarTicketsDto) { return this.quick.similar(user, dto); }
  @Roles('admin', 'support', 'employee') @Post(':id/quick-update') quickUpdate(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: UpdateQuickTicketDto) { return this.quick.update(user, id, dto); }
  @Roles('admin', 'support', 'employee') @Post('from-work-item/:id') convert(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: ConvertWorkItemDto) { return this.tickets.convertWorkItem(user, id, dto.organizationId); }
  @Get(':id') get(@CurrentUser() user: AuthUser, @Param('id') id: string) { return this.tickets.get(user, id); }
  @Post() create(@CurrentUser() user: AuthUser, @Body() dto: CreateTicketDto) { return this.tickets.create(user, dto); }
  @Roles('admin', 'support', 'employee') @Patch(':id') update(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: UpdateTicketDto) { return this.tickets.update(user, id, dto); }
  @Roles('admin', 'support', 'employee') @Post(':id/status') changeStatus(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: ChangeStatusDto) { return this.tickets.changeStatus(user, id, dto); }
  @Post(':id/events') addEvent(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: CreateTicketEventDto) { return this.tickets.addEvent(user, id, dto); }
  @Roles('admin') @Delete(':id') remove(@Param('id') id: string) { return this.tickets.remove(id); }
}
