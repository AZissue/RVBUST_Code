import { Body, Controller, Get, Param, Patch, Post } from '@nestjs/common';
import { CurrentUser } from '../auth/current-user.decorator.js';
import { Roles } from '../auth/roles.decorator.js';
import type { AuthUser } from '../auth/auth.types.js';
import { CreateUserDto } from './dto/create-user.dto.js';
import { UpdateUserDto } from './dto/update-user.dto.js';
import { UsersService } from './users.service.js';

@Controller('users')
export class UsersController {
  constructor(private readonly users: UsersService) {}

  @Roles('admin') @Get() list() { return this.users.list(); }
  @Roles('admin', 'support', 'employee') @Get('assignable') assignable() { return this.users.assignable(); }
  @Roles('admin') @Post() create(@Body() dto: CreateUserDto) { return this.users.create(dto); }
  @Roles('admin') @Patch(':id') update(@Param('id') id: string, @Body() dto: UpdateUserDto, @CurrentUser() actor: AuthUser) { return this.users.update(id, dto, actor.id); }
}

