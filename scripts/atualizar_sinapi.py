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
    anterior = json.loads(json.dumps(estado))  # cópia, para comparar com o mês anterior
    novidades, erros = [], []  # erros: (periodo ou None, mensagem)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=UA, locale="pt-BR")
            page = ctx.new_page()

            pacotes = listar_pacotes(page)
            print(f"Pacotes encontrados na Caixa: {len(pacotes)} (mais recente: {max(pacotes) if pacotes else '-'})")
            if not pacotes:
                raise RuntimeError("nenhum pacote encontrado na página da Caixa")

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
                    erros.append((per, str(e)))
                    print(f"  ERRO: {e}")

            browser.close()
    except Exception as e:
        erros.append((None, str(e)))
        print(f"ERRO GERAL: {e}")

    if novidades or erros:
        (SAIDA / "titulo.txt").write_text(titulo_aviso(novidades, erros), encoding="utf-8")
        (SAIDA / "novidades.md").write_text(relatorio(novidades, erros, anterior), encoding="utf-8")

    if erros:
        sys.exit(1)


# ─── Aviso por e-mail (issue no GitHub) ──────────────────────────────────────

def titulo_aviso(novidades, erros):
    pers = ", ".join(per for per, *_ in novidades)
    if erros and not novidades:
        return "❌ Robô do SINAPI falhou — veja o que fazer"
    if erros:
        return f"⚠️ SINAPI {pers} gerado, mas houve falhas em outros meses"
    if not all(ok for *_, ok in novidades):
        return f"⚠️ SINAPI {pers} gerado com alertas na validação"
    return f"✅ Novo SINAPI {pers} — JSONs gerados e validados"


def explicar_erro(msg):
    """Traduz o erro técnico em causa provável + o que fazer."""
    m = msg.lower()
    if "nenhum pacote" in m:
        return ("A página da Caixa abriu, mas a lista de relatórios mensais não apareceu. "
                "Provavelmente a Caixa mudou o layout do site ou estava fora do ar.",
                "Nada por enquanto: o robô tenta de novo amanhã. Se repetir por 3 dias seguidos, "
                "peça ao Claude: \"o robô do SINAPI não acha os pacotes, ajuste o atualizar_sinapi.py\".")
    if "timeout" in m or "net::" in m or "http 5" in m:
        return ("O site da Caixa demorou demais ou ficou instável.",
                "Nada: o robô tenta de novo amanhã automaticamente.")
    if "download falhou" in m or "zip válido" in m:
        return ("O link do pacote existe, mas o download não veio completo/correto (a Caixa pode ter bloqueado "
                "ou o arquivo estava sendo substituído).",
                "Nada por enquanto: o robô tenta de novo amanhã. Se repetir, peça ao Claude para investigar.")
    if "referência não encontrada" in m:
        return ("O zip baixou, mas não tinha a planilha SINAPI_Referência — a Caixa mudou o conteúdo do pacote.",
                "Peça ao Claude: \"a Caixa mudou o zip do SINAPI, ajuste o robô\" (o nome dos arquivos está no erro).")
    if "gerar_sinapi_json_v3" in m or "não gerado" in m or "suspeito" in m:
        return ("A planilha foi baixada, mas a geração dos JSONs falhou ou saiu incompleta — "
                "provavelmente a Caixa mudou colunas/abas da planilha.",
                "Peça ao Claude: \"o gerador do SINAPI falhou no mês X, veja o log em dados/logs e ajuste o "
                "gerar_sinapi_json_v3.py\". Os JSONs dos meses anteriores continuam válidos.")
    return ("Erro inesperado.", "Peça ao Claude para olhar o log desta execução no GitHub Actions.")


def mb(caminho):
    return f"{caminho.stat().st_size / 1024 / 1024:.1f} MB" if caminho.exists() else "-"


def relatorio(novidades, erros, anterior):
    repo = os.environ.get("GITHUB_REPOSITORY", "engmiltonjose/miltonjose-sinapi")
    run = os.environ.get("GITHUB_RUN_ID")
    L = []

    if novidades:
        L += ["## ✅ O que deu certo", ""]
        L += ["| Mês | Pacote da Caixa | Composições | Insumos | Validação |", "|---|---|---|---|---|"]
        for per, info, cont, ok in novidades:
            ret = f" — Retificação {info['retificacao']:02d}" if info["retificacao"] else ""
            prev = [p for p in sorted(anterior) if p < per]
            delta = ""
            if prev and "registros" in anterior[prev[-1]]:
                d = cont["composicoes"] - anterior[prev[-1]]["registros"]["composicoes"]
                delta = f" ({d:+d} vs {prev[-1]})"
            L.append(f"| **{per}**{ret} | `{info['pacote']}` | {cont['composicoes']}{delta} | {cont['insumos']} | "
                     f"{'✅ passou' if ok else '⚠️ alertas'} |")

        if any(info["retificacao"] for _, info, *_ in novidades):
            L += ["", "> **Retificação:** a Caixa corrigiu um mês já publicado. Os JSONs desse mês foram "
                  "**substituídos** pela versão corrigida — use os novos."]
        if not all(ok for *_, ok in novidades):
            L += ["", "> **Alertas na validação:** os JSONs foram gerados, mas o validador encontrou "
                  "inconsistências. Veja `dados/logs/validacao-{mês}.txt` ou peça ao Claude para analisar "
                  "antes de usar no Quantify."]

        L += ["", "### Arquivos gerados", ""]
        for per, *_ in novidades:
            for k in ("composicoes", "analitico", "insumos"):
                f = DADOS / f"sinapi-{k}-{per}.json"
                L.append(f"- [`{f.name}`](https://github.com/{repo}/blob/main/dados/{f.name}) ({mb(f)})")

        L += ["", "### O que você precisa fazer", "",
              "- **No Quantify: nada.** A nova base aparece sozinha nos seletores em até ~5 minutos "
              "(o Quantify lê a lista de bases deste repositório e baixa os JSONs pelo CDN).",
              "- **Opcional:** se quiser os JSONs também no seu PC (para as skills Pilar ou uso offline), "
              "peça ao Claude: *\"baixe os JSONs novos do SINAPI do GitHub\"*."]

    if erros:
        L += ["", "## ❌ O que não deu certo", ""]
        for per, msg in erros:
            causa, acao = explicar_erro(msg)
            L += [f"### {'Mês ' + per if per else 'Execução geral'}", "",
                  f"- **Erro técnico:** `{msg}`",
                  f"- **Causa provável:** {causa}",
                  f"- **O que fazer:** {acao}", ""]
        L += ["Os meses que já estavam prontos **não foram afetados**."]

    if run:
        L += ["", f"---", f"Log completo desta execução: https://github.com/{repo}/actions/runs/{run}"]
    return "\n".join(L)


if __name__ == "__main__":
    main()
