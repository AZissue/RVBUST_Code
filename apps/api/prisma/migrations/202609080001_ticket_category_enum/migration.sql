-- Ticket.category 自由文本收敛为 TicketCategory 枚举（存量中文标签映射，未知值归 OTHER）

-- CreateEnum
CREATE TYPE "TicketCategory" AS ENUM ('PRE_SALES', 'TRAINING', 'POINTCLOUD_DEBUG', 'SDK_DEVELOPMENT', 'HAND_EYE_CALIBRATION', 'HARDWARE_FAILURE', 'OTHER');

-- AlterTable
ALTER TABLE "tickets"
ALTER COLUMN "category" DROP DEFAULT,
ALTER COLUMN "category" SET DATA TYPE "TicketCategory" USING ((
  CASE "category"
    WHEN '售前咨询' THEN 'PRE_SALES'
    WHEN '客户培训' THEN 'TRAINING'
    WHEN '点云调试' THEN 'POINTCLOUD_DEBUG'
    WHEN 'SDK 开发' THEN 'SDK_DEVELOPMENT'
    WHEN 'SDK开发' THEN 'SDK_DEVELOPMENT'
    WHEN '手眼标定' THEN 'HAND_EYE_CALIBRATION'
    WHEN '硬件故障' THEN 'HARDWARE_FAILURE'
    ELSE 'OTHER'
  END
)::text::"TicketCategory"),
ALTER COLUMN "category" SET DEFAULT 'OTHER';
