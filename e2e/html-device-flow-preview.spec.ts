import { expect, test } from '@playwright/test'

test.use({ channel: 'chrome' })

const previewDb = '/flow_github_21b4129'
const sourceKey = 'device_flow_records_v28_real'

test.beforeEach(async ({ page }) => {
  if (!process.env.DATABASE_URL?.includes(previewDb)) throw new Error('Only run against the isolated device-flow preview database')
  if (!process.env.SEED_ADMIN_PASSWORD) throw new Error('Preview admin password is missing')
  await page.goto('/login')
  await page.getByLabel('账号').fill('admin')
  await page.getByLabel('密码').fill(process.env.SEED_ADMIN_PASSWORD)
  await page.getByRole('button', { name: '安全登录' }).click()
  await page.waitForURL('/')
  await page.goto('/device-flow')
  await page.frameLocator('iframe').locator('#flowSyncStatus').waitFor()
})

test('loads imported records and preserves the original loan controls', async ({ page }) => {
  const frame = page.frameLocator('iframe')
  const snapshot = await page.request.get('/api/html-device-flow/snapshot')
  expect(snapshot.ok()).toBeTruthy()
  const data = (await snapshot.json()).data
  expect(data.records).toHaveLength(1102)
  expect(data.devices).toHaveLength(75)
  await page.waitForTimeout(500)
  if (await frame.locator('#dueWarningModal').evaluate((node) => node.classList.contains('open'))) {
    await frame.locator('#dueWarningModal button').first().click()
  }
  await frame.locator('nav button[data-tab="loans"]').click()
  await expect(frame.locator('#loans')).toBeVisible()
  await frame.locator('#loanFilter').selectOption('已逾期')
  await frame.locator('#loanSort').selectOption('overdue_desc')
  await expect(frame.locator('#loanTable tbody tr').first()).toHaveClass(/overdue-row/)
  await frame.locator('#loanSearch').fill('NO-SUCH-PREVIEW-RECORD')
  await expect(frame.locator('#loanTable')).toContainText('暂无记录')
  await frame.locator('#loanSearch').fill('')
  await frame.locator('body').evaluate(async (body) => {
    const view = body.ownerDocument!.defaultView as any
    while (!view.XLSX) await new Promise((resolve) => setTimeout(resolve, 100))
  })
  const download = page.waitForEvent('download')
  await frame.locator('#loans button[onclick="exportRecordsExcel(\'loan\')"]').click()
  expect((await download).suggestedFilename()).toMatch(/^借测记录_.*\.xlsx$/)
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await frame.locator('body').evaluate((body) => body.ownerDocument!.documentElement.scrollWidth)).toBe(390)
})

test('saves a new record to the server and keeps it after reload', async ({ page }) => {
  const frame = page.frameLocator('iframe')
  const id = `PREVIEW-${Date.now()}`
  try {
    await frame.locator('body').evaluate(async (body, args) => {
      const flow = (body.ownerDocument!.defaultView as any).flowOnline
      const records = flow.load(args.key, [])
      records.unshift({ id: args.id, type: 'repair', sn: args.id, model: '预览测试', customer: '预览测试', status: '待寄回', photos: {}, followUps: [] })
      await flow.save(args.key, records)
    }, { key: sourceKey, id })
    await page.reload()
    await frame.locator('#flowSyncStatus').waitFor()
    expect(await frame.locator('body').evaluate((body, args) => {
      const flow = (body.ownerDocument!.defaultView as any).flowOnline
      return flow.load(args.key, []).some((record: any) => record.id === args.id)
    }, { key: sourceKey, id })).toBeTruthy()
  } finally {
    await frame.locator('body').evaluate(async (body, args) => {
      const flow = (body.ownerDocument!.defaultView as any).flowOnline
      await flow.save(args.key, flow.load(args.key, []).filter((record: any) => record.id !== args.id))
    }, { key: sourceKey, id })
  }
})

test('creates a repair through the original form and generates its PDF', async ({ page }) => {
  const frame = page.frameLocator('iframe')
  const sn = `PREVIEW-REPAIR-${Date.now()}`
  page.on('dialog', (dialog) => dialog.accept())
  await page.waitForTimeout(500)
  if (await frame.locator('#dueWarningModal').evaluate((node) => node.classList.contains('open'))) {
    await frame.locator('#dueWarningModal button').first().click()
  }
  try {
    await frame.locator('nav button[data-tab="repairs"]').click()
    await frame.locator('#repairs button[onclick="goNew(\'repair\')"]').click()
    await frame.locator('#rSN').fill(sn)
    await frame.locator('#rModel').fill('预览测试型号')
    await frame.locator('#rCustomer').fill('预览测试客户')
    await frame.locator('#rReason').fill('预览测试故障')
    await frame.locator('body').evaluate(async (body) => {
      const view = body.ownerDocument!.defaultView as any
      while (!view.html2canvas || !view.jspdf) await new Promise((resolve) => setTimeout(resolve, 100))
    })
    const download = page.waitForEvent('download')
    await frame.locator('#newRecord button[onclick="saveRecord()"]').click()
    expect((await download).suggestedFilename()).toMatch(/^返厂维修单_.*\.pdf$/)
    await expect(frame.locator('#repairs')).toBeVisible()
    await page.reload()
    await frame.locator('#flowSyncStatus').waitFor()
    const record = await frame.locator('body').evaluate((body, args) => {
      const flow = (body.ownerDocument!.defaultView as any).flowOnline
      return flow.load(args.key, []).find((item: any) => item.sn === args.sn)
    }, { key: sourceKey, sn })
    expect(record).toBeTruthy()
  } finally {
    await frame.locator('body').evaluate(async (body, args) => {
      const flow = (body.ownerDocument!.defaultView as any).flowOnline
      await flow.save(args.key, flow.load(args.key, []).filter((record: any) => record.sn !== args.sn))
      const devices = flow.load('device_flow_devices_v28_real', [])
      await flow.save('device_flow_devices_v28_real', devices.filter((device: any) => device.sn !== args.sn))
    }, { key: sourceKey, sn })
  }
})

test('stores loan agreement and device photo on the server', async ({ page }) => {
  const frame = page.frameLocator('iframe')
  const sn = `PREVIEW-LOAN-${Date.now()}`
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==', 'base64')
  let agreementUrl = ''
  let photoUrl = ''
  page.on('dialog', (dialog) => dialog.accept())
  await page.waitForTimeout(500)
  if (await frame.locator('#dueWarningModal').evaluate((node) => node.classList.contains('open'))) {
    await frame.locator('#dueWarningModal button').first().click()
  }
  try {
    await frame.locator('nav button[data-tab="loans"]').click()
    await frame.locator('#loans button[onclick="goNew(\'loan\')"]').click()
    await frame.locator('#rSN').fill(sn)
    await frame.locator('#rModel').fill('预览借测型号')
    await frame.locator('#rCustomer').fill('预览借测客户')
    await frame.locator('#agreementFileInput').setInputFiles({ name: '预览协议.png', mimeType: 'image/png', buffer: png })
    await expect(frame.locator('#agreementStatus')).toContainText('已添加')
    await frame.locator('#slot0 input[type="file"]').setInputFiles({ name: '预览相机.png', mimeType: 'image/png', buffer: png })
    await expect(frame.locator('#slot0')).toHaveClass(/has-photo/)
    await frame.locator('#newRecord button[onclick="saveRecord()"]').click()
    await expect(frame.locator('#loans')).toBeVisible()
    await page.reload()
    await frame.locator('#flowSyncStatus').waitFor()
    const saved = await frame.locator('body').evaluate((body, args) => {
      const flow = (body.ownerDocument!.defaultView as any).flowOnline
      return flow.load(args.key, []).find((item: any) => item.sn === args.sn)
    }, { key: sourceKey, sn })
    expect(saved?.agreement?.data).toMatch(/^\/api\/html-device-flow\/files\//)
    expect(saved?.photos?.['0']).toMatch(/^\/api\/html-device-flow\/files\//)
    agreementUrl = saved.agreement.data
    photoUrl = saved.photos['0']
    const agreement = await page.request.get(saved.agreement.data)
    const photo = await page.request.get(saved.photos['0'])
    expect(agreement.ok()).toBeTruthy()
    expect(photo.ok()).toBeTruthy()
    expect(agreement.headers()['content-type']).toContain('image/png')
    expect(photo.headers()['content-type']).toContain('image/jpeg')
    expect(agreement.headers()['content-disposition']).toContain(encodeURIComponent('预览协议.png'))
  } finally {
    await frame.locator('body').evaluate(async (body, args) => {
      const flow = (body.ownerDocument!.defaultView as any).flowOnline
      await flow.save(args.key, flow.load(args.key, []).filter((record: any) => record.sn !== args.sn))
      const devices = flow.load('device_flow_devices_v28_real', [])
      await flow.save('device_flow_devices_v28_real', devices.filter((device: any) => device.sn !== args.sn))
    }, { key: sourceKey, sn })
  }
  expect((await page.request.get(agreementUrl)).status()).toBe(404)
  expect((await page.request.get(photoUrl)).status()).toBe(404)
})
