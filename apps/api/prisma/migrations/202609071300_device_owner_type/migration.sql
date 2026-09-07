-- 设备资产归属：公司样机可挂靠客户（借测）或无所属（公司库存）；客户资产通过返修挂靠
CREATE TYPE "DeviceOwnerType" AS ENUM ('COMPANY', 'CUSTOMER');

ALTER TABLE "devices" ADD COLUMN "owner_type" "DeviceOwnerType" NOT NULL DEFAULT 'CUSTOMER';

-- organization_id 允许为空（公司样机在公司库存时无所属客户）
ALTER TABLE "devices" ALTER COLUMN "organization_id" DROP NOT NULL;
ALTER TABLE "devices" DROP CONSTRAINT IF EXISTS "devices_organization_id_fkey";
ALTER TABLE "devices" ADD CONSTRAINT "devices_organization_id_fkey" FOREIGN KEY ("organization_id") REFERENCES "customer_organizations"("id") ON DELETE SET NULL ON UPDATE CASCADE;
