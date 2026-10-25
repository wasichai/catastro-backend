// logs into catastro-ui as the dev admin and screenshots the home and one more screen.
// run through driver.sh ui (it puts playwright on NODE_PATH). uses the installed Google Chrome, no browser download
const { chromium } = require('playwright')

const url = process.env.UI_URL ?? 'http://localhost:5181'
const out = process.env.SHOTS ?? '/tmp/catastro-run/shots'
const screen = process.argv[2] ?? 'Mapas'

;(async () => {
    const browser = await chromium.launch({ channel: 'chrome', headless: true })
    const page = await browser.newPage({ viewport: { width: 1440, height: 900 } })
    const errors = []
    // a failed load logs no url to the console: the response listener reports it with one (favicon.ico: the ui has none)
    page.on('console', (m) => m.type() === 'error' && !m.text().startsWith('Failed to load resource') && errors.push(m.text()))
    page.on('response', (r) => r.status() >= 400 && !r.url().endsWith('/favicon.ico') && errors.push(`${r.status()} ${r.url()}`))
    page.on('pageerror', (e) => errors.push(String(e)))
    try {
        await page.goto(url)
        // the email comes prefilled in dev (defaultLoginEmail), fill overwrites it anyway
        await page.getByLabel('Correo').fill('admin@wasichai.local')
        await page.getByLabel('Contraseña').fill('admin')
        await page.getByRole('button', { name: 'Iniciar sesión' }).click()
        await page.getByRole('heading', { name: 'Inicio' }).waitFor({ timeout: 20000 })
        await page.screenshot({ path: `${out}/inicio.png` })
        console.log(`ok login -> ${out}/inicio.png`)

        await page.getByRole('link', { name: screen }).first().click()
        await page.waitForLoadState('networkidle')
        const file = `${out}/${screen.toLowerCase().replace(/\W+/g, '-')}.png`
        await page.screenshot({ path: file })
        console.log(`ok ${screen} (${page.url()}) -> ${file}`)
    } finally {
        await browser.close()
    }
    if (errors.length) {
        console.log(`console errors (${errors.length}):\n  ${errors.join('\n  ')}`)
        process.exitCode = 1
    }
})().catch((e) => {
    console.error(e)
    process.exit(1)
})
