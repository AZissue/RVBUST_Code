CREATE TABLE "ai_provider_configs" (
  "id" UUID NOT NULL, "provider" VARCHAR(40) NOT NULL, "name" VARCHAR(100) NOT NULL,
  "enabled" BOOLEAN NOT NULL DEFAULT false, "baseUrl" VARCHAR(500) NOT NULL,
  "apiKeyEncrypted" TEXT, "defaultModel" VARCHAR(160) NOT NULL,
  "temperature" DOUBLE PRECISION NOT NULL DEFAULT 0.1, "maxTokens" INTEGER NOT NULL DEFAULT 1024,
  "timeout" INTEGER NOT NULL DEFAULT 30000, "isDefault" BOOLEAN NOT NULL DEFAULT false,
  "omitTemperature" BOOLEAN NOT NULL DEFAULT false, "jsonMode" BOOLEAN NOT NULL DEFAULT true,
  "tokenParameter" VARCHAR(40) NOT NULL DEFAULT 'max_tokens',
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP, "updatedAt" TIMESTAMP(3) NOT NULL,
  CONSTRAINT "ai_provider_configs_pkey" PRIMARY KEY ("id"),
  CONSTRAINT "ai_provider_default_enabled" CHECK (NOT "isDefault" OR "enabled")
);
CREATE UNIQUE INDEX "ai_provider_single_default" ON "ai_provider_configs" ("isDefault") WHERE "isDefault" = true;
CREATE TABLE "ai_feature_configs" (
  "featureKey" VARCHAR(80) NOT NULL, "providerId" UUID, "model" VARCHAR(160),
  "useSystemDefault" BOOLEAN NOT NULL DEFAULT true, "temperature" DOUBLE PRECISION, "maxTokens" INTEGER,
  "updatedAt" TIMESTAMP(3) NOT NULL, CONSTRAINT "ai_feature_configs_pkey" PRIMARY KEY ("featureKey"),
  CONSTRAINT "ai_feature_provider_fkey" FOREIGN KEY ("providerId") REFERENCES "ai_provider_configs"("id") ON DELETE SET NULL ON UPDATE CASCADE
);
CREATE TABLE "ai_usage_logs" (
  "id" UUID NOT NULL, "requestId" UUID NOT NULL, "userId" UUID NOT NULL, "feature" VARCHAR(80) NOT NULL,
  "providerId" UUID, "provider" VARCHAR(40), "model" VARCHAR(160), "success" BOOLEAN NOT NULL,
  "errorType" VARCHAR(60), "latencyMs" INTEGER NOT NULL, "attempts" INTEGER NOT NULL DEFAULT 0,
  "promptTokens" INTEGER, "completionTokens" INTEGER, "totalTokens" INTEGER,
  "createdAt" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT "ai_usage_logs_pkey" PRIMARY KEY ("id")
);
CREATE UNIQUE INDEX "ai_usage_logs_requestId_key" ON "ai_usage_logs"("requestId");
CREATE INDEX "ai_usage_logs_createdAt_idx" ON "ai_usage_logs"("createdAt");
CREATE INDEX "ai_usage_logs_feature_createdAt_idx" ON "ai_usage_logs"("feature", "createdAt");
