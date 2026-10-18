"""
Teste de acesso ao site da Caixa a partir do GitHub Actions.

Abre a seção "SINAPI - Relatórios mensais - a partir de 2025" (categoria 888)
da página de downloads, lista os links dos pacotes mensais (formato-xlsx) e
testa se o mais recente pode ser baixado (só o cabeçalho, sem baixar o zip).
Salva HTML, screenshot e relatório em ./saida/ para inspeção.
"""

import re
import time
from pathlib import Path

PAGE_URL = "https://www.caixa.gov.br/site/Paginas/downloads.aspx#categoria_888"
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


try:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="pt-BR", accept_downloads=True)
        page = ctx.new_page()
        resp = page.goto(PAGE_URL, wait_until="networkidle", timeout=90000)
        log(f"[pagina] status={resp.status if resp else None} url_final={page.url}")
        time.sleep(4)

        # Abre o accordion da categoria, se existir
        for sel in ["a[href='#categoria_888']", "[data-categoria='888']", "#categoria_888"]:
            try:
                page.click(sel, timeout=3000)
                log(f"[pagina] clicou em {sel}")
                time.sleep(3)
                break
            except Exception:
                pass

        page.screenshot(path=str(OUT / "pagina.png"), full_page=True)
        (OUT / "pagina.html").write_text(page.content(), encoding="utf-8")

        links = page.eval_on_selector_all(
            "a[href]", "els => els.map(a => [a.textContent.trim(), a.href])"
        )
        mensais = [(t, h) for t, h in links if re.search(r"SINAPI-\d{4}-\d{2}-formato", t + h, re.I)]
        log(f"[links] totais={len(links)} | pacotes mensais={len(mensais)}")
        for t, h in mensais:
            log(f"   - {t[:80]!r} -> {h}")

        xlsx = [h for t, h in mensais if "xlsx" in (t + h).lower()]
        if xlsx:
            alvo = xlsx[0]
            log(f"[download] testando o primeiro xlsx: {alvo}")
            r = ctx.request.get(alvo, headers={"Referer": PAGE_URL, "Range": "bytes=0-1023"},
                                timeout=60000)
            log(f"[download] status={r.status} content-type={r.headers.get('content-type')} "
                f"content-range={r.headers.get('content-range')} content-length={r.headers.get('content-length')}")
            corpo = r.body()
            log(f"[download] primeiros bytes={corpo[:4]!r} (zip valido comeca com b'PK')")
        browser.close()
except Exception as e:
    log(f"[erro] {e!r}")

(OUT / "relatorio.txt").write_text("\n".join(relatorio), encoding="utf-8")
