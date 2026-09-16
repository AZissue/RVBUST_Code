-- AlterEnum
ALTER TYPE "TicketCategory" ADD VALUE 'LOAN_REQUEST';

-- AlterEnum
-- This migration adds more than one value to an enum.
-- With PostgreSQL versions 11 and earlier, this is not possible
-- in a single migration. This can be worked around by creating
-- multiple migrations, each migration adding only one value to
-- the enum.


ALTER TYPE "TicketEventType" ADD VALUE 'LINK_CREATED';
ALTER TYPE "TicketEventType" ADD VALUE 'LINK_UPDATE';

-- 部分唯一索引：同一工单仅允许一张进行中的借测单/维修单（软删除除外），Prisma schema 无法表达，手写 SQL
CREATE UNIQUE INDEX loan_orders_one_active_per_ticket ON loan_orders(ticket_id) WHERE status IN ('QUEUED','ONGOING','OVERDUE') AND deleted_at IS NULL;
CREATE UNIQUE INDEX repair_orders_one_active_per_ticket ON repair_orders(ticket_id) WHERE status IN ('RECEIVED','DIAGNOSING','REPAIRING','SHIPPED') AND deleted_at IS NULL;
