import { TicketStatus } from '@prisma/client';
import { IsEnum, IsOptional, IsString, Length } from 'class-validator';

export class ChangeStatusDto {
  @IsEnum(TicketStatus) status!: TicketStatus;
  @IsOptional() @IsString() @Length(0, 1000) reason?: string;
}

