import { PartialType } from '@nestjs/mapped-types';
import { IsBoolean, IsInt, IsOptional, IsString, Length, Matches, Max, Min } from 'class-validator';

export class CreateWorkTypeDto {
  @IsString() @Length(2, 80) @Matches(/^[a-z0-9-]+$/) code!: string;
  @IsString() @Length(1, 100) label!: string;
  @IsOptional() @IsString() @Length(0, 1000) description?: string;
  @IsOptional() @IsBoolean() isActive?: boolean;
  @IsOptional() @IsInt() @Min(0) @Max(10000) sortOrder?: number;
}

export class UpdateWorkTypeDto extends PartialType(CreateWorkTypeDto) {}
