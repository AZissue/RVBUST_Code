-- 工单回收站（软删除）与协助/驳回
-- 1) 新增协助请求状态枚举
CREATE TYPE "TicketAssistStatus" AS ENUM ('PENDING', 'ACCEPTED', 'REJECTED', 'CANCELLED');

-- 2) 工单事件类型扩展（协助与删除/恢复记录）
ALTER TYPE "TicketEventType" ADD VALUE 'ASSIST_REQUEST';
ALTER TYPE "TicketEventType" ADD VALUE 'ASSIST_ACCEPT';
ALTER TYPE "TicketEventType" ADD VALUE 'ASSIST_REJECT';
ALTER TYPE "TicketEventType" ADD VALUE 'DELETE';
ALTER TYPE "TicketEventType" ADD VALUE 'RESTORE';

-- 3) 工单软删除字段（回收站）
ALTER TABLE "tickets" ADD COLUMN "deleted_at" TIMESTAMP(3),
ADD COLUMN "deleted_by_id" UUID,
ADD COLUMN "deleted_reason" TEXT;

CREATE INDEX "tickets_deleted_at_idx" ON "tickets"("deleted_at");

-- 4) 协助请求表
CREATE TABLE "ticket_assist_requests" (
    "id" UUID NOT NULL,
    "ticket_id" UUID NOT NULL,
    "requester_id" UUID NOT NULL,
    "target_user_id" UUID NOT NULL,
    "status" "TicketAssistStatus" NOT NULL DEFAULT 'PENDING',
    "message" TEXT,
    "accepted_at" TIMESTAMP(3),
    "rejected_at" TIMESTAMP(3),
    "reject_reason" TEXT,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "ticket_assist_requests_pkey" PRIMARY KEY ("id")
);

CREATE INDEX "ticket_assist_requests_ticket_id_idx" ON "ticket_assist_requests"("ticket_id");
CREATE INDEX "ticket_assist_requests_target_user_id_status_idx" ON "ticket_assist_requests"("target_user_id", "status");
CREATE INDEX "ticket_assist_requests_requester_id_idx" ON "ticket_assist_requests"("requester_id");

-- 5) 外键
ALTER TABLE "tickets" ADD CONSTRAINT "tickets_deleted_by_id_fkey" FOREIGN KEY ("deleted_by_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "ticket_assist_requests" ADD CONSTRAINT "ticket_assist_requests_ticket_id_fkey" FOREIGN KEY ("ticket_id") REFERENCES "tickets"("id") ON DELETE CASCADE ON UPDATE CASCADE;
ALTER TABLE "ticket_assist_requests" ADD CONSTRAINT "ticket_assist_requests_requester_id_fkey" FOREIGN KEY ("requester_id") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "ticket_assist_requests" ADD CONSTRAINT "ticket_assist_requests_target_user_id_fkey" FOREIGN KEY ("target_user_id") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
