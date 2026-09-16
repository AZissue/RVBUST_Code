-- CreateTable
CREATE TABLE "customer_aliases" (
    "id" UUID NOT NULL,
    "organization_id" UUID NOT NULL,
    "alias" VARCHAR(100) NOT NULL,
    "created_by_id" UUID NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "customer_aliases_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE INDEX "customer_aliases_alias_idx" ON "customer_aliases"("alias");

-- CreateIndex
CREATE UNIQUE INDEX "customer_aliases_organization_id_alias_key" ON "customer_aliases"("organization_id", "alias");

-- AddForeignKey
ALTER TABLE "customer_aliases" ADD CONSTRAINT "customer_aliases_organization_id_fkey" FOREIGN KEY ("organization_id") REFERENCES "customer_organizations"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "customer_aliases" ADD CONSTRAINT "customer_aliases_created_by_id_fkey" FOREIGN KEY ("created_by_id") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
