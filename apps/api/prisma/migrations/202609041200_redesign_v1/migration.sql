-- Redesign V1: 用户体系（注册审批）、设备生命周期、借测、返修、客户 360
CREATE TYPE "UserStatus" AS ENUM ('PENDING', 'ACTIVE', 'DISABLED');
CREATE TYPE "DeviceStatus" AS ENUM ('IN_STOCK', 'LOANED', 'REPAIRING', 'RETIRED');
CREATE TYPE "LoanStatus" AS ENUM ('ONGOING', 'OVERDUE', 'RETURNED', 'CANCELLED');
CREATE TYPE "RepairStatus" AS ENUM ('RECEIVED', 'DIAGNOSING', 'REPAIRING', 'SHIPPED', 'CLOSED');

-- users: is_active -> status, + department
ALTER TABLE "users" ADD COLUMN "status" "UserStatus" NOT NULL DEFAULT 'PENDING';
UPDATE "users" SET "status" = 'ACTIVE' WHERE "is_active" = true;
UPDATE "users" SET "status" = 'DISABLED' WHERE "is_active" = false;
ALTER TABLE "users" DROP COLUMN "is_active";
ALTER TABLE "users" ADD COLUMN "department" VARCHAR(100);

-- customer_organizations: profile 扩展
ALTER TABLE "customer_organizations" ADD COLUMN "website_url" VARCHAR(500);
ALTER TABLE "customer_organizations" ADD COLUMN "wiki_ref" VARCHAR(500);
ALTER TABLE "customer_organizations" ADD COLUMN "background" TEXT;
ALTER TABLE "customer_organizations" ADD COLUMN "application_scenarios" TEXT;
ALTER TABLE "customer_organizations" ADD COLUMN "project_needs" TEXT;

-- devices: 生命周期状态与保修
ALTER TABLE "devices" ADD COLUMN "status" "DeviceStatus" NOT NULL DEFAULT 'IN_STOCK';
ALTER TABLE "devices" ADD COLUMN "purchase_date" DATE;
ALTER TABLE "devices" ADD COLUMN "warranty_until" DATE;

-- loan_orders / loan_items
CREATE TABLE "loan_orders" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "loan_no" VARCHAR(32) NOT NULL,
    "organization_id" UUID NOT NULL,
    "contact_id" UUID,
    "assignee_id" UUID,
    "purpose" VARCHAR(500) NOT NULL,
    "status" "LoanStatus" NOT NULL DEFAULT 'ONGOING',
    "loaned_at" DATE NOT NULL,
    "due_at" DATE NOT NULL,
    "returned_at" TIMESTAMP(3),
    "agreement_no" VARCHAR(100),
    "note" TEXT,
    "created_by_id" UUID NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "loan_orders_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "loan_orders_loan_no_key" UNIQUE ("loan_no")
);
CREATE TABLE "loan_items" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "loan_order_id" UUID NOT NULL,
    "device_id" UUID NOT NULL,
    "returned_at" TIMESTAMP(3),
    "condition_note" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "loan_items_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "loan_items_loan_order_id_device_id_key" UNIQUE ("loan_order_id", "device_id")
);
ALTER TABLE "loan_orders" ADD CONSTRAINT "loan_orders_organization_id_fkey" FOREIGN KEY ("organization_id") REFERENCES "customer_organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "loan_orders" ADD CONSTRAINT "loan_orders_contact_id_fkey" FOREIGN KEY ("contact_id") REFERENCES "contacts"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "loan_orders" ADD CONSTRAINT "loan_orders_assignee_id_fkey" FOREIGN KEY ("assignee_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "loan_items" ADD CONSTRAINT "loan_items_loan_order_id_fkey" FOREIGN KEY ("loan_order_id") REFERENCES "loan_orders"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "loan_items" ADD CONSTRAINT "loan_items_device_id_fkey" FOREIGN KEY ("device_id") REFERENCES "devices"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
CREATE INDEX "loan_orders_organization_id_idx" ON "loan_orders"("organization_id");
CREATE INDEX "loan_orders_assignee_id_status_idx" ON "loan_orders"("assignee_id", "status");
CREATE INDEX "loan_orders_status_due_at_idx" ON "loan_orders"("status", "due_at");
CREATE INDEX "loan_items_device_id_idx" ON "loan_items"("device_id");

-- repair_orders / repair_events
CREATE TABLE "repair_orders" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "repair_no" VARCHAR(32) NOT NULL,
    "device_id" UUID NOT NULL,
    "organization_id" UUID NOT NULL,
    "contact_id" UUID,
    "assignee_id" UUID,
    "symptom" VARCHAR(1000) NOT NULL,
    "fault_cause" TEXT,
    "status" "RepairStatus" NOT NULL DEFAULT 'RECEIVED',
    "in_warranty" BOOLEAN,
    "received_at" DATE NOT NULL,
    "shipped_at" TIMESTAMP(3),
    "closed_at" TIMESTAMP(3),
    "tracking_no" VARCHAR(100),
    "resolution" TEXT,
    "note" TEXT,
    "created_by_id" UUID NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "repair_orders_pkey" PRIMARY KEY ("id"),
    CONSTRAINT "repair_orders_repair_no_key" UNIQUE ("repair_no")
);
CREATE TABLE "repair_events" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "repair_order_id" UUID NOT NULL,
    "author_id" UUID NOT NULL,
    "type" VARCHAR(60) NOT NULL,
    "content" TEXT NOT NULL,
    "metadata" JSONB,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "repair_events_pkey" PRIMARY KEY ("id")
);
ALTER TABLE "repair_orders" ADD CONSTRAINT "repair_orders_device_id_fkey" FOREIGN KEY ("device_id") REFERENCES "devices"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "repair_orders" ADD CONSTRAINT "repair_orders_organization_id_fkey" FOREIGN KEY ("organization_id") REFERENCES "customer_organizations"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "repair_orders" ADD CONSTRAINT "repair_orders_contact_id_fkey" FOREIGN KEY ("contact_id") REFERENCES "contacts"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "repair_orders" ADD CONSTRAINT "repair_orders_assignee_id_fkey" FOREIGN KEY ("assignee_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "repair_events" ADD CONSTRAINT "repair_events_repair_order_id_fkey" FOREIGN KEY ("repair_order_id") REFERENCES "repair_orders"("id") ON DELETE CASCADE ON UPDATE CASCADE;
CREATE INDEX "repair_orders_organization_id_idx" ON "repair_orders"("organization_id");
CREATE INDEX "repair_orders_device_id_idx" ON "repair_orders"("device_id");
CREATE INDEX "repair_orders_assignee_id_status_idx" ON "repair_orders"("assignee_id", "status");
CREATE INDEX "repair_events_repair_order_id_created_at_idx" ON "repair_events"("repair_order_id", "created_at");

-- attachments: 支持返修单
ALTER TABLE "attachments" ADD COLUMN "repair_order_id" UUID;
ALTER TABLE "attachments" ADD CONSTRAINT "attachments_repair_order_id_fkey" FOREIGN KEY ("repair_order_id") REFERENCES "repair_orders"("id") ON DELETE CASCADE ON UPDATE CASCADE;
CREATE INDEX "attachments_repair_order_id_idx" ON "attachments"("repair_order_id");
