-- DropForeignKey
ALTER TABLE "attachments" DROP CONSTRAINT "attachments_loan_item_id_fkey";

-- DropForeignKey
ALTER TABLE "repair_orders" DROP CONSTRAINT "repair_orders_device_id_fkey";

-- AlterTable
ALTER TABLE "bug_reports" ALTER COLUMN "id" DROP DEFAULT;

-- AlterTable
ALTER TABLE "devices" ADD COLUMN     "asset_no" VARCHAR(120);

-- AlterTable
ALTER TABLE "loan_items" ALTER COLUMN "id" DROP DEFAULT;

-- AlterTable
ALTER TABLE "loan_orders" ALTER COLUMN "id" DROP DEFAULT,
ALTER COLUMN "updated_at" DROP DEFAULT;

-- AlterTable
ALTER TABLE "repair_events" ALTER COLUMN "id" DROP DEFAULT;

-- AlterTable
ALTER TABLE "repair_orders" ALTER COLUMN "id" DROP DEFAULT,
ALTER COLUMN "updated_at" DROP DEFAULT;

-- RenameForeignKey
ALTER TABLE "ai_feature_configs" RENAME CONSTRAINT "ai_feature_provider_fkey" TO "ai_feature_configs_providerId_fkey";

-- AddForeignKey
ALTER TABLE "attachments" ADD CONSTRAINT "attachments_loan_item_id_fkey" FOREIGN KEY ("loan_item_id") REFERENCES "loan_items"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "repair_orders" ADD CONSTRAINT "repair_orders_device_id_fkey" FOREIGN KEY ("device_id") REFERENCES "devices"("id") ON DELETE SET NULL ON UPDATE CASCADE;
