-- CreateEnum
CREATE TYPE "BugStatus" AS ENUM ('OPEN', 'IN_PROGRESS', 'FIXED');

-- CreateTable
CREATE TABLE "bug_reports" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "bug_no" VARCHAR(32) NOT NULL,
    "title" VARCHAR(240) NOT NULL,
    "description" VARCHAR(20000) NOT NULL,
    "status" "BugStatus" NOT NULL DEFAULT 'OPEN',
    "author_id" UUID NOT NULL,
    "resolver_id" UUID,
    "resolved_at" TIMESTAMP(3),
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "bug_reports_pkey" PRIMARY KEY ("id")
);

-- AlterTable
ALTER TABLE "attachments" ADD COLUMN "bug_report_id" UUID;

-- CreateIndex
CREATE UNIQUE INDEX "bug_reports_bug_no_key" ON "bug_reports"("bug_no");
CREATE INDEX "bug_reports_status_idx" ON "bug_reports"("status");
CREATE INDEX "bug_reports_author_id_idx" ON "bug_reports"("author_id");
CREATE INDEX "attachments_bug_report_id_idx" ON "attachments"("bug_report_id");

-- AddForeignKey
ALTER TABLE "bug_reports" ADD CONSTRAINT "bug_reports_author_id_fkey" FOREIGN KEY ("author_id") REFERENCES "users"("id") ON DELETE RESTRICT ON UPDATE CASCADE;
ALTER TABLE "bug_reports" ADD CONSTRAINT "bug_reports_resolver_id_fkey" FOREIGN KEY ("resolver_id") REFERENCES "users"("id") ON DELETE SET NULL ON UPDATE CASCADE;
ALTER TABLE "attachments" ADD CONSTRAINT "attachments_bug_report_id_fkey" FOREIGN KEY ("bug_report_id") REFERENCES "bug_reports"("id") ON DELETE CASCADE ON UPDATE CASCADE;
