"""Gráficos comparativos MAB vs Round Robin a partir de:
  - rl_input_state_mab.csv
  - rl_input_state_rr.csv
(produzidos pelo run_experiment.sh em ../run_experiment.sh, copiados pra cá.)

Gera em relatorio_compare/:
  - cpu.png                 CPU média ao longo do tempo (MAB vs RR)
  - memoria.png             Memória (%)
  - throughput.png          Throughput (Kbps)
  - num_instancias.png      Número de instâncias (decisões do MAPE-K)
  - latency.png             Latência média (avg_avg_latency_ms)
  - queue.png               Tamanho da fila
  - cpu_vs_instancias.png   CPU sobreposta a nº instâncias, separado por cenário
  - resumo_kpi.csv          KPIs comparativos: latência média/p95, SLA violation,
                            instance-hours, oscilações de scaling.
"""

import argparse
import os
import sys

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns


SLA_LATENCY_MS = 200.0  # limite de violação pra KPI

NUMERIC_COLS = [
    'avg_cpu_percent', 'max_cpu_percent', 'min_cpu_percent',
    'avg_memory_percent', 'max_memory_percent', 'min_memory_percent',
    'avg_memory_used_mb', 'max_memory_used_mb', 'min_memory_used_mb',
    'avg_queue_size', 'max_queue_size', 'min_queue_size',
    'avg_network_rx_kbps', 'max_network_rx_kbps', 'min_network_rx_kbps',
    'avg_network_tx_kbps', 'max_network_tx_kbps', 'min_network_tx_kbps',
    'avg_throughput_kbps', 'max_throughput_kbps', 'min_throughput_kbps',
    'avg_avg_latency_ms', 'max_avg_latency_ms', 'min_avg_latency_ms',
    'num_services',
]

SCENARIO_FILES = {
    'MAB':         'rl_input_state_mab.csv',
    'Round Robin': 'rl_input_state_rr.csv',
}

PALETTE = {
    'MAB': '#1f77b4',
    'Round Robin': '#ff7f0e',
}


def load_scenario(csv_path, label):
    if not os.path.exists(csv_path):
        print(f"AVISO: {csv_path} não encontrado — pulando '{label}'")
        return None
    df = pd.read_csv(csv_path)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df = df[df['app_type'] == 'VidProc'].copy()
    if df.empty:
        print(f"AVISO: '{label}' não tem amostras VidProc")
        return None
    df = df.sort_values('timestamp').reset_index(drop=True)
    df['scenario'] = label
    df['elapsed_min'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds() / 60
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        else:
            df[col] = np.nan
    print(f"  '{label}': {len(df)} amostras, duração {df['elapsed_min'].max():.1f} min")
    return df


def line_plot(df_combined, metric, title, ylabel, fname, out_dir, ylim=None):
    if df_combined[metric].dropna().empty:
        print(f"  [skip] {fname}: sem dados em {metric}")
        return
    fig, ax = plt.subplots(figsize=(13, 6))
    for label, sub in df_combined.groupby('scenario', sort=False):
        ax.plot(sub['elapsed_min'], sub[metric],
                label=label, color=PALETTE.get(label), linewidth=1.8)
    ax.set_title(title)
    ax.set_xlabel('Tempo (min)')
    ax.set_ylabel(ylabel)
    if ylim:
        ax.set_ylim(ylim)
    ax.grid(alpha=0.3)
    ax.legend(title='Cenário')
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, fname), dpi=200)
    plt.close(fig)
    print(f"  [ok] {fname}")


def num_instances_plot(df_combined, out_dir):
    if df_combined['num_services'].dropna().empty:
        return
    fig, ax = plt.subplots(figsize=(13, 5))
    for label, sub in df_combined.groupby('scenario', sort=False):
        ax.step(sub['elapsed_min'], sub['num_services'], where='post',
                label=label, color=PALETTE.get(label), linewidth=2)
    ax.set_title('Decisões do MAPE-K — instâncias VidProc ao longo do tempo')
    ax.set_xlabel('Tempo (min)')
    ax.set_ylabel('Número de instâncias')
    max_n = df_combined['num_services'].max()
    ax.set_yticks(np.arange(0, int(max_n) + 2, 1))
    ax.grid(alpha=0.3)
    ax.legend(title='Cenário')
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, 'num_instancias.png'), dpi=200)
    plt.close(fig)
    print("  [ok] num_instancias.png")


def cpu_vs_instances_plot(df_combined, out_dir):
    scenarios = df_combined['scenario'].unique()
    if len(scenarios) == 0:
        return
    fig, axes = plt.subplots(len(scenarios), 1, figsize=(13, 5 * len(scenarios)),
                             sharex=True)
    if len(scenarios) == 1:
        axes = [axes]

    for ax_left, label in zip(axes, scenarios):
        sub = df_combined[df_combined['scenario'] == label]
        color = PALETTE.get(label, '#444')
        ax_left.plot(sub['elapsed_min'], sub['avg_cpu_percent'],
                     color=color, linewidth=1.8, label='CPU média (%)')
        ax_left.set_ylabel('CPU (%)', color=color)
        ax_left.tick_params(axis='y', labelcolor=color)
        ax_left.set_ylim(0, max(50, sub['avg_cpu_percent'].max() * 1.1 if sub['avg_cpu_percent'].notna().any() else 50))
        ax_left.set_title(f'{label} — CPU vs nº instâncias')
        ax_left.grid(alpha=0.3)

        ax_right = ax_left.twinx()
        ax_right.step(sub['elapsed_min'], sub['num_services'], where='post',
                      color='#666', linestyle='--', linewidth=1.5, label='Instâncias')
        ax_right.set_ylabel('Instâncias', color='#666')
        ax_right.tick_params(axis='y', labelcolor='#666')
        ax_right.set_ylim(0, df_combined['num_services'].max() + 1)

    axes[-1].set_xlabel('Tempo (min)')
    fig.tight_layout()
    fig.savefig(os.path.join(out_dir, 'cpu_vs_instancias.png'), dpi=200)
    plt.close(fig)
    print("  [ok] cpu_vs_instancias.png")


def kpi_table(df_combined, out_dir):
    """Computa KPIs comparativos."""
    rows = []
    for label, sub in df_combined.groupby('scenario', sort=False):
        lat = sub['avg_avg_latency_ms'].dropna()
        n_svc = sub['num_services'].dropna()
        elapsed_min = sub['elapsed_min'].max()

        if not lat.empty:
            sla_pct = float((lat > SLA_LATENCY_MS).mean() * 100)
        else:
            sla_pct = float('nan')

        if not n_svc.empty and elapsed_min > 0:
            instance_hours = float(np.trapz(n_svc, sub['elapsed_min']) / 60.0)
        else:
            instance_hours = float('nan')

        scaling_changes = int((n_svc.diff().fillna(0) != 0).sum()) if not n_svc.empty else 0

        rows.append({
            'cenario': label,
            'amostras': len(sub),
            'duracao_min': round(elapsed_min, 1),
            'lat_media_ms': round(lat.mean(), 2) if not lat.empty else float('nan'),
            'lat_p50_ms': round(lat.quantile(0.50), 2) if not lat.empty else float('nan'),
            'lat_p95_ms': round(lat.quantile(0.95), 2) if not lat.empty else float('nan'),
            'lat_p99_ms': round(lat.quantile(0.99), 2) if not lat.empty else float('nan'),
            f'sla_violacao_pct_>{int(SLA_LATENCY_MS)}ms': round(sla_pct, 2),
            'cpu_media_pct': round(sub['avg_cpu_percent'].mean(), 2),
            'thrput_medio_kbps': round(sub['avg_throughput_kbps'].mean(), 2),
            'instancias_media': round(n_svc.mean(), 2) if not n_svc.empty else float('nan'),
            'instancias_max': int(n_svc.max()) if not n_svc.empty else 0,
            'instance_minutes': round(instance_hours * 60, 1),
            'scaling_changes': scaling_changes,
        })

    out = pd.DataFrame(rows)
    path = os.path.join(out_dir, 'resumo_kpi.csv')
    out.to_csv(path, index=False)
    print(f"  [ok] resumo_kpi.csv")
    print('\n=== KPI COMPARATIVO ===')
    print(out.to_string(index=False))
    return out


def main():
    parser = argparse.ArgumentParser(
        description='Gera gráficos comparativos MAB vs Round Robin'
    )
    parser.add_argument('--out', default='relatorio_compare', help='Diretório de saída')
    args = parser.parse_args()

    os.makedirs(args.out, exist_ok=True)
    plt.style.use('seaborn-v0_8-darkgrid')
    sns.set_palette('tab10')

    print("Carregando cenários...")
    dfs = []
    for label, path in SCENARIO_FILES.items():
        df = load_scenario(path, label)
        if df is not None:
            dfs.append(df)

    if not dfs:
        sys.exit("Nenhum CSV de cenário encontrado. Rode os experimentos primeiro:\n"
                 "  ./run_experiment.sh mab\n"
                 "  ./run_experiment.sh rr")

    df_combined = pd.concat(dfs, ignore_index=True)
    print(f"\nGerando gráficos em '{args.out}/':")

    line_plot(df_combined, 'avg_cpu_percent',
              'Uso de CPU médio (MAB vs Round Robin)', 'CPU (%)',
              'cpu.png', args.out, ylim=(0, 100))

    line_plot(df_combined, 'avg_memory_percent',
              'Uso de memória médio', 'Memória (%)',
              'memoria.png', args.out, ylim=(0, 100))

    line_plot(df_combined, 'avg_throughput_kbps',
              'Throughput médio', 'Throughput (Kbps)',
              'throughput.png', args.out)

    line_plot(df_combined, 'avg_avg_latency_ms',
              'Latência média (avg_avg_latency_ms)', 'Latência (ms)',
              'latency.png', args.out)

    line_plot(df_combined, 'avg_queue_size',
              'Tamanho da fila médio', 'Tamanho da fila',
              'queue.png', args.out)

    num_instances_plot(df_combined, args.out)
    cpu_vs_instances_plot(df_combined, args.out)
    kpi_table(df_combined, args.out)

    print(f"\nFinalizado. Gráficos em '{args.out}/'")


if __name__ == '__main__':
    main()
