"""
Gera dados/manifesto.json — a lista de bases SINAPI disponíveis que o Quantify lê.

Para cada mês em dados/estado.json, registra o commit em que os 3 JSONs daquele mês
foram gravados pela última vez. O Quantify monta a URL do CDN fixada nesse commit:
  https://cdn.jsdelivr.net/gh/<repo>@<commit>/dados/sinapi-<tipo>-<mes>.json
Como o endereço muda a cada nova versão (ex.: retificação), o CDN nunca serve arquivo velho.

Uso: python scripts/gerar_manifesto.py   (rodar DEPOIS de commitar os JSONs)
"""

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DADOS = RAIZ / "dados"
TIPOS = ("composicoes", "analitico", "insumos")


def ultimo_commit_de(*caminhos):
    r = subprocess.run(["git", "log", "-1", "--format=%H", "--", *map(str, caminhos)],
                       cwd=RAIZ, capture_output=True, text=True, check=True)
    return r.stdout.strip()


def main():
    estado = json.loads((DADOS / "estado.json").read_text(encoding="utf-8"))
    bases = []
    for per in sorted(estado, reverse=True):
        arquivos = [DADOS / f"sinapi-{t}-{per}.json" for t in TIPOS]
        if not all(a.exists() for a in arquivos):
            continue
        # commit mais recente que tocou qualquer um dos 3 JSONs: nele os três estão na versão atual
        commit = ultimo_commit_de(*[a.relative_to(RAIZ) for a in arquivos])
        if not commit:
            raise SystemExit(f"{per}: JSONs ainda não commitados")
        info = estado[per]
        bases.append({
            "data": per,
            "commit": commit,
            "pacote": info.get("pacote", ""),
            "retificacao": info.get("retificacao", 0),
            "validacao_passou": info.get("validacao_passou"),
        })
    caminho = DADOS / "manifesto.json"
    anterior = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
    if anterior.get("bases") == bases:
        print(f"manifesto sem mudanças ({len(bases)} bases)")
        return
    manifesto = {
        "atualizado_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mais_recente": bases[0]["data"] if bases else None,
        "bases": bases,
    }
    caminho.write_text(json.dumps(manifesto, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"manifesto: {len(bases)} bases, mais recente {manifesto['mais_recente']}")


if __name__ == "__main__":
    main()
