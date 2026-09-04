import { expect, test } from '@playwright/test'

test('quick input, personal ticket sync, themes and mobile', async ({ page, browser }) => {
  if (!process.env.DATABASE_URL?.includes('schema=quick_ticket_test')) throw new Error('Requires isolated quick_ticket_test schema')
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  await page.goto('/')
  await page.getByLabel('账号').fill('admin')
  await page.getByLabel('密码').fill(process.env.SEED_ADMIN_PASSWORD!)
  await page.getByRole('button', { name: '安全登录' }).click()
  await expect(page.getByRole('heading', { name: '今日工作台' })).toBeVisible()
  await expect(page.locator('nav').getByRole('link', { name: '工作事项', exact: true })).toHaveCount(0)
  const users = await (await page.request.get('/api/users')).json()
  const support = users.find((u: { username: string }) => u.username === 'support')
  const admin = users.find((u: { username: string }) => u.username === 'admin')
  await page.request.patch(`/api/users/${admin.id}`, { data: { name: '张伟' } })
  await page.request.patch(`/api/users/${support.id}`, { data: { name: '李四' } })
  for (const name of ['浙江智享机器人', '工布公司']) {
    const customers = await (await page.request.get('/api/customers')).json()
    if (!customers.some((c: { name: string }) => c.name === name)) expect((await page.request.post('/api/customers', { data: { name } })).ok()).toBe(true)
  }
  const inputs = [
    ['浙江智享机器人 M2600拍摄3D无点云 张伟 紧急', 'URGENT', true],
    ['浙江智享 M2600连接不上 张伟 高优先级', 'HIGH', true],
    ['工布 G52000 2D正常3D无点云 李四 普通', 'MEDIUM', true],
    ['浙江智享机器人 M2600拍摄超时', 'MEDIUM', true],
    ['M2600无点云 张伟 紧急', 'URGENT', false],
  ] as const
  for (const [input, priority, matched] of inputs) {
    await page.getByLabel('快速工单输入').fill(input)
    await page.getByRole('button', { name: '解析并创建工单' }).click()
    const dialog = page.getByRole('dialog', { name: '解析结果确认' })
    await expect(dialog).toBeVisible()
    await expect(dialog.getByLabel('确认优先级')).toHaveValue(priority)
    if (!matched) {
      await expect(dialog.getByText('未匹配到现有客户', { exact: true })).toBeVisible()
      await expect(dialog.getByRole('button', { name: '确认创建工单', exact: true })).toBeDisabled()
    } else await expect(dialog.getByLabel('确认客户')).not.toHaveValue('')
    if (input.includes('2D正常')) await expect(dialog.getByLabel('确认问题')).toHaveValue('G52000 2D正常3D无点云')
    await dialog.getByRole('button', { name: '重新编辑' }).click()
  }
  const extraCustomerResponse = await page.request.post('/api/customers', { data: { name: '浙江智享科技' } })
  expect(extraCustomerResponse.ok()).toBe(true)
  const extraCustomer = await extraCustomerResponse.json()
  const employee = users.find((u: { username: string }) => u.username === 'employee')
  await page.request.patch(`/api/users/${employee.id}`, { data: { name: '张三' } })
  try {
    await page.getByLabel('快速工单输入').fill('浙江智享 M2600无点云 张工 紧急')
    await page.getByRole('button', { name: '解析并创建工单' }).click()
    const ambiguous = page.getByRole('dialog', { name: '解析结果确认' })
    await expect(ambiguous.getByLabel('确认客户')).toHaveValue('')
    await expect(ambiguous.getByLabel('确认负责人')).toHaveValue('')
    await expect(ambiguous.getByRole('button', { name: '确认创建工单', exact: true })).toBeDisabled()
    await expect(ambiguous.getByText('可能的客户', { exact: true })).toBeVisible()
    await ambiguous.getByRole('button', { name: '重新编辑' }).click()
  } finally {
    await page.request.delete(`/api/customers/${extraCustomer.id}`)
    await page.request.patch(`/api/users/${employee.id}`, { data: { name: employee.name } })
  }
  await page.getByLabel('快速工单输入').fill('浙江智享机器人 M2600拍摄3D无点云 张伟 紧急')
  await page.getByRole('button', { name: '解析并创建工单' }).click()
  const dialog = page.getByRole('dialog', { name: '解析结果确认' })
  await expect(dialog.getByLabel('确认负责人')).toHaveValue(admin.id)
  await expect(dialog.getByRole('button', { name: /确认创建工单|仍然创建新工单/ })).toBeEnabled()
  await page.screenshot({ path: 'test-results/quick-confirm-desktop.png', fullPage: true })
  await dialog.getByRole('button', { name: /确认创建工单|仍然创建新工单/ }).click()
  await expect(page.getByRole('status').filter({ hasText: '创建成功' })).toBeVisible()
  const href = await page.getByRole('status').getByRole('link', { name: '查看工单', exact: true }).getAttribute('href')
  const id = href!.split('/').pop()!
  try {
    await page.reload()
    await expect(page.locator('.today-overview')).toContainText('待处理工单')
    await page.getByRole('link', { name: '我的工作', exact: true }).first().click()
    const row = page.locator(`.personal-ticket-list a[href="/tickets/${id}"]`)
    await expect(row).toBeVisible(); await row.click()
    await expect(page).toHaveURL(new RegExp(`/tickets/${id}$`))
    await page.locator('.status-select').selectOption('IN_PROGRESS')
    await expect(page.locator('.detail-header')).toContainText('处理中')
    await page.getByRole('link', { name: '我的工作', exact: true }).click()
    await expect(row).toContainText('处理中')
    expect(await row.locator('.task-main').evaluate((e) => e.getBoundingClientRect().width)).toBeGreaterThan(300)
    await page.screenshot({ path: 'test-results/my-work-light.png', fullPage: true })
    await page.getByTitle('深色').click()
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark')
    await page.screenshot({ path: 'test-results/my-work-dark.png', fullPage: true })
    await row.click()
    await page.getByLabel('工单负责人', { exact: true }).selectOption(support.id)
    await expect(page.getByLabel('工单负责人', { exact: true })).toHaveValue(support.id)
    await page.getByRole('link', { name: '我的工作', exact: true }).click()
    await expect(row).toHaveCount(0)
    const supportContext = await browser.newContext({ baseURL: process.env.WEB_PORT ? `http://127.0.0.1:${process.env.WEB_PORT}` : 'http://127.0.0.1:5173' })
    await supportContext.request.post('/api/auth/login', { data: { username: 'support', password: process.env.SEED_SUPPORT_PASSWORD } })
    const supportPage = await supportContext.newPage()
    await supportPage.goto('/my-work')
    await expect(supportPage.locator(`a[href="/tickets/${id}"]`)).toBeVisible()
    await supportContext.close()
    await page.getByRole('link', { name: '仪表盘', exact: true }).click()
    await page.getByLabel('快速工单输入').fill('浙江智享 M2600没有点云 张伟 高优先级')
    await page.getByRole('button', { name: '解析并创建工单' }).click()
    await expect(page.getByRole('heading', { name: '发现可能相关的现有工单' })).toBeVisible()
    const match = page.locator('.similar-tickets article').filter({ has: page.locator(`a[href="/tickets/${id}"]`) })
    page.once('dialog', (d) => d.accept())
    await match.getByRole('button', { name: '更新现有工单' }).click()
    await expect(page.getByRole('status').filter({ hasText: '更新成功' })).toBeVisible()
    const persisted = await (await page.request.get(`/api/tickets/${id}`)).json()
    expect(persisted.status).toBe('IN_PROGRESS'); expect(persisted.assignee.id).toBe(admin.id)
    expect(persisted.events.at(-1).content).toBe('M2600没有点云')
    await page.setViewportSize({ width: 390, height: 844 })
    await page.getByTitle('浅色').click()
    await page.screenshot({ path: 'test-results/dashboard-mobile.png', fullPage: true })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.getByLabel('快速工单输入').fill('M2600无点云 张伟 紧急')
    await page.getByRole('button', { name: '解析并创建工单' }).click()
    await page.screenshot({ path: 'test-results/quick-confirm-mobile.png' })
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
    await page.getByRole('button', { name: '重新编辑' }).click()
    for (const path of ['/customers', '/devices', '/worklogs', '/reports', '/stats', '/work-items']) {
      await page.goto(path); await expect(page.locator('h1')).toBeVisible(); await expect(page.getByText('数据加载失败', { exact: true })).toHaveCount(0)
    }
    expect(errors).toEqual([])
  } finally { await page.request.delete(`/api/tickets/${id}`) }
})
