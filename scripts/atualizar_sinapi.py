"""
Robô diário do SINAPI.

1. Abre a seção "SINAPI - Relatórios mensais - a partir de 2025" (categoria 888)
   da página de downloads da Caixa e lista os pacotes SINAPI-{ano}-{mes}-formato-xlsx.
2. Compara com dados/estado.json e identifica meses novos ou novas retificações.
3. Para cada pendência: baixa o zip, extrai a planilha SINAPI_Referência,
   roda gerar_sinapi_json_v3.py (3 JSONs em dados/) e o validador.
4. Atualiza dados/estado.json e escreve saida/novidades.md (vira aviso no GitHub).

Variáveis de ambiente opcionais:
  PERIODO_MINIMO     — primeiro mês considerado (padrão 2026-01)
  MAX_POR_EXECUCAO   — limite de meses processados por rodada (padrão 12)
"""

import json
import os
import re
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
LOGS = DADOS / "logs"
SAIDA = RAIZ / "saida"
ESTADO = DADOS / "estado.json"
SCRIPTS = RAIZ / "scripts"

PAGE_URL = "https://www.caixa.gov.br/site/Paginas/downloads.aspx#categoria_888"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)
PADRAO = re.compile(r"SINAPI-(\d{4})-(\d{2})-formato-xlsx(?:_Retificacao(\d+))?\.zip", re.I)
PERIODO_MINIMO = os.environ.get("PERIODO_MINIMO", "2026-01")
MAX_POR_EXECUCAO = int(os.environ.get("MAX_POR_EXECUCAO", "12"))

for d in (DADOS, LOGS, SAIDA):
    d.mkdir(parents=True, exist_ok=True)


def carregar_estado():
    if ESTADO.exists():
        return json.loads(ESTADO.read_text(encoding="utf-8"))
    return {}


def salvar_estado(estado):
    ESTADO.write_text(json.dumps(dict(sorted(estado.items())), ensure_ascii=False, indent=2),
                      encoding="utf-8")


def listar_pacotes(page):
    """Retorna {periodo: {"url", "pacote", "retificacao"}} com a maior retificação de cada mês."""
    page.goto(PAGE_URL, wait_until="networkidle", timeout=90000)
    time.sleep(4)
    try:
        page.click("[data-categoria='888']", timeout=5000)
        time.sleep(3)
    except Exception:
        pass
    hrefs = page.eval_on_selector_all("a[href]", "els => els.map(a => a.href)")
    pacotes = {}
    for h in hrefs:
        m = PADRAO.search(h)
        if not m:
            continue
        periodo = f"{m.group(1)}-{m.group(2)}"
        ret = int(m.group(3) or 0)
        if periodo not in pacotes or ret > pacotes[periodo]["retificacao"]:
            pacotes[periodo] = {"url": h, "pacote": m.group(0), "retificacao": ret}
    return pacotes


def baixar(ctx, url, destino):
    r = ctx.request.get(url, headers={"Referer": PAGE_URL}, timeout=300000)
    if r.status != 200:
        raise RuntimeError(f"download falhou: HTTP {r.status}")
    corpo = r.body()
    if not corpo.startswith(b"PK"):
        raise RuntimeError("o arquivo baixado não é um zip válido")
    destino.write_bytes(corpo)
    return len(corpo)


def extrair_referencia(zip_path, pasta):
    with zipfile.ZipFile(zip_path) as z:
        nomes = [n for n in z.namelist() if re.search(r"Refer.*\.xlsx$", n, re.I)]
        if not nomes:
            raise RuntimeError(f"planilha de Referência não encontrada no zip: {z.namelist()}")
        z.extract(nomes[0], pasta)
        return Path(pasta) / nomes[0]


def processar(ctx, periodo, info):
    with tempfile.TemporaryDirectory() as tmp:
        zip_path = Path(tmp) / info["pacote"]
        tamanho = baixar(ctx, info["url"], zip_path)
        print(f"  baixado {info['pacote']} ({tamanho // 1024 // 1024} MB)")
        xlsx = extrair_referencia(zip_path, tmp)
        print(f"  planilha: {xlsx.name}")

        env = dict(os.environ, SINAPI_OUT=str(DADOS))
        r = subprocess.run([sys.executable, str(SCRIPTS / "gerar_sinapi_json_v3.py"), str(xlsx), periodo],
                           env=env, capture_output=True, text=True, encoding="utf-8", errors="replace")
        (LOGS / f"geracao-{periodo}.txt").write_text(r.stdout + r.stderr, encoding="utf-8")
        if r.returncode != 0:
            raise RuntimeError(f"gerar_sinapi_json_v3.py falhou (veja dados/logs/geracao-{periodo}.txt)")

    arquivos = {k: DADOS / f"sinapi-{k}-{periodo}.json" for k in ("composicoes", "analitico", "insumos")}
    contagens = {}
    for k, f in arquivos.items():
        if not f.exists():
            raise RuntimeError(f"arquivo não gerado: {f.name}")
        dados = json.loads(f.read_text(encoding="utf-8"))
        contagens[k] = len(dados)
        if contagens[k] < 1000:
            raise RuntimeError(f"{f.name} tem só {contagens[k]} registros — suspeito")

    v = subprocess.run([sys.executable, str(SCRIPTS / "validar-sinapi-analitico.py"),
                        str(arquivos["analitico"]), str(arquivos["composicoes"])],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    log_val = v.stdout + v.stderr
    (LOGS / f"validacao-{periodo}.txt").write_text(log_val, encoding="utf-8")
    validacao_ok = "PASSOU" in log_val
    return contagens, validacao_ok


def main():
    from playwright.sync_api import sync_playwright

    estado = carregar_estado()
    novidades, erros = [], []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(user_agent=UA, locale="pt-BR")
        page = ctx.new_page()

        pacotes = listar_pacotes(page)
        print(f"Pacotes encontrados na Caixa: {len(pacotes)} (mais recente: {max(pacotes) if pacotes else '-'})")
        if not pacotes:
            raise SystemExit("Nenhum pacote encontrado — a página da Caixa pode ter mudado.")

        pendentes = [
            per for per in sorted(pacotes)
            if per >= PERIODO_MINIMO
            and (per not in estado or pacotes[per]["retificacao"] > estado[per].get("retificacao", 0))
        ][:MAX_POR_EXECUCAO]
        print(f"Pendentes: {pendentes or 'nenhum'}")

        for per in pendentes:
            info = pacotes[per]
            print(f"\n== {per} ({info['pacote']})")
            try:
                contagens, validacao_ok = processar(ctx, per, info)
                estado[per] = {
                    "pacote": info["pacote"],
                    "retificacao": info["retificacao"],
                    "processado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "registros": contagens,
                    "validacao_passou": validacao_ok,
                }
                salvar_estado(estado)
                novidades.append((per, info, contagens, validacao_ok))
                print(f"  ok: {contagens} | validação {'passou' if validacao_ok else 'com alertas'}")
            except Exception as e:
                erros.append(f"{per}: {e}")
                print(f"  ERRO: {e}")

        browser.close()

    if novidades or erros:
        linhas = ["## Atualização do SINAPI", ""]
        for per, info, cont, ok in novidades:
            ret = f" (Retificação {info['retificacao']:02d})" if info["retificacao"] else ""
            linhas.append(f"- **{per}**{ret}: {cont['composicoes']} composições, {cont['insumos']} insumos — "
                          f"validação {'✅ passou' if ok else '⚠️ com alertas (ver dados/logs)'}")
        if erros:
            linhas += ["", "### Erros", *[f"- {e}" for e in erros]]
        linhas += ["", "Lembrete: atualizar os seletores de base no `quantify.html` (SP_DB / SP_DB_LABELS, "
                   "3× `sp-db-select` e `orc-cfg-database`) e subir os JSONs para o servidor."]
        (SAIDA / "novidades.md").write_text("\n".join(linhas), encoding="utf-8")

    if erros:
        sys.exit(1)


if __name__ == "__main__":
    main()
