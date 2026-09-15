-- 借测单状态默认值设为 QUEUED（需在枚举值提交后单独执行）
ALTER TABLE "loan_orders" ALTER COLUMN "status" SET DEFAULT 'QUEUED';
