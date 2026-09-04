import { IsBoolean, IsIn, IsInt, IsNumber, IsOptional, IsString, IsUUID, Length, Matches, Max, Min } from 'class-validator';
import { PROVIDERS } from './ai.types.js';
import { PickType } from '@nestjs/mapped-types';

export class ProviderDto {
  @IsIn(PROVIDERS) provider: string;
  @IsString() @Length(1, 100) @Matches(/\S/) name: string;
  @IsBoolean() enabled: boolean;
  @IsString() @Length(8, 500) baseUrl: string;
  @IsOptional() @IsString() @Length(50, 5000) @Matches(/^v1\.[A-Za-z0-9+/=]+\.[A-Za-z0-9+/=]+\.[A-Za-z0-9+/=]+$/) sealedApiKey?: string;
  @IsString() @Length(1, 160) @Matches(/^[a-zA-Z0-9][a-zA-Z0-9_./:@+-]*$/) defaultModel: string;
  @IsNumber() @Min(0) @Max(2) temperature: number;
  @IsInt() @Min(64) @Max(32768) maxTokens: number;
  @IsInt() @Min(1000) @Max(60000) timeout: number;
  @IsBoolean() isDefault: boolean;
  @IsBoolean() omitTemperature: boolean;
  @IsBoolean() jsonMode: boolean;
  @IsIn(['max_tokens', 'max_completion_tokens']) tokenParameter: string;
}
export class FeatureDto {
  @IsBoolean() useSystemDefault: boolean;
  @IsOptional() @IsUUID() providerId?: string | null;
  @IsOptional() @IsString() @Length(1, 160) @Matches(/^[a-zA-Z0-9][a-zA-Z0-9_./:@+-]*$/) model?: string | null;
  @IsOptional() @IsNumber() @Min(0) @Max(2) temperature?: number | null;
  @IsOptional() @IsInt() @Min(64) @Max(32768) maxTokens?: number | null;
}

export class DiscoverModelsDto extends PickType(ProviderDto, ['provider', 'baseUrl', 'sealedApiKey', 'timeout'] as const) {
  @IsOptional() @IsUUID() providerId?: string;
}
