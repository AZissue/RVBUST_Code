import { PartialType } from '@nestjs/mapped-types';
import { ArrayMinSize, IsArray, IsDateString, IsOptional, IsString, IsUUID, Length, ValidateNested } from 'class-validator';
import { Type } from 'class-transformer';

export class CreateLoanDto {
  @IsUUID() organizationId!: string;
  @IsOptional() @IsUUID() contactId?: string;
  @IsString() @Length(1, 500) purpose!: string;
  @IsOptional() @IsDateString() loanedAt?: string;
  @IsDateString() dueAt!: string;
  @IsOptional() @IsString() @Length(0, 100) agreementNo?: string;
  @IsOptional() @IsString() @Length(0, 4000) note?: string;
  @IsArray() @ArrayMinSize(1) @IsUUID('4', { each: true }) deviceIds!: string[];
}

export class UpdateLoanDto extends PartialType(CreateLoanDto) {}

export class AssignLoanDto {
  @IsUUID() assigneeId!: string;
}

export class ReturnLoanItemDto {
  @IsUUID() deviceId!: string;
  @IsOptional() @IsString() @Length(0, 2000) conditionNote?: string;
}

export class ReturnLoanDto {
  @IsOptional() @IsArray() @ValidateNested({ each: true }) @Type(() => ReturnLoanItemDto) items?: ReturnLoanItemDto[];
}
