#!/usr/bin/env python3
"""
SISTEMA DE VALIDAO SINAPI
Garante que todas as composies tm seus insumos e que no h inconsistncias.
"""

import json
import sys
from collections import defaultdict

def validar_analitico(arquivo_json, arquivo_composicoes_json=None):
    """
    Valida o arquivo sinapi-analitico.json

    Args:
        arquivo_json: caminho para sinapi-analitico.json
        arquivo_composicoes_json: caminho para sinapi-composicoes.json (opcional)
    """

    print("="*80)
    print("VALIDAO DO SINAPI ANALTICO")
    print("="*80)

    # Load analitico
    try:
        with open(arquivo_json, 'r', encoding='utf-8') as f:
            analitico = json.load(f)
    except Exception as e:
        print(f" ERRO ao carregar {arquivo_json}: {e}")
        return False

    # Load composicoes (se fornecido)
    composicoes = {}
    if arquivo_composicoes_json:
        try:
            with open(arquivo_composicoes_json, 'r', encoding='utf-8') as f:
                comp_data = json.load(f)
                # Se for lista, converta para dict
                if isinstance(comp_data, list):
                    composicoes = {c['codigo']: c for c in comp_data}
                else:
                    composicoes = comp_data
        except Exception as e:
            print(f"  Aviso: No foi possvel carregar {arquivo_composicoes_json}: {e}")

    # Estatsticas
    stats = {
        'total_composicoes': len(analitico),
        'composicoes_com_itens': 0,
        'composicoes_sem_itens': [],
        'composicoes_com_insumos': 0,
        'composicoes_sem_insumos': [],
        'composicoes_so_com_composicoes': [],
        'total_itens': 0,
        'total_insumos': 0,
        'total_composicoes_ref': 0,
        'erros': []
    }

    # Validar cada composio
    for cod_comp, itens in analitico.items():
        if not isinstance(itens, list):
            stats['erros'].append(f"Composio {cod_comp}: valor no  lista")
            continue

        if len(itens) == 0:
            stats['composicoes_sem_itens'].append(cod_comp)
            continue

        stats['composicoes_com_itens'] += 1
        stats['total_itens'] += len(itens)

        # Verificar tipos de itens
        tem_insumo = False
        tem_composicao = False

        for item in itens:
            if not isinstance(item, dict):
                stats['erros'].append(f"Composio {cod_comp}: item no  dict")
                continue

            tipo = item.get('tipo', '')

            # Validar campos obrigatrios
            campos_obrigatorios = ['tipo', 'codigo', 'descricao', 'unidade', 'coef', 'situacao']
            for campo in campos_obrigatorios:
                if campo not in item:
                    stats['erros'].append(f"Composio {cod_comp}, item {item.get('codigo')}: falta campo '{campo}'")

            if tipo == 'INSUMO':
                tem_insumo = True
                stats['total_insumos'] += 1
            elif tipo == 'COMPOSIO':
                tem_composicao = True
                stats['total_composicoes_ref'] += 1

        # Aviso: composio sem insumos
        if not tem_insumo:
            stats['composicoes_sem_insumos'].append(cod_comp)
            if composicoes and cod_comp in composicoes:
                desc = composicoes[cod_comp].get('descricao', '')
                stats['erros'].append(f"  Composio {cod_comp} SEM INSUMOS: {desc[:70]}")
        else:
            stats['composicoes_com_insumos'] += 1

        if tem_composicao and not tem_insumo:
            stats['composicoes_so_com_composicoes'].append(cod_comp)

    # Imprimir relatrio
    print("\nRESUMO ESTATSTICO:")
    print("-"*80)
    print(f"Total de composies: {stats['total_composicoes']}")
    print(f"   Com itens: {stats['composicoes_com_itens']}")
    print(f"   Sem itens: {len(stats['composicoes_sem_itens'])}")
    print(f"\nComposies por tipo de item:")
    print(f"   Com INSUMOS: {stats['composicoes_com_insumos']}")
    print(f"   SEM insumos: {len(stats['composicoes_sem_insumos'])}")
    print(f"   S com composies (sem insumos): {len(stats['composicoes_so_com_composicoes'])}")
    print(f"\nTotal de itens: {stats['total_itens']}")
    print(f"   INSUMOS: {stats['total_insumos']}")
    print(f"   COMPOSIES: {stats['total_composicoes_ref']}")

    # Mostrar problemas encontrados
    if stats['erros']:
        print("\n  PROBLEMAS ENCONTRADOS:")
        print("-"*80)
        for erro in stats['erros'][:50]:  # Mostrar primeiros 50
            print(f"  {erro}")
        if len(stats['erros']) > 50:
            print(f"  ... e mais {len(stats['erros']) - 50} problemas")

    # Verificao especfica
    if '87275' in analitico:
        print("\n VERIFICAO - Composio 87275:")
        print("-"*80)
        itens = analitico['87275']
        print(f"Itens encontrados: {len(itens)}")
        for i, item in enumerate(itens, 1):
            print(f"  {i}. {item.get('tipo', '?'):12} | {item.get('codigo', '?'):6} | {item.get('descricao', '?')[:60]}")

        # Check if ceramic plate is included
        insumo_codes = [item['codigo'] for item in itens if item.get('tipo') == 'INSUMO']
        if '1287' in insumo_codes or '1292' in insumo_codes or '10515' in insumo_codes:
            print("   Cermica/placa encontrada!")
        else:
            print("   FALTA: Placa cermica no encontrada!")
    else:
        print("\n Composio 87275 no encontrada no arquivo!")

    # Resultado final
    print("\n" + "="*80)
    is_valid = len(stats['erros']) == 0 and len(stats['composicoes_sem_insumos']) == 0

    if is_valid:
        print(" VALIDAO PASSOU - Nenhum problema encontrado!")
    else:
        print(" VALIDAO COM PROBLEMAS - Veja os erros acima")

    print("="*80)

    return is_valid

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(f"Uso: python3 {sys.argv[0]} <arquivo.json> [composicoes.json]")
        print(f"\nExemplo:")
        print(f"  python3 {sys.argv[0]} sinapi-analitico.json sinapi-composicoes.json")
        sys.exit(1)

    arquivo_json = sys.argv[1]
    arquivo_comp = sys.argv[2] if len(sys.argv) > 2 else None

    validar_analitico(arquivo_json, arquivo_comp)
