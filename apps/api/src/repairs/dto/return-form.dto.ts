import { IsDateString, IsString, Length } from 'class-validator';

export class ReturnFormDto {
  @IsString() @Length(1, 200) companyName!: string;
  @IsDateString() reportedAt!: string;
  @IsString() @Length(1, 100) reporterName!: string;
  @IsString() @Length(1, 80) reporterPhone!: string;
  @IsString() @Length(1, 120) serialNumber!: string;
  @IsString() @Length(1, 1000) appearance!: string;
  @IsString() @Length(1, 2000) returnAddress!: string;
  @IsString() @Length(0, 100) salesContact!: string;
  @IsString() @Length(0, 100) afterSalesContact!: string;
}
