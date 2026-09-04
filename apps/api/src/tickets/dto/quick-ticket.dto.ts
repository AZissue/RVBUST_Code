import { IsEnum, IsOptional, IsString, IsUUID, Length, IsDateString } from 'class-validator';
import { TicketPriority } from '@prisma/client';

export class ParseQuickTicketDto {
  @IsString() @Length(3, 4000) rawText!: string;
}
export class SimilarTicketsDto {
  @IsUUID() organizationId!: string;
  @IsString() @Length(1, 4000) issue!: string;
  @IsOptional() @IsString() @Length(0, 100) cameraModel?: string;
}
export class UpdateQuickTicketDto {
  @IsString() @Length(3, 4000) issue!: string;
  @IsString() @Length(3, 4000) rawText!: string;
  @IsUUID() organizationId!: string;
  @IsUUID() assigneeId!: string;
  @IsEnum(TicketPriority) priority!: TicketPriority;
  @IsDateString() expectedUpdatedAt!: string;
}
export class ConvertWorkItemDto {
  @IsUUID() organizationId!: string;
}
