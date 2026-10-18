"""
Teste de acesso ao site da Caixa a partir do GitHub Actions.

Verifica se a página de downloads abre (sem bloqueio) e lista os links
que mencionam SINAPI. Salva HTML, screenshot e relatório em ./saida/
para inspeção. Não falha o job: o objetivo é só diagnosticar.
"""

import re
import time
from pathlib import Path

PAGE_URL = "https://www.caixa.gov.br/site/Paginas/downloads.aspx"
OUT = Path("saida")
OUT.mkdir(exist_ok=True)
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

relatorio = []


def log(msg):
    print(msg)
    relatorio.append(msg)


# ─── 1. Requisição simples (sem navegador) ───────────────────────────────────

try:
    import requests

    r = requests.get(PAGE_URL, headers={"User-Agent": UA, "Accept-Language": "pt-BR,pt;q=0.9"},
                     timeout=30, allow_redirects=True)
    log(f"[requests] status={r.status_code} url_final={r.url} redirects={len(r.history)} bytes={len(r.content)}")
except Exception as e:
    log(f"[requests] ERRO: {e!r}")

# ─── 2. Navegador real (Playwright) ──────────────────────────────────────────

try:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="pt-BR")
        page = ctx.new_page()
        resp = page.goto(PAGE_URL, wait_until="networkidle", timeout=90000)
        log(f"[playwright] status={resp.status if resp else None} url_final={page.url} titulo={page.title()!r}")
        time.sleep(3)

        # Tenta usar a busca da própria página
        campos = page.locator("input[type='search'], input[type='text']")
        log(f"[playwright] campos de texto encontrados: {campos.count()}")
        for i in range(campos.count()):
            c = campos.nth(i)
            try:
                if c.is_visible():
                    log(f"[playwright] usando campo #{i} (id={c.get_attribute('id')}, placeholder={c.get_attribute('placeholder')})")
                    c.fill("SINAPI")
                    c.press("Enter")
                    page.wait_for_load_state("networkidle", timeout=60000)
                    time.sleep(4)
                    break
            except Exception as e:
                log(f"[playwright] campo #{i} falhou: {e!r}")

        page.screenshot(path=str(OUT / "pagina.png"), full_page=True)
        html = page.content()
        (OUT / "pagina.html").write_text(html, encoding="utf-8")

        links = page.eval_on_selector_all(
            "a[href]", "els => els.map(a => [a.textContent.trim(), a.href])"
        )
        sinapi = [(t, h) for t, h in links if re.search(r"sinapi", t + h, re.I)]
        log(f"[playwright] links totais={len(links)} | links com SINAPI={len(sinapi)}")
        for t, h in sinapi[:60]:
            log(f"   - {t[:90]!r} -> {h}")
        browser.close()
except Exception as e:
    log(f"[playwright] ERRO: {e!r}")

(OUT / "relatorio.txt").write_text("\n".join(relatorio), encoding="utf-8")
