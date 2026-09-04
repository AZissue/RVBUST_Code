import { Body, Controller, Delete, Get, Header, Param, ParseUUIDPipe, Post, Put } from '@nestjs/common';
import { Roles } from '../auth/roles.decorator.js';
import { CurrentUser } from '../auth/current-user.decorator.js';
import type { AuthUser } from '../auth/auth.types.js';
import { AIService } from './ai.service.js';
import { FeatureDto, ProviderDto } from './ai.dto.js';

@Roles('admin')
@Controller('ai')
export class AIController {
  constructor(private readonly ai: AIService) {}
  @Get('key-exchange') @Header('Cache-Control', 'no-store') keyExchange() { return this.ai.keyExchange(); }
  @Get('providers') @Header('Cache-Control', 'no-store') providers() { return this.ai.providers(); }
  @Post('providers') create(@Body() dto: ProviderDto) { return this.ai.saveProvider(dto); }
  @Put('providers/:id') update(@Param('id', ParseUUIDPipe) id: string, @Body() dto: ProviderDto) { return this.ai.updateProvider(id, dto); }
  @Delete('providers/:id') remove(@Param('id', ParseUUIDPipe) id: string) { return this.ai.deleteProvider(id); }
  @Post('providers/:id/test') test(@Param('id', ParseUUIDPipe) id: string, @CurrentUser() user: AuthUser) { return this.ai.testProvider(id, user.id); }
  @Post('providers/:id/models') models(@Param('id', ParseUUIDPipe) id: string, @CurrentUser() user: AuthUser) { return this.ai.models(id, user.id); }
  @Get('features') features() { return this.ai.features(); }
  @Put('features/:key') feature(@Param('key') key: string, @Body() dto: FeatureDto) { return this.ai.saveFeature(key, dto); }
  @Get('usage') @Header('Cache-Control', 'no-store') usage() { return this.ai.usage(); }
}
