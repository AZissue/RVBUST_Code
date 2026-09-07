import { Body, Controller, Get, Param, Patch, Post, Query } from '@nestjs/common';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import type { AuthUser } from '../auth/auth.types.js';
import { CreateUserDto } from './dto/create-user.dto.js';
import { ListUsersDto } from './dto/list-users.dto.js';
import { ResetPasswordDto } from './dto/reset-password.dto.js';
import { UpdateUserDto } from './dto/update-user.dto.js';
import { UsersService } from './users.service.js';

@Controller('users')
export class UsersController {
  constructor(private readonly users: UsersService) {}

  @Roles('admin') @Get() list(@Query() query: ListUsersDto) { return this.users.list(query); }
  @Roles('admin', 'support', 'employee') @Get('assignable') assignable() { return this.users.assignable(); }
  @Roles('admin') @Post() create(@Body() dto: CreateUserDto) { return this.users.create(dto); }
  @Roles('admin') @Patch(':id') update(@Param('id') id: string, @Body() dto: UpdateUserDto, @CurrentUser() actor: AuthUser) { return this.users.update(id, dto, actor.id); }
  @Roles('admin') @Post(':id/approve') approve(@Param('id') id: string) { return this.users.approve(id); }
  @Roles('admin') @Post(':id/reject') reject(@Param('id') id: string) { return this.users.reject(id); }
  @Roles('admin') @Post(':id/disable') disable(@Param('id') id: string, @CurrentUser() actor: AuthUser) { return this.users.disable(id, actor.id); }
  @Roles('admin') @Post(':id/enable') enable(@Param('id') id: string) { return this.users.enable(id); }
  @Roles('admin') @Post(':id/reset-password') resetPassword(@Param('id') id: string, @Body() dto: ResetPasswordDto) { return this.users.resetPassword(id, dto.password); }
}
