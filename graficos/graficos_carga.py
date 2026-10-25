"""Gráficos da carga oferecida pelas UEs: carga fixa (uniforme) vs carga variável
(perfis leve/médio/pesado dos cenários *_lat).

A carga não é medida, é reconstruída — o workload é determinístico:
  - os horários das fases saem do workload_<cenario>_<ts>.log arquivado em runs/;
  - a ordem de subida/descida das UEs é a do run_workload.sh (UE i sobe no warmup a
    cada 1 s, no ramp a cada ramp_step; no drain morre da 100 para a 11);
  - o perfil de cada UE é o mesmo sorteio do ue_client.py (random.Random(UE_ID)),
    então a UE 37 tem o mesmo perfil no MAB e no RR.

Gera em relatorio_carga/:
  - ues_ativas.png              UEs ativas por perfil ao longo do tempo, com as fases
  - requisicoes.png             Requisições /infer por segundo: carga fixa vs variável
  - demanda_cpu.png             CPU exigida pelas UEs (em instâncias de --cpus 0.20)
                                vs instâncias que o MAPE-K manteve, MAB_lat e RR_lat
  - resumo_carga.csv            UEs por perfil e carga média por fase

Uso:
  python3 graficos_carga.py
  python3 graficos_carga.py --runs ../runs/mab_lat_X ../runs/rr_lat_Y
"""

import argparse
import glob
import os
import random
import re
from datetime import datetime, timedelta

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_RUNS_DIR = os.path.join(_SCRIPT_DIR, '..', 'runs')

# Espelho do ue_client.py — mantenha os dois iguais.
PROFILES = {
    'leve':   {'interval': (0.5, 1.0), 'work_ms': 4},
    'medio':  {'interval': (0.3, 0.6), 'work_ms': 8},
    'pesado': {'interval': (0.2, 0.4), 'work_ms': 12},
}
UNIFORM_INTERVAL = (0.1, 0.5)
INSTANCE_CPU_MS_PER_S = 0.20 * 1000  # --cpus 0.20 do mec_instance_manager.py

PROFILE_COLORS = {'leve': '#8fd18f', 'medio': '#f0b84a', 'pesado': '#d9534f'}
PALETTE = {'MAB': '#1f77b4', 'Round Robin': '#ff7f0e'}
PHASE_NAMES = ['Warmup', 'Ramp', 'Peak', 'Drain', 'Settle']


def profile_of(ue_id):
    sorteio = random.Random(ue_id).random()
    return 'leve' if sorteio < 0.5 else 'medio' if sorteio < 0.8 else 'pesado'


def req_per_s(interval):
    # O /infer leva alguns ms; o sleep domina, então 1/intervalo médio basta.
    return 1.0 / np.mean(interval)


def cpu_ms_per_s(profile):
    p = PROFILES[profile]
    return p['work_ms'] * req_per_s(p['interval'])


def latest_run(scenario):
    runs = sorted(glob.glob(os.path.join(_RUNS_DIR, f'{scenario}_2*')))
    return runs[-1] if runs else None


def parse_workload_log(run_dir):
    """Devolve horários das fases e os parâmetros do workload a partir do log."""
    logs = glob.glob(os.path.join(run_dir, 'workload_*.log'))
    if not logs:
        raise FileNotFoundError(f'sem workload_*.log em {run_dir}')
    csv_path = os.path.join(run_dir, 'rl_input_state.csv')
    first_ts = pd.to_datetime(pd.read_csv(csv_path, usecols=['timestamp'])['timestamp'].iloc[0])

    # O log só tem HH:MM:SS. A data vem do CSV, e cada volta do relógio vira +1 dia.
    times, prev, day = {}, None, first_ts.normalize()
    params = {}
    for line in open(logs[0], errors='ignore'):
        m = re.match(r'\[(\d\d):(\d\d):(\d\d)\] (.*)', line)
        if not m:
            continue
        t = day + timedelta(hours=int(m[1]), minutes=int(m[2]), seconds=int(m[3]))
        if prev is not None and t < prev:
            day += timedelta(days=1)
            t += timedelta(days=1)
        prev = t
        msg = m[4]
        if 'WARMUP_UES=' in msg:
            params = {k: int(v) for k, v in re.findall(r'(\w+)=(\d+)', msg)}
        for key, pattern in [('inicio', '=== INÍCIO'), ('warmup', 'Fase 1/5'), ('ramp', 'Fase 2/5'),
                             ('peak', 'Fase 3/5'), ('drain', 'Fase 4/5'), ('settle', 'Fase 5/5'),
                             ('fim', '=== FIM')]:
            if pattern in msg:
                times[key] = t
        m_drain = re.search(r'matando (\d+) UEs em (\d+)s', msg)
        if m_drain:
            params['drain_step'] = max(1, int(m_drain[2]) // int(m_drain[1]))
    return first_ts, times, params


def ue_intervals(times, params):
    """(ue_id, t_start, t_stop) de cada UE, seguindo a ordem do run_workload.sh."""
    warmup, peak = params['WARMUP_UES'], params['PEAK_UES']
    ramp_step, drain_step = params['ramp_step'], params['drain_step']
    out = []
    for i in range(1, peak + 1):
        if i <= warmup:
            start = times['warmup'] + timedelta(seconds=i - 1)
            stop = times['fim']
        else:
            start = times['ramp'] + timedelta(seconds=(i - warmup - 1) * ramp_step)
            stop = times['drain'] + timedelta(seconds=(peak - i) * drain_step)
        out.append((i, start, stop))
    return out


def load_timeseries(run_dir, heterogeneous):
    """Série a cada 10 s: UEs ativas por perfil, req/s e CPU exigida."""
    first_ts, times, params = parse_workload_log(run_dir)
    ues = ue_intervals(times, params)
    grid = pd.date_range(first_ts, times['fim'], freq='10s')
    rows = []
    for t in grid:
        active = [i for i, a, b in ues if a <= t < b]
        row = {'timestamp': t, 'elapsed_min': (t - first_ts).total_seconds() / 60, 'ues': len(active)}
        if heterogeneous:
            perfis = [profile_of(i) for i in active]
            for p in PROFILES:
                row[p] = perfis.count(p)
            row['req_s'] = sum(req_per_s(PROFILES[p]['interval']) for p in perfis)
            row['cpu_ms_s'] = sum(cpu_ms_per_s(p) for p in perfis)
        else:
            row['req_s'] = len(active) * req_per_s(UNIFORM_INTERVAL)
            row['cpu_ms_s'] = np.nan  # o /infer uniforme só dorme
        rows.append(row)
    df = pd.DataFrame(rows)
    df['instancias_equivalentes'] = df['cpu_ms_s'] / INSTANCE_CPU_MS_PER_S
    phases = {k: (v - first_ts).total_seconds() / 60 for k, v in times.items()}
    return df, phases


def shade_phases(ax, phases):
    bounds = [phases['warmup'], phases['ramp'], phases['peak'], phases['drain'], phases['settle'], phases['fim']]
    for k, (a, b) in enumerate(zip(bounds[:-1], bounds[1:])):
        if k % 2 == 0:
            ax.axvspan(a, b, color='#000', alpha=0.04, linewidth=0)
        ax.text((a + b) / 2, 1.01, PHASE_NAMES[k], transform=ax.get_xaxis_transform(),
                ha='center', va='bottom', fontsize=9, color='#555')


def ues_ativas_plot(df_het, phases, out_dir):
    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.stackplot(df_het['elapsed_min'], *[df_het[p] for p in PROFILES],
                 labels=[f'{p} ({PROFILES[p]["work_ms"]} ms CPU/req)' for p in PROFILES],
                 colors=[PROFILE_COLORS[p] for p in PROFILES], alpha=0.9)
    ax.plot(df_het['elapsed_min'], df_het['ues'], color='#333', linewidth=1.2, label='Total de UEs')
    shade_phases(ax, phases)
    ax.set_title('UEs ativas por perfil de carga (carga variável)', pad=20)
    ax.set_xlabel('Tempo (min)')
    ax.set_ylabel('UEs ativas')
    ax.set_xlim(0, df_het['elapsed_min'].max())
    ax.grid(alpha=0.3)
    ax.legend(loc='upper left')
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, 'ues_ativas.png'), dpi=200)
    plt.close(fig)
    print('  [ok] ues_ativas.png')


def requisicoes_plot(df_fix, df_het, phases, out_dir):
    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.plot(df_fix['elapsed_min'], df_fix['req_s'], color='#555', linewidth=1.8,
            label='Carga fixa (uniforme, 0.1–0.5 s)')
    ax.plot(df_het['elapsed_min'], df_het['req_s'], color='#d9534f', linewidth=1.8,
            label='Carga variável (leve/médio/pesado)')
    shade_phases(ax, phases)
    ax.set_title('Requisições /infer oferecidas pelas UEs', pad=20)
    ax.set_xlabel('Tempo (min)')
    ax.set_ylabel('Requisições/s')
    ax.set_xlim(0, df_het['elapsed_min'].max())
    ax.grid(alpha=0.3)
    ax.legend(loc='upper left')
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, 'requisicoes.png'), dpi=200)
    plt.close(fig)
    print('  [ok] requisicoes.png')


def demanda_cpu_plot(df_het, phases, scenario_csvs, out_dir):
    """Demanda de CPU em instâncias equivalentes vs o que o MAPE-K provisionou."""
    fig, ax = plt.subplots(figsize=(13, 5.5))
    ax.fill_between(df_het['elapsed_min'], df_het['instancias_equivalentes'], color='#d9534f', alpha=0.25,
                    label='CPU exigida pelas UEs (instâncias de 0.20 CPU)')
    for label, csv_path in scenario_csvs.items():
        df = pd.read_csv(csv_path)
        df = df[df['app_type'] == 'VidProc'].copy()
        df['timestamp'] = pd.to_datetime(df['timestamp'])
        df['elapsed_min'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds() / 60
        ax.step(df['elapsed_min'], pd.to_numeric(df['num_services'], errors='coerce'), where='post',
                color=PALETTE[label], linewidth=2, label=f'Instâncias — {label}')
    shade_phases(ax, phases)
    ax.set_title('Demanda de CPU da carga variável vs instâncias do MAPE-K por latência', pad=20)
    ax.set_xlabel('Tempo (min)')
    ax.set_ylabel('Instâncias')
    ax.set_xlim(0, df_het['elapsed_min'].max())
    ax.set_ylim(0, 11)
    ax.grid(alpha=0.3)
    ax.legend(loc='upper left')
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, 'demanda_cpu.png'), dpi=200)
    plt.close(fig)
    print('  [ok] demanda_cpu.png')


def resumo(df_fix, df_het, phases, out_dir):
    bounds = [phases['warmup'], phases['ramp'], phases['peak'], phases['drain'], phases['settle'], phases['fim']]
    rows = []
    for nome, a, b in zip(PHASE_NAMES, bounds[:-1], bounds[1:]):
        fix = df_fix[(df_fix['elapsed_min'] >= a) & (df_fix['elapsed_min'] < b)]
        het = df_het[(df_het['elapsed_min'] >= a) & (df_het['elapsed_min'] < b)]
        rows.append({
            'fase': nome,
            'duracao_min': round(b - a, 1),
            'ues_media': round(het['ues'].mean(), 1),
            'ues_max': int(het['ues'].max()),
            **{f'{p}_max': int(het[p].max()) for p in PROFILES},
            'req_s_fixa': round(fix['req_s'].mean(), 1),
            'req_s_variavel': round(het['req_s'].mean(), 1),
            'cpu_ms_s_variavel': round(het['cpu_ms_s'].mean(), 1),
            'instancias_equivalentes': round(het['instancias_equivalentes'].mean(), 2),
        })
    out = pd.DataFrame(rows)
    out.to_csv(os.path.join(out_dir, 'resumo_carga.csv'), index=False)
    print('  [ok] resumo_carga.csv')
    print('\n=== CARGA POR FASE ===')
    print(out.to_string(index=False))


def main():
    parser = argparse.ArgumentParser(description='Gráficos da carga oferecida pelas UEs')
    parser.add_argument('--fixa', default=None, help='run da carga fixa (default: último runs/mab_2*)')
    parser.add_argument('--variavel', default=None, help='run da carga variável (default: último runs/mab_lat_2*)')
    parser.add_argument('--out', default=os.path.join(_SCRIPT_DIR, 'relatorio_carga'))
    args = parser.parse_args()

    run_fix = args.fixa or latest_run('mab')
    run_het = args.variavel or latest_run('mab_lat')
    if not run_fix or not run_het:
        raise SystemExit('Não achei as runs em runs/ — passe --fixa e --variavel.')
    print(f'Carga fixa:    {run_fix}')
    print(f'Carga variável: {run_het}')

    os.makedirs(args.out, exist_ok=True)
    plt.style.use('seaborn-v0_8-darkgrid')

    df_fix, _ = load_timeseries(run_fix, heterogeneous=False)
    df_het, phases = load_timeseries(run_het, heterogeneous=True)

    ues_ativas_plot(df_het, phases, args.out)
    requisicoes_plot(df_fix, df_het, phases, args.out)
    scenario_csvs = {
        'MAB': os.path.join(_SCRIPT_DIR, 'rl_input_state_mab_lat.csv'),
        'Round Robin': os.path.join(_SCRIPT_DIR, 'rl_input_state_rr_lat.csv'),
    }
    scenario_csvs = {k: v for k, v in scenario_csvs.items() if os.path.exists(v)}
    demanda_cpu_plot(df_het, phases, scenario_csvs, args.out)
    resumo(df_fix, df_het, phases, args.out)
    print(f"\nFinalizado. Gráficos em '{args.out}/'")


if __name__ == '__main__':
    main()
