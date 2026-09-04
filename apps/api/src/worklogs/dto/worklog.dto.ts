import { PartialType } from '@nestjs/mapped-types';
import { WorklogSource, WorklogStatus } from '@prisma/client';
import { ArrayMaxSize, ArrayMinSize, IsArray, IsDateString, IsEnum, IsInt, IsOptional, IsString, IsUUID, Length, Max, Min } from 'class-validator';

export class CreateWorklogDto {
  @IsDateString() occurredAt!: string;
  @IsUUID() workTypeId!: string;
  @IsOptional() @IsUUID() organizationId?: string;
  @IsOptional() @IsUUID() ticketId?: string;
  @IsOptional() @IsUUID() workItemId?: string;
  @IsOptional() @IsUUID() projectId?: string;
  @IsString() @Length(2, 240) summary!: string;
  @IsOptional() @IsString() @Length(0, 10000) problem?: string;
  @IsOptional() @IsString() @Length(0, 10000) actions?: string;
  @IsOptional() @IsString() @Length(0, 10000) result?: string;
  @IsOptional() @IsString() @Length(0, 10000) nextStep?: string;
  @IsOptional() @IsInt() @Min(0) @Max(1440) durationMinutes?: number;
  @IsOptional() @IsString() @Length(0, 20000) rawText?: string;
  @IsOptional() @IsEnum(WorklogSource) source?: WorklogSource;
  @IsOptional() @IsEnum(WorklogStatus) status?: WorklogStatus;
}

export class UpdateWorklogDto extends PartialType(CreateWorklogDto) {}

export class CreateWorklogDraftsDto {
  @IsString() @Length(2, 20000) rawText!: string;
  @IsDateString() occurredAt!: string;
  @IsUUID() workTypeId!: string;
  @IsArray() @ArrayMinSize(1) @ArrayMaxSize(20) @IsString({ each: true }) summaries!: string[];
}
