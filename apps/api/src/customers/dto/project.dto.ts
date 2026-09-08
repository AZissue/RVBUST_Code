import { PartialType } from '@nestjs/mapped-types';
import { ProjectStatus } from '@prisma/client';
import { IsEnum, IsOptional, IsString, Length } from 'class-validator';

export class CreateProjectDto {
  @IsString() @Length(1, 200) name!: string;
  @IsOptional() @IsString() @Length(0, 4000) application?: string;
  @IsOptional() @IsEnum(ProjectStatus) status?: ProjectStatus;
  @IsOptional() @IsString() @Length(0, 4000) notes?: string;
}

export class UpdateProjectDto extends PartialType(CreateProjectDto) {}

