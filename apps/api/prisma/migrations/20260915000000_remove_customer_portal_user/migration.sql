-- 删除 customer 门户账号体系（数据清理必须在删列之前，按外键顺序）

-- 1. 该用户的登录会话
DELETE FROM "auth_sessions" WHERE "user_id" IN (SELECT "id" FROM "users" WHERE "username" = 'customer');

-- 2. customer 角色的权限绑定 + tickets.customer 孤立权限的绑定
DELETE FROM "role_permissions" WHERE "role_id" IN (SELECT "id" FROM "roles" WHERE "name" = 'customer');
DELETE FROM "role_permissions" WHERE "permission_id" IN (SELECT "id" FROM "permissions" WHERE "code" = 'tickets.customer');

-- 3. customer 门户账号本身
DELETE FROM "users" WHERE "username" = 'customer';

-- 4. customer 角色
DELETE FROM "roles" WHERE "name" = 'customer';

-- 5. tickets.customer 孤立权限码
DELETE FROM "permissions" WHERE "code" = 'tickets.customer';

-- DropForeignKey
ALTER TABLE "users" DROP CONSTRAINT "users_customer_organization_id_fkey";

-- DropIndex
DROP INDEX "users_customer_organization_id_idx";

-- AlterTable
ALTER TABLE "users" DROP COLUMN "customer_organization_id";
