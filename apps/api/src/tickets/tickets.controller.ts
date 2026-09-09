import { BadRequestException, Body, Controller, Delete, Get, Param, Patch, Post, Query, Res, UploadedFile, UseInterceptors } from '@nestjs/common';
import { FileInterceptor } from '@nestjs/platform-express';
import { memoryStorage } from 'multer';
import type { Response } from 'express';
import { TicketStatus } from '@prisma/client';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import { ChangeStatusDto } from './dto/change-status.dto.js';
import { CreateTicketEventDto } from './dto/ticket-event.dto.js';
import { CreateTicketDto, UpdateTicketDto, ChangeCreatorDto } from './dto/ticket.dto.js';
import { TicketsService } from './tickets.service.js';
import { TicketsExcelService } from './tickets-excel.service.js';
import { QuickTicketsService } from './quick-tickets.service.js';
import { ParseQuickTicketDto, SimilarTicketsDto, UpdateQuickTicketDto, ConvertWorkItemDto } from './dto/quick-ticket.dto.js';

const importUploadOptions = {
  storage: memoryStorage(),
  limits: { fileSize: 2 * 1024 * 1024, files: 1 },
  fileFilter: (_request: unknown, file: Express.Multer.File, callback: (error: Error | null, accept: boolean) => void) => {
    const ok = file.mimetype === 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet' || file.originalname.toLowerCase().endsWith('.xlsx');
    callback(ok ? null : new BadRequestException('仅支持 xlsx 文件'), ok);
  },
};

@Controller('tickets')
export class TicketsController {
  constructor(private readonly tickets: TicketsService, private readonly quick: QuickTicketsService, private readonly excel: TicketsExcelService) {}
  @Get() list(@CurrentUser() user: AuthUser, @Query('search') search?: string, @Query('status') statusRaw?: string, @Query('mine') mine?: string, @Query('page') pageRaw?: string, @Query('all') all?: string) {
    const statuses = statusRaw ? statusRaw.split(',').filter(Boolean) : [];
    if (statuses.some((item) => !Object.values(TicketStatus).includes(item as TicketStatus))) throw new BadRequestException('工单状态无效');
    // all=1 保持数组返回，供引用数据下拉（如工作记录关联工单）使用；默认分页返回 { items, total, page, pageSize, byStatus }
    if (all === '1') return this.tickets.listAll(user, search, statuses as TicketStatus[], mine === '1');
    const page = Math.max(1, Number.parseInt(pageRaw ?? '1', 10) || 1);
    return this.tickets.list(user, search, statuses as TicketStatus[], mine === '1', page);
  }
  @Roles('admin', 'support', 'employee') @Post('quick/parse') parse(@CurrentUser() user: AuthUser, @Body() dto: ParseQuickTicketDto) { return this.quick.parse(user, dto.rawText); }
  @Roles('admin', 'support', 'employee') @Post('quick/similar') similar(@CurrentUser() user: AuthUser, @Body() dto: SimilarTicketsDto) { return this.quick.similar(user, dto); }
  @Roles('admin', 'support', 'employee') @Post(':id/quick-update') quickUpdate(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: UpdateQuickTicketDto) { return this.quick.update(user, id, dto); }
  @Roles('admin', 'support', 'employee') @Post('from-work-item/:id') convert(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: ConvertWorkItemDto) { return this.tickets.convertWorkItem(user, id, dto.organizationId); }
  @Roles('admin', 'support', 'employee') @Get('import-template') async importTemplate(@Res() response: Response) {
    const buffer = await this.excel.buildTemplateBuffer();
    response.setHeader('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet');
    response.setHeader('Content-Disposition', `attachment; filename*=UTF-8''${encodeURIComponent('工单导入模板.xlsx')}`);
    return response.send(buffer);
  }
  @Roles('admin', 'support', 'employee') @Post('import') @UseInterceptors(FileInterceptor('file', importUploadOptions))
  importTickets(@CurrentUser() user: AuthUser, @UploadedFile() file: Express.Multer.File) {
    if (!file) throw new BadRequestException('请选择 xlsx 文件');
    return this.excel.importBuffer(user, file.buffer);
  }
  @Get(':id') get(@CurrentUser() user: AuthUser, @Param('id') id: string) { return this.tickets.get(user, id); }
  @Post() create(@CurrentUser() user: AuthUser, @Body() dto: CreateTicketDto) { return this.tickets.create(user, dto); }
  @Roles('admin', 'support', 'employee') @Patch(':id') update(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: UpdateTicketDto) { return this.tickets.update(user, id, dto); }
  @Roles('admin') @Post(':id/created-by') changeCreator(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: ChangeCreatorDto) { return this.tickets.changeCreator(user, id, dto); }
  @Roles('admin', 'support', 'employee') @Post(':id/status') changeStatus(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: ChangeStatusDto) { return this.tickets.changeStatus(user, id, dto); }
  @Post(':id/events') addEvent(@CurrentUser() user: AuthUser, @Param('id') id: string, @Body() dto: CreateTicketEventDto) { return this.tickets.addEvent(user, id, dto); }
  @Roles('admin') @Delete(':id') remove(@Param('id') id: string) { return this.tickets.remove(id); }
}
