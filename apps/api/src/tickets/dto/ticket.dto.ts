import { PartialType } from '@nestjs/mapped-types';
import { TicketCategory, TicketPriority } from '@prisma/client';
import { IsArray, IsDateString, IsEnum, IsOptional, IsString, IsUUID, Length } from 'class-validator';

export class CreateTicketDto {
  @IsOptional() @IsString() @Length(1, 20000) rawText?: string;
  @IsOptional() @IsUUID() requestKey?: string;
  @IsUUID() organizationId!: string;
  @IsOptional() @IsUUID() contactId?: string;
  @IsOptional() @IsUUID() deviceId?: string;
  @IsOptional() @IsUUID() projectId?: string;
  @IsOptional() @IsString() @Length(0, 100) cameraModel?: string;
  @IsOptional() @IsString() @Length(0, 120) serialNumber?: string;
  @IsOptional() @IsString() @Length(0, 80) sdkVersion?: string;
  @IsOptional() @IsString() @Length(0, 4000) systemEnvironment?: string;
  @IsEnum(TicketCategory, { message: '问题分类无效' }) category!: TicketCategory;
  @IsString() @Length(3, 240) title!: string;
  @IsString() @Length(3, 20000) description!: string;
  @IsOptional() @IsEnum(TicketPriority) priority?: TicketPriority;
  @IsOptional() @IsUUID() assigneeId?: string;
  @IsOptional() @IsArray() @IsUUID('4', { each: true }) collaboratorIds?: string[];
  @IsOptional() @IsDateString() plannedAt?: string;
}

export class UpdateTicketDto extends PartialType(CreateTicketDto) {}

export class ChangeCreatorDto {
  @IsUUID() createdById!: string;
}
