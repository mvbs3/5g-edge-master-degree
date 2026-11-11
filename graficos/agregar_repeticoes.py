"""Agrega as repetições do experimento: média, desvio e IC 95% por cenário e KPI.

Lê todas as runs em ../runs/<cenario>_AAAAMMDD_HHMMSS/rl_input_state.csv (mab, rr,
mab_lat, rr_lat — as curtas, *_short_*, ficam de fora), calcula os KPIs de cada run com
a mesma função do graficos_compare.py (compute_kpis, incluindo a latência ponderada por
UE) e grava em relatorio_repeticoes/:
  - kpis_por_run.csv        uma linha por run
  - resumo_repeticoes.csv   por cenário e KPI: n, média, desvio, IC 95% (t de Student)

Uso:
  python3 agregar_repeticoes.py                    # todas as runs completas
  python3 agregar_repeticoes.py --desde 20261027   # só runs a partir dessa data
"""

import argparse
import glob
import os
import re

import numpy as np
import pandas as pd

from graficos_compare import compute_kpis, load_scenario

try:
    from scipy import stats
except ImportError:
    stats = None

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNS_DIR = os.path.join(_SCRIPT_DIR, '..', 'runs')

SCENARIOS = {
    'mab': 'MAB · cenário 1 (carga fixa, CPU)',
    'rr': 'Round Robin · cenário 1 (carga fixa, CPU)',
    'mabsem': 'MAB sem teto · cenário 1 (carga fixa, CPU)',
    'mab_lat': 'MAB · cenário 2 (carga variável, latência)',
    'rr_lat': 'Round Robin · cenário 2 (carga variável, latência)',
    'mabsem_lat': 'MAB sem teto · cenário 2 (carga variável, latência)',
    'mab_het': 'MAB · cenário 3 (instâncias heterogêneas, CPU)',
    'rr_het': 'Round Robin · cenário 3 (instâncias heterogêneas, CPU)',
    'mabsem_het': 'MAB sem teto · cenário 3 (instâncias heterogêneas, CPU)',
    'mab_var': 'MAB · cenário 4 (carga variável, CPU)',
    'rr_var': 'Round Robin · cenário 4 (carga variável, CPU)',
    'mabsem_var': 'MAB sem teto · cenário 4 (carga variável, CPU)',
}
RUN_NAME = re.compile(r'^((?:mab|rr|mabsem)(?:_lat|_het|_var)?)_(\d{8})_(\d{6})$')

# KPIs que entram no resumo (os de identificação da run ficam de fora).
KPI_COLS = [
    'lat_media_ms', 'lat_p50_ms', 'lat_p95_ms', 'lat_p99_ms', 'sla_violacao_pct_>200ms',
    'lat_media_pond_ms', 'lat_p95_pond_ms', 'sla_violacao_pond_pct',
    'cpu_media_pct', 'thrput_medio_kbps', 'instancias_media', 'instancias_max',
    'instance_minutes', 'scaling_changes',
]

# t de Student bicaudal 95% para poucos graus de liberdade, caso o scipy não exista.
_T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
        8: 2.306, 9: 2.262, 10: 2.228}


def t95(df):
    if stats is not None:
        return float(stats.t.ppf(0.975, df))
    return _T95.get(df, 1.96)


def find_runs(desde, min_duracao):
    runs = []
    for path in sorted(glob.glob(os.path.join(_RUNS_DIR, '*_2*'))):
        m = RUN_NAME.match(os.path.basename(path))
        if not m:
            continue
        scenario, day, hour = m.groups()
        if desde and day < desde:
            continue
        csv_path = os.path.join(path, 'rl_input_state.csv')
        if not os.path.exists(csv_path):
            print(f"  [skip] {os.path.basename(path)}: sem rl_input_state.csv")
            continue
        runs.append((scenario, f'{day}_{hour}', path, csv_path))
    return runs


def kpis_por_run(runs, min_duracao):
    rows = []
    for scenario, ts, path, csv_path in runs:
        df = load_scenario(csv_path, SCENARIOS[scenario])
        if df is None:
            continue
        kpis = compute_kpis(df, SCENARIOS[scenario])
        if kpis['duracao_min'] < min_duracao:
            print(f"  [skip] {os.path.basename(path)}: {kpis['duracao_min']} min (< {min_duracao}), run incompleta")
            continue
        rows.append({'codigo': scenario, 'run': ts, **kpis})
    return pd.DataFrame(rows)


def resumo(per_run):
    rows = []
    for codigo, sub in per_run.groupby('codigo', sort=False):
        for kpi in KPI_COLS:
            values = sub[kpi].dropna().astype(float)
            n = len(values)
            mean = values.mean() if n else np.nan
            std = values.std(ddof=1) if n > 1 else np.nan
            half = t95(n - 1) * std / np.sqrt(n) if n > 1 else np.nan
            rows.append({
                'codigo': codigo,
                'cenario': SCENARIOS[codigo],
                'kpi': kpi,
                'n': n,
                'media': round(mean, 2),
                'desvio': round(std, 2),
                'ic95_inf': round(mean - half, 2),
                'ic95_sup': round(mean + half, 2),
            })
    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser(description='Agrega as repetições do experimento (média e IC 95%)')
    parser.add_argument('--desde', default=None, help='só runs a partir desta data (AAAAMMDD)')
    parser.add_argument('--min-duracao', type=float, default=50.0,
                        help='descarta runs com menos minutos que isso (default 50)')
    parser.add_argument('--out', default=os.path.join(_SCRIPT_DIR, 'relatorio_repeticoes'))
    args = parser.parse_args()

    runs = find_runs(args.desde, args.min_duracao)
    if not runs:
        raise SystemExit(f"Nenhuma run encontrada em {os.path.abspath(_RUNS_DIR)}"
                         + (f" a partir de {args.desde}" if args.desde else ""))

    print(f"Runs encontradas: {len(runs)}")
    per_run = kpis_por_run(runs, args.min_duracao)
    if per_run.empty:
        raise SystemExit("Nenhuma run completa para agregar.")

    os.makedirs(args.out, exist_ok=True)
    per_run.to_csv(os.path.join(args.out, 'kpis_por_run.csv'), index=False)
    out = resumo(per_run)
    out.to_csv(os.path.join(args.out, 'resumo_repeticoes.csv'), index=False)

    print('\n=== RUNS POR CENÁRIO ===')
    print(per_run.groupby('codigo')['run'].apply(lambda r: ', '.join(r)).to_string())

    # média ± meia-largura do IC, um cenário por coluna
    tabela = out.assign(valor=[
        f"{m:.2f}" if np.isnan(lo) else f"{m:.2f} ± {(hi - lo) / 2:.2f}"
        for m, lo, hi in zip(out['media'], out['ic95_inf'], out['ic95_sup'])
    ]).pivot(index='kpi', columns='codigo', values='valor').reindex(KPI_COLS)
    tabela = tabela[[c for c in SCENARIOS if c in tabela.columns]]
    print('\n=== MÉDIA ± IC 95% (n = nº de runs por cenário) ===')
    print('n:', {k: int(v) for k, v in per_run.groupby('codigo').size().items()})
    print(tabela.to_string())
    print(f"\nFinalizado. Arquivos em '{args.out}/'")


if __name__ == '__main__':
    main()
