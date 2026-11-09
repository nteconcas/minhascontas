from playwright.sync_api import sync_playwright

base = "http://127.0.0.1:5055"
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_page(viewport={"width": 1440, "height": 950})
    pg.goto(base + "/", wait_until="networkidle")
    pg.wait_for_timeout(500)
    pg.screenshot(path="shots/login.png", full_page=True)

    pg.goto(base + "/conta/cadastro", wait_until="networkidle")
    pg.wait_for_timeout(400)
    pg.screenshot(path="shots/cadastro.png", full_page=True)

    # cria conta com dados de exemplo
    pg.fill("#full_name", "Maria Silva Santos")
    pg.fill("#email", "maria@exemplo.com")
    pg.fill("#password", "senha1234")
    pg.fill("#confirm_password", "senha1234")
    pg.check("#demo_data")
    pg.check("#terms")
    pg.screenshot(path="shots/cadastro-preenchido.png", full_page=True)
    pg.click("button[type=submit]")
    pg.wait_for_load_state("networkidle")
    pg.wait_for_timeout(1200)
    pg.screenshot(path="shots/dashboard.png", full_page=True)

    pg.goto(base + "/despesas/", wait_until="networkidle")
    pg.wait_for_timeout(400)
    pg.screenshot(path="shots/despesas.png", full_page=True)

    pg.goto(base + "/metas/", wait_until="networkidle")
    pg.wait_for_timeout(800)
    pg.screenshot(path="shots/metas.png", full_page=True)

    pg.goto(base + "/relatorios/", wait_until="networkidle")
    pg.wait_for_timeout(900)
    pg.screenshot(path="shots/relatorios.png", full_page=True)

    pg.goto(base + "/", wait_until="networkidle")
    pg.click("#themeToggle")
    pg.wait_for_timeout(1000)
    pg.reload(wait_until="networkidle")
    pg.wait_for_timeout(1000)
    pg.screenshot(path="shots/dashboard-dark.png", full_page=True)
    pg.click("#themeToggle")
    pg.wait_for_timeout(400)

    m = b.new_page(viewport={"width": 390, "height": 844}, device_scale_factor=2)
    m.goto(base + "/", wait_until="networkidle")
    m.wait_for_timeout(1000)
    m.screenshot(path="shots/mobile.png", full_page=True)
    b.close()
print("ok")
