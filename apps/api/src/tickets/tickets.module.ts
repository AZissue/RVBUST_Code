import { Module } from '@nestjs/common';
import { AuthModule } from '../auth/auth.module.js';
import { TicketsController } from './tickets.controller.js';
import { TicketsService } from './tickets.service.js';
import { QuickTicketsService } from './quick-tickets.service.js';
import { QUICK_INPUT_PARSER, RuleBasedParser } from './quick-input.parser.js';

@Module({ imports: [AuthModule], controllers: [TicketsController], providers: [TicketsService, QuickTicketsService, { provide: QUICK_INPUT_PARSER, useClass: RuleBasedParser }], exports: [TicketsService] })
export class TicketsModule {}
