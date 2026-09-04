import { Body, Controller, Get, Param, Patch, Post } from '@nestjs/common';
import type { AuthUser } from '../auth/auth.types.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import { CreateNotificationDto } from './dto/create-notification.dto.js';
import { NotificationsService } from './notifications.service.js';

@Controller('notifications')
export class NotificationsController {
  constructor(private readonly notifications: NotificationsService) {}
  @Get() list(@CurrentUser() user: AuthUser) { return this.notifications.list(user.id); }
  @Get('unread-count') count(@CurrentUser() user: AuthUser) { return this.notifications.count(user.id); }
  @Roles('admin', 'support') @Post() create(@Body() dto: CreateNotificationDto) { return this.notifications.create(dto); }
  @Patch(':id/read') read(@CurrentUser() user: AuthUser, @Param('id') id: string) { return this.notifications.read(user.id, id); }
  @Post('read-all') readAll(@CurrentUser() user: AuthUser) { return this.notifications.readAll(user.id); }
}

