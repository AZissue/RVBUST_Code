import { PartialType } from '@nestjs/mapped-types';
import { IsArray, IsOptional, IsString, IsUUID, Length } from 'class-validator';

export class CreateTeamDto {
  @IsString() @Length(2, 100) name!: string;
  @IsOptional() @IsString() @Length(0, 1000) description?: string;
  @IsOptional() @IsArray() @IsUUID('4', { each: true }) memberIds?: string[];
}

export class UpdateTeamDto extends PartialType(CreateTeamDto) {}

