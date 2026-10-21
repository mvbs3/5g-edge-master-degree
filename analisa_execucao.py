#!/usr/bin/env python3
"""Veredito automático sobre uma execução: o ciclo de vida de UEs e instâncias fechou?

Uso:
    python3 analisa_execucao.py graficos/rl_input_state_mab_short.csv
    python3 analisa_execucao.py graficos/rl_input_state_mab.csv

Existe porque as três perguntas que importam depois de uma execução — as instâncias
desceram? as UEs voltaram? o workload completou as fases? — não se respondem olhando
o gráfico: a curva fica plana tanto quando está tudo certo e estável quanto quando o
drain nunca rodou. Aqui elas viram PASSOU/FALHOU com o número do lado.
"""

import argparse
import csv
import json
import sys
from datetime import datetime

TS_FORMAT = "%Y-%m-%d %H:%M:%S"
APP_TYPE = "VidProc"


def carregar(caminho):
    pontos = []
    vazios = 0
    with open(caminho) as f:
        for linha in csv.DictReader(f):
            if linha.get("app_type") != APP_TYPE:
                continue
            try:
                ts = datetime.strptime(linha["timestamp"], TS_FORMAT)
                instancias = int(linha["num_services"])
            except (KeyError, ValueError):
                continue

            bruto = (linha.get("ues_json") or "").strip()
            if bruto in ("", "{}"):
                vazios += 1
            try:
                ues_por_servico = json.loads(bruto or "{}")
            except json.JSONDecodeError:
                ues_por_servico = {}

            ues = set()
            for lista in ues_por_servico.values():
                if isinstance(lista, list):
                    ues.update(lista)

            pontos.append({"ts": ts, "instancias": instancias, "ues": len(ues)})
    return pontos, vazios


def transicoes(valores):
    return [
        (i, valores[i - 1], valores[i])
        for i in range(1, len(valores))
        if valores[i] != valores[i - 1]
    ]


def formata(ok):
    return "PASSOU" if ok else "FALHOU"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("csv", help="rl_input_state_*.csv da execução")
    parser.add_argument("--warmup-ues", type=int, default=10,
                        help="UEs da fase de warmup/settle (default: 10)")
    parser.add_argument("--tolerancia-ues", type=int, default=5,
                        help="folga aceita ao comparar as UEs finais com o warmup")
    args = parser.parse_args()

    pontos, vazios = carregar(args.csv)
    if not pontos:
        print(f"ERRO: nenhuma linha {APP_TYPE} em {args.csv}")
        return 2

    inicio, fim = pontos[0]["ts"], pontos[-1]["ts"]
    duracao_min = (fim - inicio).total_seconds() / 60
    inst = [p["instancias"] for p in pontos]
    ues = [p["ues"] for p in pontos]

    print(f"Arquivo:  {args.csv}")
    print(f"Janela:   {inicio} -> {fim}  ({duracao_min:.1f} min, {len(pontos)} amostras)")

    # ues_json só lista UEs JÁ ATRIBUÍDAS a uma instância. Se a maior parte das linhas
    # vier vazia, a contagem de UEs abaixo não mede a carga real e as verificações 2 e
    # 3 não têm valor — melhor dizer isso do que devolver um veredito errado.
    pct_vazio = 100 * vazios / len(pontos)
    ues_confiavel = pct_vazio < 50
    if not ues_confiavel:
        print(f"\nAVISO: {pct_vazio:.0f}% das amostras têm ues_json vazio.")
        print("       As UEs só aparecem aqui depois de atribuídas a uma instância,")
        print("       então as verificações 2 e 3 vão ser puladas. Causas prováveis:")
        print("       o roteador não atribuiu as UEs, ou a carga não chegou ao MEC.")
    print()

    # ---- 1. o pool desceu? ----
    mudancas = transicoes(inst)
    subidas = sum(1 for _, a, b in mudancas if b > a)
    descidas = sum(1 for _, a, b in mudancas if b < a)
    pico_inst = max(inst)
    tempo_no_pico = 100 * sum(1 for v in inst if v == pico_inst) / len(inst)
    ok_descida = descidas > 0

    print(f"[{formata(ok_descida)}] 1. O pool VidProc desceu")
    print(f"          {subidas} subida(s), {descidas} descida(s)")
    print(f"          pico={pico_inst}, {tempo_no_pico:.1f}% das amostras no pico")
    if not ok_descida:
        print("          -> nenhum SCALE_DOWN: confira o sinal de CPU (avg vs max)")
        print("             e se o mec_app_inteligence foi reiniciado")

    # ---- 2. as UEs voltaram? ----
    if not ues_confiavel:
        print("\n[PULADO] 2. As UEs voltaram ao nível de warmup (ues_json vazio demais)")
        print("[PULADO] 3. A carga tem forma de corcova (ues_json vazio demais)")
        print("\n" + "=" * 60)
        print(f"RESULTADO: só a verificação 1 pôde ser avaliada ({formata(ok_descida)})")
        print("=" * 60)
        return 0 if ok_descida else 1

    pico_ues = max(ues)
    ues_final = ues[-1]
    alvo = args.warmup_ues + args.tolerancia_ues
    ok_ues = pico_ues > args.warmup_ues and ues_final <= alvo

    print(f"\n[{formata(ok_ues)}] 2. As UEs voltaram ao nível de warmup")
    print(f"          pico={pico_ues}, final={ues_final} (esperado <= {alvo})")
    if pico_ues <= args.warmup_ues:
        print("          -> a rampa não aconteceu: o workload subiu as UEs?")
    elif ues_final > alvo:
        print("          -> o drain não completou, ou o settle acabou antes do")
        print("             INACTIVITY_TIMEOUT (30s) remover as UEs mortas")

    # ---- 3. o formato da curva ----
    idx_pico = ues.index(pico_ues)
    pos_pico = 100 * idx_pico / len(ues)
    ok_formato = 10 < pos_pico < 90

    print(f"\n[{formata(ok_formato)}] 3. A carga tem forma de corcova")
    print(f"          pico das UEs em {pos_pico:.0f}% da execução")
    if pos_pico >= 90:
        print("          -> o pico está no fim: execução cortada antes do drain")
    elif pos_pico <= 10:
        print("          -> rampa rápida demais: confira as PHASE_*_SEC no log")

    # ---- resumo ----
    print("\n" + "=" * 60)
    todos = [ok_descida, ok_ues, ok_formato]
    if all(todos):
        print("RESULTADO: ciclo de vida completo — as correções funcionaram")
    else:
        print(f"RESULTADO: {sum(todos)}/3 verificações passaram")
        print("Mande este output junto com runs/*/workload_*.log e logs/mapeK_*.log")
    print("=" * 60)

    return 0 if all(todos) else 1


if __name__ == "__main__":
    sys.exit(main())
