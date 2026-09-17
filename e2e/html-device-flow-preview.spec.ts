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
})

async function openDeviceFlow(page: import('@playwright/test').Page) {
  await page.goto('/device-flow')
  await expect(page.locator('.device-flow-mount')).toBeAttached()
  // 等待数据加载与首屏渲染完成（is-ready 由 init() 完成后设置）
  await expect(page.locator('.device-flow-mount.is-ready')).toBeVisible()
  await page.waitForTimeout(600)
  if (await page.locator('#dueWarningModal').evaluate((node) => node.classList.contains('open'))) {
    await page.locator('#dueWarningModal button').first().click()
  }
}

test('device flow lives inside the support system shell with in-page tabs', async ({ page }) => {
  await openDeviceFlow(page)
  // 系统外壳：顶部栏 + 左侧主导航保留，页面内是标签而不是第二套侧边栏
  await expect(page.locator('header.topbar')).toBeVisible()
  await expect(page.locator('.sidebar')).toBeVisible()
  await expect(page.locator('.sidebar a.active')).toContainText('设备服务管理')
  await expect(page.locator('.device-flow-mount nav.flow-tabs button')).toHaveCount(4)
  await expect(page.locator('iframe')).toHaveCount(0)

  // 四个标签来回切换：只切换内容，不整页重建
  for (const tab of ['repairs', 'loans', 'recycle', 'dashboard']) {
    await page.locator(`.flow-tabs button[data-tab="${tab}"]`).click()
    await expect(page.locator(`#${tab}`)).toBeVisible()
    await expect(page.locator('.section.active')).toHaveCount(1)
  }
})

test('keeps imported records and the original loan controls', async ({ page }) => {
  await openDeviceFlow(page)
  const snapshot = await page.request.get('/api/html-device-flow/snapshot')
  expect(snapshot.ok()).toBeTruthy()
  const data = (await snapshot.json()).data
  expect(data.records).toHaveLength(1102)
  expect(data.devices).toHaveLength(75)

  await page.locator('.flow-tabs button[data-tab="loans"]').click()
  await expect(page.locator('#loans')).toBeVisible()
  await page.locator('#loanFilter').selectOption('已逾期')
  await page.locator('#loanSort').selectOption('overdue_desc')
  await expect(page.locator('#loanTable tbody tr').first()).toHaveClass(/overdue-row/)
  await page.locator('#loanSearch').fill('NO-SUCH-PREVIEW-RECORD')
  await expect(page.locator('#loanTable')).toContainText('暂无记录')
  await page.locator('#loanSearch').fill('')

  // Excel 导出（组件按需加载）
  const download = page.waitForEvent('download', { timeout: 60000 })
  await page.locator('#loans button[onclick="exportRecordsExcel(\'loan\')"]').click()
  expect((await download).suggestedFilename()).toMatch(/^借测记录_.*\.xlsx$/)

  // 详情抽屉：打开后关闭回到列表，筛选状态保留
  await page.locator('#loanTable tbody tr').first().locator('td').first().click()
  await expect(page.locator('#drawer.drawer')).toHaveClass(/open/)
  await page.locator('#drawer .drawer-head button').click()
  await expect(page.locator('#drawer.drawer')).not.toHaveClass(/open/)
  await expect(page.locator('#loanFilter')).toHaveValue('已逾期')
})

test('new-device entry removed, page title and tabs renamed, mobile width fits', async ({ page }) => {
  await openDeviceFlow(page)
  // 旧版“+ 新建设备”按钮与弹窗已移除，数据入口只在维修/借测管理
  await expect(page.locator('#dashboard button[onclick="openDeviceForm()"]')).toHaveCount(0)
  await expect(page.locator('#deviceModal')).toHaveCount(0)
  await expect(page.locator('.page-header h1')).toHaveText('设备服务管理')
  await expect(page.locator('.sidebar a.active')).toContainText('设备服务管理')
  // 命名一致：维修工单 / 借测单
  await page.locator('.flow-tabs button[data-tab="loans"]').click()
  await expect(page.locator('#loans button[onclick="goNew(\'loan\')"]')).toContainText('新建借测单')
  await page.setViewportSize({ width: 390, height: 844 })
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390)
  await page.setViewportSize({ width: 1440, height: 900 })
})

test('saves a new record to the server and keeps it after reload', async ({ page }) => {
  await openDeviceFlow(page)
  const id = `PREVIEW-${Date.now()}`
  try {
    await page.evaluate(async (args) => {
      const flow = window.flowOnline
      const records = flow.load(args.key, [])
      records.unshift({ id: args.id, type: 'repair', sn: args.id, model: '预览测试', customer: '预览测试', status: '待寄回', photos: {}, followUps: [] })
      await flow.save(args.key, records)
    }, { key: sourceKey, id })
    await page.reload()
    await page.locator('.device-flow-mount.is-ready').waitFor({ timeout: 15000 })
    expect(await page.evaluate((args) => {
      const flow = window.flowOnline
      return flow.load(args.key, []).some((record: { id: string }) => record.id === args.id)
    }, { key: sourceKey, id })).toBeTruthy()
  } finally {
    await page.evaluate(async (args) => {
      const flow = window.flowOnline
      await flow.save(args.key, flow.load(args.key, []).filter((record: { id: string }) => record.id !== args.id))
    }, { key: sourceKey, id })
  }
})

test('creates a repair through the drawer form and generates its PDF', async ({ page }) => {
  await openDeviceFlow(page)
  const sn = `PREVIEW-REPAIR-${Date.now()}`
  page.on('dialog', (dialog) => dialog.accept())
  try {
    await page.locator('.flow-tabs button[data-tab="repairs"]').click()
    await page.locator('#repairs button[onclick="goNew(\'repair\')"]').click()
    // 新建工单在当前页以抽屉打开，列表仍在后面
    await expect(page.locator('#newRecord.drawer')).toHaveClass(/open/)
    await expect(page.locator('#repairs')).toBeVisible()
    await page.locator('#rSN').fill(sn)
    await page.locator('#rModel').fill('预览测试型号')
    await page.locator('#rCustomer').fill('预览测试客户')
    await page.locator('#rReason').fill('预览测试故障')
    await page.locator('#newRecord button[onclick="saveRecord()"]').click()
    // 保存后回到维修列表并能看到新记录（保存不再自动下载 PDF）
    await expect(page.locator('#newRecord.drawer')).not.toHaveClass(/open/)
    await expect(page.locator('#repairs')).toBeVisible()
    await page.locator('#repairSearch').fill(sn)
    await expect(page.locator('#repairTable')).toContainText(sn)
    // 从详情生成维修工单 PDF：文件名“维修工单-单号-客户.pdf”
    await page.locator('#repairTable tbody tr').first().locator('td').first().click()
    await expect(page.locator('#drawer.drawer')).toHaveClass(/open/)
    await expect(page.locator('#drawer .drawer-top-actions')).toContainText('生成维修 PDF')
    const download = page.waitForEvent('download', { timeout: 60000 })
    await page.locator('#drawer .drawer-top-actions button', { hasText: '生成维修 PDF' }).click()
    expect((await download).suggestedFilename()).toMatch(/^维修工单-.*-预览测试客户\.pdf$/)
    await page.reload()
    await page.locator('.device-flow-mount.is-ready').waitFor({ timeout: 15000 })
    const record = await page.evaluate((args) => {
      const flow = window.flowOnline
      return flow.load(args.key, []).find((item: { sn: string }) => item.sn === args.sn)
    }, { key: sourceKey, sn })
    expect(record).toBeTruthy()
  } finally {
    await page.evaluate(async (args) => {
      const flow = window.flowOnline
      await flow.save(args.key, flow.load(args.key, []).filter((record: { sn: string }) => record.sn !== args.sn))
      const devices = flow.load('device_flow_devices_v28_real', [])
      await flow.save('device_flow_devices_v28_real', devices.filter((device: { sn: string }) => device.sn !== args.sn))
    }, { key: sourceKey, sn })
    // 等待防抖刷盘落库，避免浏览器回收时丢失清理
    await page.waitForTimeout(600)
  }
})

test('stores loan agreement and device photo on the server', async ({ page }) => {
  await openDeviceFlow(page)
  const sn = `PREVIEW-LOAN-${Date.now()}`
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==', 'base64')
  let agreementUrl = ''
  let photoUrl = ''
  page.on('dialog', (dialog) => dialog.accept())
  try {
    await page.locator('.flow-tabs button[data-tab="loans"]').click()
    await page.locator('#loans button[onclick="goNew(\'loan\')"]').click()
    await expect(page.locator('#newRecord.drawer')).toHaveClass(/open/)
    await page.locator('#rSN').fill(sn)
    await page.locator('#rModel').fill('预览借测型号')
    await page.locator('#rCustomer').fill('预览借测客户')
    await page.locator('#agreementFileInput').setInputFiles({ name: '预览协议.png', mimeType: 'image/png', buffer: png })
    await expect(page.locator('#agreementStatus')).toContainText('已添加')
    await page.locator('#slot0 input[type="file"]').setInputFiles({ name: '预览相机.png', mimeType: 'image/png', buffer: png })
    await expect(page.locator('#slot0')).toHaveClass(/has-photo/)
    await page.locator('#newRecord button[onclick="saveRecord()"]').click()
    await expect(page.locator('#newRecord.drawer')).not.toHaveClass(/open/)
    await expect(page.locator('#loans')).toBeVisible()
    await page.reload()
    await page.locator('.device-flow-mount.is-ready').waitFor({ timeout: 15000 })
    const saved = await page.evaluate((args) => {
      const flow = window.flowOnline
      return flow.load(args.key, []).find((item: { sn: string }) => item.sn === args.sn)
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

    // 附件预览：详情抽屉里打开图片 Lightbox
    await page.locator('.flow-tabs button[data-tab="loans"]').click()
    await page.locator('#loanSearch').fill(sn)
    await page.locator('#loanTable tbody tr').first().locator('td').first().click()
    await expect(page.locator('#drawer.drawer')).toHaveClass(/open/)
    await page.locator('#drawer .detail-photo img').first().click()
    await expect(page.locator('#imageLightbox')).toHaveClass(/open/)
    await page.keyboard.press('Escape')
    await expect(page.locator('#imageLightbox')).not.toHaveClass(/open/)
  } finally {
    await page.evaluate(async (args) => {
      const flow = window.flowOnline
      await flow.save(args.key, flow.load(args.key, []).filter((record: { sn: string }) => record.sn !== args.sn))
      const devices = flow.load('device_flow_devices_v28_real', [])
      await flow.save('device_flow_devices_v28_real', devices.filter((device: { sn: string }) => device.sn !== args.sn))
    }, { key: sourceKey, sn })
    // 等待防抖刷盘落库，避免浏览器回收时丢失清理
    await page.waitForTimeout(600)
  }
  expect((await page.request.get(agreementUrl)).status()).toBe(404)
  expect((await page.request.get(photoUrl)).status()).toBe(404)
})

test('loan detail photo upload, zip download, followup history and loan wording', async ({ page }) => {
  test.slow()
  await openDeviceFlow(page)
  const sn = `PREVIEW-PHOTO-${Date.now()}`
  const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVQIHWP4z8DwHwAFgAI/ScL/nwAAAABJRU5ErkJggg==', 'base64')
  page.on('dialog', (dialog) => dialog.accept())
  try {
    // 新建无图片借测单
    await page.locator('.flow-tabs button[data-tab="loans"]').click()
    await page.locator('#loans button[onclick="goNew(\'loan\')"]').click()
    await expect(page.locator('#newRecord.drawer')).toHaveClass(/open/)
    // 借测表单措辞：不得出现维修过程/维修动作/更换件
    await expect(page.locator('#notesSectionTitle')).toHaveText('借测备注')
    await expect(page.locator('#rNotes')).not.toHaveAttribute('placeholder', /维修/)
    await expect(page.locator('#newRecord')).not.toContainText('维修过程')
    // 物流区顺序：借测寄出在前、归还其后（DOM 顺序，网格按行排列）
    const logisticsOrder = await page.evaluate(() => {
      const outbound = document.getElementById('outboundCarrierWrap')
      const inbound = document.getElementById('fInboundCarrier')
      return outbound.compareDocumentPosition(inbound) & Node.DOCUMENT_POSITION_FOLLOWING ? 'inbound-after-outbound' : 'wrong-order'
    })
    expect(logisticsOrder).toBe('inbound-after-outbound')
    await page.locator('#rSN').fill(sn)
    await page.locator('#rModel').fill('预览拍照型号')
    await page.locator('#rCustomer').fill('预览拍照客户')
    await page.locator('#agreementFileInput').setInputFiles({ name: '预览协议.png', mimeType: 'image/png', buffer: png })
    await expect(page.locator('#agreementStatus')).toContainText('已添加')
    await page.locator('#newRecord button[onclick="saveRecord()"]').click()
    await expect(page.locator('#newRecord.drawer')).not.toHaveClass(/open/)

    // 详情空态：无下载按钮、有“添加图片”入口
    await page.locator('#loanSearch').fill(sn)
    await page.locator('#loanTable tbody tr').first().locator('td').first().click()
    await expect(page.locator('#drawer.drawer')).toHaveClass(/open/)
    await expect(page.locator('#drawer')).toContainText('此工单未上传图片')
    await expect(page.locator('#drawer')).toContainText('添加图片')
    await expect(page.locator('#drawer .drawer-top-actions')).not.toContainText('打包下载图片')
    // 借测详情备注标签
    await expect(page.locator('#drawer')).toContainText('借测备注')
    await expect(page.locator('#drawer')).not.toContainText('维修过程')

    // 添加图片：进入编辑抽屉图片区，上传两张
    await page.locator('#drawer button:has-text("添加图片")').click()
    await expect(page.locator('#newRecord.drawer')).toHaveClass(/open/)
    await page.locator('#slot0 input[type="file"]').setInputFiles({ name: '预览正面.png', mimeType: 'image/png', buffer: png })
    await page.locator('#slot1 input[type="file"]').setInputFiles({ name: '预览背面.png', mimeType: 'image/png', buffer: png })
    await expect(page.locator('#slot0')).toHaveClass(/has-photo/)
    await expect(page.locator('#slot1')).toHaveClass(/has-photo/)
    await page.locator('#newRecord button[onclick="saveRecord()"]').click()
    await expect(page.locator('#newRecord.drawer')).not.toHaveClass(/open/)

    // 刷新后图片仍在，可预览大图，可一键打包下载
    await page.reload()
    await page.locator('.device-flow-mount.is-ready').waitFor({ timeout: 15000 })
    await page.waitForTimeout(600)
    if (await page.locator('#dueWarningModal').evaluate((node) => node.classList.contains('open'))) {
      await page.locator('#dueWarningModal button').first().click()
    }
    await page.locator('.flow-tabs button[data-tab="loans"]').click()
    await page.locator('#loanSearch').fill(sn)
    await page.locator('#loanTable tbody tr').first().locator('td').first().click()
    await expect(page.locator('#drawer .detail-photo-grid img')).toHaveCount(2)
    await expect(page.locator('#drawer .drawer-top-actions')).toContainText('一键打包下载图片')
    await page.locator('#drawer .detail-photo-grid img').first().click()
    await expect(page.locator('#imageLightbox')).toHaveClass(/open/)
    await page.keyboard.press('Escape')
    await expect(page.locator('#imageLightbox')).not.toHaveClass(/open/)
    const zip = page.waitForEvent('download', { timeout: 60000 })
    await page.locator('#drawer .drawer-top-actions button', { hasText: '一键打包下载图片' }).click()
    expect((await zip).suggestedFilename()).toMatch(/\.zip$/)

    // 跟进表单对齐：控件不得越出抽屉右缘
    const drawerBox = await page.locator('#drawer').boundingBox()
    const followBtn = await page.locator('#drawer .followup-form .btn').boundingBox()
    expect(followBtn).not.toBeNull()
    expect(followBtn!.x + followBtn!.width).toBeLessThanOrEqual(drawerBox!.x + drawerBox!.width - 1)
    const textareaBox = await page.locator('#fuText').boundingBox()
    expect(textareaBox!.x + textareaBox!.width).toBeLessThanOrEqual(drawerBox!.x + drawerBox!.width - 1)

    // 添加跟进（日期默认当天，跟进人可输入，内容必填）
    await page.locator('#fuPerson').fill('预览测试员')
    await page.locator('#fuText').fill('预览跟进：已电话确认下周归还')
    await page.locator('#drawer .followup-form .btn').click()
    await expect(page.locator('#drawer .followup-item').first()).toContainText('预览跟进')
    // 等保存刷盘完成再刷新，避免跨会话并发冲突
    await page.waitForTimeout(600)

    // 刷新后历史仍在
    await page.reload()
    await page.locator('.device-flow-mount.is-ready').waitFor({ timeout: 15000 })
    await page.waitForTimeout(600)
    if (await page.locator('#dueWarningModal').evaluate((node) => node.classList.contains('open'))) {
      await page.locator('#dueWarningModal button').first().click()
    }
    await page.locator('.flow-tabs button[data-tab="loans"]').click()
    await page.locator('#loanSearch').fill(sn)
    await page.locator('#loanTable tbody tr').first().locator('td').first().click()
    await expect(page.locator('#drawer')).toContainText('预览跟进：已电话确认下周归还')
    await expect(page.locator('#drawer .followup-item').first()).toContainText('预览测试员')
  } finally {
    await page.evaluate(async (args) => {
      const flow = window.flowOnline
      await flow.save(args.key, flow.load(args.key, []).filter((record: { sn: string }) => record.sn !== args.sn))
      const devices = flow.load('device_flow_devices_v28_real', [])
      await flow.save('device_flow_devices_v28_real', devices.filter((device: { sn: string }) => device.sn !== args.sn))
    }, { key: sourceKey, sn })
    // 等待防抖刷盘落库，避免浏览器回收时丢失清理
    await page.waitForTimeout(600)
  }
})

test('repair without SN saves (no fake device), existing SN links, edit generates PDF', async ({ page }) => {
  test.slow()
  await openDeviceFlow(page)
  const noSnId = `PREVIEW-NOSN-${Date.now()}`
  const existSn = await page.evaluate(() => {
    const devs = window.flowOnline.load('device_flow_devices_v28_real', [])
    return devs.length ? devs[0].sn : ''
  })
  expect(existSn).toBeTruthy()
  const originalCustomer = await page.evaluate((args) => {
    const d = window.flowOnline.load('device_flow_devices_v28_real', []).find((x: { sn: string }) => x.sn === args.sn)
    return d ? d.customer : ''
  }, { sn: existSn })
  const devicesBefore = await page.evaluate(() => window.flowOnline.load('device_flow_devices_v28_real', []).length)
  page.on('dialog', (dialog) => dialog.accept())
  try {
    // 1) 无 SN 新建维修单：允许保存，列表显示 SN: -
    await page.locator('.flow-tabs button[data-tab="repairs"]').click()
    await page.locator('#repairs button[onclick="goNew(\'repair\')"]').click()
    await expect(page.locator('#fRSN label')).toContainText('选填')
    await page.locator('#rCustomer').fill('无SN预览客户')
    await page.locator('#rReason').fill('无SN预览故障')
    await page.locator('#newRecord button[onclick="saveRecord()"]').click()
    await expect(page.locator('#newRecord.drawer')).not.toHaveClass(/open/)
    await page.locator('#repairSearch').fill('无SN预览客户')
    await expect(page.locator('#repairTable')).toContainText('SN: -')
    // 不生成虚假设备档案
    expect(await page.evaluate(() => window.flowOnline.load('device_flow_devices_v28_real', []).length)).toBe(devicesBefore)

    // 2) 选择已有设备 SN 建单：关联保留
    await page.locator('#repairSearch').fill('')
    await page.locator('#repairs button[onclick="goNew(\'repair\')"]').click()
    await page.locator('#rSN').fill(existSn)
    await page.locator('#rCustomer').fill('已有SN预览客户')
    await page.locator('#newRecord button[onclick="saveRecord()"]').click()
    await expect(page.locator('#newRecord.drawer')).not.toHaveClass(/open/)
    const deviceStillThere = await page.evaluate((args) => {
      const devs = window.flowOnline.load('device_flow_devices_v28_real', [])
      return devs.some((d: { sn: string }) => d.sn === args.sn)
    }, { sn: existSn })
    expect(deviceStillThere).toBeTruthy()

    // 3) 编辑无 SN 记录 → 保存并生成维修 PDF（先保存后导出）
    await page.locator('#repairSearch').fill('无SN预览客户')
    await page.locator('#repairTable tbody tr').first().locator('button', { hasText: '编辑' }).click()
    await expect(page.locator('#newRecord.drawer')).toHaveClass(/open/)
    await page.locator('#rNotes').fill('无SN预览维修过程')
    const download = page.waitForEvent('download', { timeout: 60000 })
    await page.locator('#newRecord button[onclick="generateRepairPdfFromForm()"]').click()
    const file = await download
    expect(file.suggestedFilename()).toMatch(/^维修工单-.*-无SN预览客户\.pdf$/)
    // 生成 PDF 会先保存：抽屉转为编辑态且不关闭
    await expect(page.locator('#newRecord.drawer')).toHaveClass(/open/)
    await expect(page.locator('#recordTitle')).toContainText('编辑维修工单')

    // 4) 刷新后数据仍在
    await page.reload()
    await page.locator('.device-flow-mount.is-ready').waitFor({ timeout: 15000 })
    await page.waitForTimeout(600)
    if (await page.locator('#dueWarningModal').evaluate((node) => node.classList.contains('open'))) {
      await page.locator('#dueWarningModal button').first().click()
    }
    const saved = await page.evaluate(() => {
      const flow = window.flowOnline
      const r = flow.load('device_flow_records_v28_real', []).find((item: { customer: string }) => item.customer === '无SN预览客户')
      return r ? { sn: r.sn, notes: r.notes } : null
    })
    expect(saved).toBeTruthy()
    expect(saved!.sn || '').toBe('')
    expect(saved!.notes).toBe('无SN预览维修过程')
    // 无 SN 不新建设备；已有 SN 只更新原设备，设备总数不变
    expect(await page.evaluate(() => window.flowOnline.load('device_flow_devices_v28_real', []).length)).toBe(devicesBefore)
    const linked = await page.evaluate((args) => {
      const d = window.flowOnline.load('device_flow_devices_v28_real', []).find((x: { sn: string }) => x.sn === args.sn)
      return d ? d.customer : null
    }, { sn: existSn })
    expect(linked).toBe('已有SN预览客户')
  } finally {
    await page.evaluate(async (args) => {
      const flow = window.flowOnline
      await flow.save(args.key, flow.load(args.key, []).filter((record: { customer: string }) => !['无SN预览客户', '已有SN预览客户'].includes(record.customer)))
      const devices = flow.load('device_flow_devices_v28_real', [])
      const target = devices.find((device: { sn: string }) => device.sn === args.sn)
      if (target) target.customer = args.originalCustomer
      await flow.save('device_flow_devices_v28_real', devices.filter((device: { customer: string }) => !['无SN预览客户', '已有SN预览客户'].includes(device.customer)))
    }, { key: sourceKey, sn: existSn, originalCustomer })
    await page.waitForTimeout(600)
  }
})
