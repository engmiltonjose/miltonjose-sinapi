# miltonjose-sinapi

Robô que verifica todo dia se a Caixa publicou um novo SINAPI e, se sim, gera os JSONs usados no Quantify e nas skills Pilar.

## Como funciona

- **Quando roda:** todo dia às 08:00 (Brasília), ou manualmente em *Actions → SINAPI diário → Run workflow*.
- **Fonte:** seção "SINAPI - Relatórios mensais - a partir de 2025" de `caixa.gov.br/site/Paginas/downloads.aspx#categoria_888`.
- **O que faz:** detecta mês novo (ou nova `_Retificacao`), baixa o pacote `formato-xlsx`, roda `gerar_sinapi_json_v3.py` e o validador.
- **Onde ficam os resultados:** `dados/sinapi-{composicoes|analitico|insumos}-{AAAA-MM}.json`; logs em `dados/logs/`; controle do que já foi processado em `dados/estado.json`.
- **Aviso:** quando há novidade, o robô abre uma *issue* no repositório — o GitHub manda e-mail.

## Arquivos

| Arquivo | Função |
|---|---|
| `scripts/atualizar_sinapi.py` | Robô: lista pacotes, baixa, gera, valida, registra |
| `scripts/gerar_sinapi_json_v3.py` | Cópia do gerador (saída configurável por `SINAPI_OUT`) |
| `scripts/validar-sinapi-analitico.py` | Cópia do validador |
| `scripts/teste_caixa.py` | Diagnóstico de acesso ao site da Caixa |

## Evoluções futuras

- **Cadernos técnicos SINAPI:** extrair também os cadernos técnicos (critérios de medição, itens inclusos, especificações) e associá-los a cada composição, para gerar **memoriais das composições** com as explicações do caderno — no Quantify e nas skills Pilar.
- **Integração com o Quantify:** servir os JSONs direto ao `quantify.html`, sem FTP.
- **Outras bases:** SICRO, ORSE, SEINFRA.
