"""
Gerador de JSONs SINAPI v3
- CSD/CCD/CSE: lê sem read_only para capturar fórmulas HYPERLINK
- Analítico/ISD: pandas com header=9 (linha 10 da planilha)
"""
import openpyxl, pandas as pd, json, re, os, sys

sys.stdout.reconfigure(encoding='utf-8', errors='replace')

# Uso: python gerar_sinapi_json_v3.py [caminho_xlsx] [sufixo_data]
#   caminho_xlsx  — planilha SINAPI_Referência_*.xlsx de origem (padrão: 2026_01, mantido por compatibilidade)
#   sufixo_data   — se informado (ex: "2026-04"), grava sinapi-*-{sufixo}.json em vez dos nomes sem data
XLSX = sys.argv[1] if len(sys.argv) > 1 else r"c:\Users\molto\CLAUDE CODE\SINAPI_Referência_2026_01.xlsx"
SUFIXO = sys.argv[2] if len(sys.argv) > 2 else ""
OUT  = os.environ.get("SINAPI_OUT", r"c:\Users\molto\CLAUDE CODE")  # no GitHub Actions: SINAPI_OUT=dados

UFS = ["AC","AL","AM","AP","BA","CE","DF","ES","GO","MA",
       "MG","MS","MT","PA","PB","PE","PI","PR","RJ","RN",
       "RO","RR","RS","SC","SE","SP","TO"]

def extract_code(v):
    if isinstance(v, int):
        return str(v) if v != 0 else None
    if isinstance(v, float):
        iv = int(v)
        return str(iv) if iv != 0 else None
    if isinstance(v, str):
        m = re.search(r',\s*(\d{4,7})\s*\)', v)  # captura número 4-7 dígitos no HYPERLINK
        if m:
            return m.group(1)
        v = v.strip()
        if re.fullmatch(r'\d{4,7}', v):
            return v
    return None

def to_float(v):
    import math
    if v is None or (isinstance(v, str) and v.strip() in ('', '-', 'nan')):
        return 0.0
    try:
        r = round(float(str(v).replace(',', '.')), 6)
        return 0.0 if math.isnan(r) or math.isinf(r) else r
    except:
        return 0.0

# ─────────────────────────────────────────────────────────────────────────────
# 1. sinapi-composicoes.json — carrega sem read_only para pegar fórmulas
# ─────────────────────────────────────────────────────────────────────────────
print("Abrindo planilha (sem read_only — aguarde)...")
wb = openpyxl.load_workbook(XLSX, data_only=False)
print("Planilha carregada.")

def ler_comp_openpyxl(sheet_name):
    ws = wb[sheet_name]
    resultado = {}
    DATA_START = 11   # linha 11 em diante (1-indexed)
    max_col = 4 + len(UFS) * 2
    for row in ws.iter_rows(min_row=DATA_START, max_col=max_col, values_only=False):
        cod_cell = row[1].value if len(row) > 1 else None
        codigo   = extract_code(cod_cell)
        if not codigo:
            continue
        grupo    = row[0].value if len(row) > 0 else None
        descricao= row[2].value if len(row) > 2 else None
        unidade  = row[3].value if len(row) > 3 else None
        custos   = []
        for i in range(len(UFS)):
            idx = 4 + i * 2
            v = row[idx].value if idx < len(row) else None
            custos.append(to_float(v))
        resultado[codigo] = {
            'grupo':     str(grupo).strip() if grupo else '',
            'descricao': str(descricao).strip() if descricao else '',
            'unidade':   str(unidade).strip() if unidade else '',
            'custos':    custos,
        }
    return resultado

print("Lendo CSD...")
csd = ler_comp_openpyxl("CSD")
print(f"  CSD: {len(csd)} composicoes")
ex_cod = next(iter(csd))
print(f"  Exemplo: {ex_cod} → {csd[ex_cod]['descricao'][:60]}")

print("Lendo CCD...")
ccd = ler_comp_openpyxl("CCD")
print("Lendo CSE...")
cse = ler_comp_openpyxl("CSE")
wb.close()

composicoes = []
for codigo, dados in csd.items():
    composicoes.append({
        'codigo':    codigo,
        'descricao': dados['descricao'],
        'grupo':     dados['grupo'],
        'unidade':   dados['unidade'],
        'custos': {
            'SD': {UFS[i]: dados['custos'][i] for i in range(len(UFS))},
            'CD': {UFS[i]: ccd[codigo]['custos'][i] if codigo in ccd else 0.0 for i in range(len(UFS))},
            'SE': {UFS[i]: cse[codigo]['custos'][i] if codigo in cse else 0.0 for i in range(len(UFS))},
        },
    })

out1 = os.path.join(OUT, f"sinapi-composicoes{'-'+SUFIXO if SUFIXO else ''}.json")
with open(out1, "w", encoding="utf-8") as f:
    json.dump(composicoes, f, ensure_ascii=False, separators=(",",":"))
sz1 = os.path.getsize(out1) // 1024
print(f"sinapi-composicoes.json: {len(composicoes)} composicoes, {sz1} KB")

# ─────────────────────────────────────────────────────────────────────────────
# 2. sinapi-analitico.json — pandas header=9
# ─────────────────────────────────────────────────────────────────────────────
print("\nLendo Analitico...")
xl = pd.ExcelFile(XLSX, engine="openpyxl")
df_ana = xl.parse("Analítico", header=9, dtype=str)
df_ana = df_ana.iloc[:, :8]
df_ana.columns = ["grupo","cod_comp","tipo","cod_item","descricao","unidade","coef","situacao"]
df_ana = df_ana[df_ana["tipo"].notna() & (df_ana["tipo"].str.strip() != "")]
print(f"  Linhas com itens: {len(df_ana)}")

analitico = {}
for _, row in df_ana.iterrows():
    cod_comp = extract_code(row["cod_comp"])
    cod_item = extract_code(row["cod_item"])
    if not cod_comp or not cod_item:
        continue
    coef = to_float(row["coef"])
    if coef == 0:
        continue
    tipo = str(row["tipo"]).strip().upper()
    tipo = "COMPOSIÇÃO" if "COMPOS" in tipo else "INSUMO"
    analitico.setdefault(cod_comp, []).append({
        "tipo":     tipo,
        "codigo":   cod_item,
        "descricao": str(row["descricao"]).strip() if pd.notna(row["descricao"]) else "",
        "unidade":  str(row["unidade"]).strip() if pd.notna(row["unidade"]) else "",
        "coef":     coef,
        "situacao": str(row["situacao"]).strip() if pd.notna(row["situacao"]) else "",
    })

out2 = os.path.join(OUT, f"sinapi-analitico{'-'+SUFIXO if SUFIXO else ''}.json")
with open(out2, "w", encoding="utf-8") as f:
    json.dump(analitico, f, ensure_ascii=False, separators=(",",":"))
sz2 = os.path.getsize(out2) // 1024
print(f"sinapi-analitico.json: {len(analitico)} composicoes, {sz2} KB")

# quantas composições têm analítico?
match = sum(1 for c in composicoes if c['codigo'] in analitico)
print(f"  Composicoes com analitico: {match}/{len(composicoes)}")

# ─────────────────────────────────────────────────────────────────────────────
# 3. sinapi-insumos.json — pandas header=9
# ─────────────────────────────────────────────────────────────────────────────
def read_ins(sheet_name):
    df = xl.parse(sheet_name, header=9, dtype=str)
    df = df.iloc[:, :5 + len(UFS)]
    df.columns = ["classif","codigo","descricao","unidade","origem"] + list(UFS)
    df = df.dropna(subset=["codigo"])
    df["codigo"] = df["codigo"].apply(lambda x: extract_code(x) or "")
    df = df[df["codigo"] != ""]
    return df

print("\nLendo ISD...")
isd = read_ins("ISD")
print(f"  ISD: {len(isd)} insumos")
print("Lendo ICD...")
icd = read_ins("ICD")
print("Lendo ISE...")
ise = read_ins("ISE")

icd_idx = icd.set_index("codigo")
ise_idx = ise.set_index("codigo")

insumos = {}
for _, row in isd.iterrows():
    cod = str(row["codigo"]).strip()
    if not cod:
        continue
    precos = {"SD": {uf: to_float(row.get(uf)) for uf in UFS}, "CD": {}, "SE": {}}
    if cod in icd_idx.index:
        r2 = icd_idx.loc[cod]
        if isinstance(r2, pd.DataFrame): r2 = r2.iloc[0]
        precos["CD"] = {uf: to_float(r2.get(uf)) for uf in UFS}
    else:
        precos["CD"] = {uf: 0.0 for uf in UFS}
    if cod in ise_idx.index:
        r3 = ise_idx.loc[cod]
        if isinstance(r3, pd.DataFrame): r3 = r3.iloc[0]
        precos["SE"] = {uf: to_float(r3.get(uf)) for uf in UFS}
    else:
        precos["SE"] = {uf: 0.0 for uf in UFS}
    classif_raw = str(row["classif"]).strip() if pd.notna(row["classif"]) else ""
    insumos[cod] = {
        "classif":   classif_raw,
        "descricao": str(row["descricao"]).strip() if pd.notna(row["descricao"]) else "",
        "unidade":   str(row["unidade"]).strip() if pd.notna(row["unidade"]) else "",
        "precos":    precos,
    }

out3 = os.path.join(OUT, f"sinapi-insumos{'-'+SUFIXO if SUFIXO else ''}.json")
with open(out3, "w", encoding="utf-8") as f:
    json.dump(insumos, f, ensure_ascii=False, separators=(",",":"))
sz3 = os.path.getsize(out3) // 1024
print(f"sinapi-insumos.json: {len(insumos)} insumos, {sz3} KB")

# ─────────────────────────────────────────────────────────────────────────────
# Validação
# ─────────────────────────────────────────────────────────────────────────────
print("\n=== VALIDACAO ===")
print(f"composicoes : {len(composicoes):>6}  | {sz1} KB")
print(f"analitico   : {len(analitico):>6}  | {sz2} KB")
print(f"insumos     : {len(insumos):>6}  | {sz3} KB")
print(f"TOTAL                 | {sz1+sz2+sz3} KB")

for cod in ['87262', '74209', '93358']:
    em_c = any(c['codigo'] == cod for c in composicoes)
    em_a = cod in analitico
    print(f"  {cod}: composicoes={em_c}, analitico={em_a}")
    if em_c:
        c = next(c for c in composicoes if c['codigo'] == cod)
        print(f"    SP/SD={c['custos']['SD']['SP']}  grupo={c['grupo']}")
    if em_a:
        print(f"    Itens: {len(analitico[cod])}  | Ex: {analitico[cod][0]}")

print("\nConcluido.")
