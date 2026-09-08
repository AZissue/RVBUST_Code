-- 字段规范化收敛：Ticket.source 移除（与 category 合并）、客户等级/项目状态/返修事件类型转枚举

CREATE TYPE "CustomerLevel" AS ENUM ('A', 'B', 'C', 'D');
CREATE TYPE "ProjectStatus" AS ENUM ('IN_PROGRESS', 'DELIVERED', 'PAUSED', 'TERMINATED');
CREATE TYPE "RepairEventType" AS ENUM ('STATUS_CHANGE', 'ATTACHMENT', 'NOTE');

-- 客户等级：存量 A-D 直转，其余置空待人工维护
ALTER TABLE "customer_organizations" ALTER COLUMN "level" SET DATA TYPE "CustomerLevel" USING (CASE WHEN "level" IN ('A','B','C','D') THEN "level"::text::"CustomerLevel" ELSE NULL END);

-- 项目状态：存量中文映射，无法识别置空
ALTER TABLE "projects" ALTER COLUMN "status" SET DATA TYPE "ProjectStatus" USING (CASE "status"
  WHEN '调试中' THEN 'IN_PROGRESS'::"ProjectStatus"
  WHEN '进行中' THEN 'IN_PROGRESS'::"ProjectStatus"
  WHEN '已交付' THEN 'DELIVERED'::"ProjectStatus"
  WHEN '已暂停' THEN 'PAUSED'::"ProjectStatus"
  WHEN '已终止' THEN 'TERMINATED'::"ProjectStatus"
  ELSE NULL END);

-- 返修事件类型：存量 STATUS_CHANGE/ATTACHMENT 直转
ALTER TABLE "repair_events" ALTER COLUMN "type" SET DATA TYPE "RepairEventType" USING ("type"::text::"RepairEventType");

-- source 与 category 语义合并：分类以 TicketCategory 为唯一维度，移除来源字段
ALTER TABLE "tickets" DROP COLUMN "source";
DROP TYPE "TicketSource";
