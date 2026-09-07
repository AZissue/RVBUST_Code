import { IsIn, IsOptional, IsString, Length } from 'class-validator';

export class ListUsersDto {
  @IsOptional() @IsIn(['PENDING', 'ACTIVE', 'DISABLED']) status?: 'PENDING' | 'ACTIVE' | 'DISABLED';
  @IsOptional() @IsIn(['admin', 'support', 'employee', 'customer']) role?: string;
  @IsOptional() @IsString() @Length(0, 100) department?: string;
  @IsOptional() @IsString() @Length(0, 60) keyword?: string;
}
