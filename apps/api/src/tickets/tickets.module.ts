import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module.js';
import { TicketsController } from './tickets.controller.js';
import { TicketsService } from './tickets.service.js';
import { QuickTicketsService } from './quick-tickets.service.js';
import { QUICK_INPUT_PARSER } from './quick-input.parser.js';
import { AIParser } from './ai.parser.js';
import { AIModule } from '../ai/ai.module.js';

@Module({ imports: [AuthModule, AIModule], controllers: [TicketsController], providers: [TicketsService, QuickTicketsService, { provide: QUICK_INPUT_PARSER, useClass: AIParser }], exports: [TicketsService] })
export class TicketsModule {}
