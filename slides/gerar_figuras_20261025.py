"""Figuras de diagnóstico do MAB para a apresentação de 25/10/2026.

Lê graficos/rl_input_state_{mab_lat,rr_lat}.csv (rodada de 25/10) e grava em
slides/figuras_20261025/:
  - ues_por_instancia.png   UEs na instância mais cheia e instâncias sem UE, MAB vs RR
  - service0_congelada.png  métricas da VideoStreamingService0 no mab_lat: CPU some e a
                            latência repete o mesmo valor enquanto as UEs continuam chegando
"""

import json
import os

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_GRAFICOS = os.path.join(_SCRIPT_DIR, '..', 'graficos')
OUT = os.path.join(_SCRIPT_DIR, 'figuras_20261025')
PALETTE = {'MAB': '#1f77b4', 'Round Robin': '#ff7f0e'}


def load(scenario):
    df = pd.read_csv(os.path.join(_GRAFICOS, f'rl_input_state_{scenario}.csv'))
    df = df[df['app_type'] == 'VidProc'].copy()
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df['elapsed_min'] = (df['timestamp'] - df['timestamp'].iloc[0]).dt.total_seconds() / 60
    return df.reset_index(drop=True)


def distribuicao(df):
    rows = []
    for _, r in df.iterrows():
        ues = json.loads(r['ues_json']) if isinstance(r['ues_json'], str) else {}
        svc = json.loads(r['services_json'])
        contagem = [len(ues.get(k, [])) for k in svc]
        rows.append({
            'elapsed_min': r['elapsed_min'],
            'ues_total': sum(contagem),
            'ues_max': max(contagem) if contagem else 0,
            'ideal': sum(contagem) / len(svc) if svc else 0,
            'ociosas': sum(1 for c in contagem if c == 0),
        })
    return pd.DataFrame(rows)


def ues_por_instancia_plot():
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True)
    for label, scenario in [('MAB', 'mab_lat'), ('Round Robin', 'rr_lat')]:
        d = distribuicao(load(scenario))
        ax1.plot(d['elapsed_min'], d['ues_max'], color=PALETTE[label], linewidth=1.8,
                 label=f'{label} — UEs na instância mais cheia')
        ax2.step(d['elapsed_min'], d['ociosas'], where='post', color=PALETTE[label], linewidth=1.8,
                 label=label)
        if label == 'Round Robin':
            ax1.plot(d['elapsed_min'], d['ideal'], color='#444', linestyle=':', linewidth=1.5,
                     label='Divisão igual (UEs / instâncias)')
    ax1.set_ylabel('UEs')
    ax1.set_title('Distribuição das UEs entre instâncias — carga variável, MAPE-K por latência')
    ax1.legend(loc='upper left')
    ax1.grid(alpha=0.3)
    ax2.set_ylabel('Instâncias sem UE')
    ax2.set_xlabel('Tempo (min)')
    ax2.legend(loc='upper left')
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'ues_por_instancia.png'), dpi=200)
    plt.close(fig)
    print('  [ok] ues_por_instancia.png')


def service0_plot():
    df = load('mab_lat')
    rows = []
    for _, r in df.iterrows():
        m = json.loads(r['services_json']).get('VideoStreamingService0', {})
        ues = json.loads(r['ues_json']) if isinstance(r['ues_json'], str) else {}
        cpu = m.get('cpu_percent(prometheus)')
        lat = m.get('avg_latency_ms')
        rows.append({
            'elapsed_min': r['elapsed_min'],
            'ues': len(ues.get('VideoStreamingService0', [])),
            'cpu': cpu if isinstance(cpu, (int, float)) else np.nan,
            'lat': lat if isinstance(lat, (int, float)) else np.nan,
        })
    d = pd.DataFrame(rows)
    # janela em que a latência repete o mesmo valor por mais de 10 amostras seguidas
    mesmo = d['lat'].diff().eq(0)
    grupos = (~mesmo).cumsum()
    tamanho = mesmo.groupby(grupos).transform('sum')
    congelado = d[mesmo & (tamanho > 10)]

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(13, 7.5), sharex=True)
    ax1.plot(d['elapsed_min'], d['lat'], color=PALETTE['MAB'], linewidth=1.8, label='Latência reportada (ms)')
    ax1.set_ylabel('Latência (ms)')
    ax1_r = ax1.twinx()
    ax1_r.plot(d['elapsed_min'], d['cpu'], color='#2ca02c', linewidth=1.2, label='CPU (%) — lacuna = N/A')
    ax1_r.set_ylabel('CPU (%)')
    ax1_r.set_ylim(0, 25)
    ax1_r.grid(False)
    ax2.step(d['elapsed_min'], d['ues'], where='post', color='#444', linewidth=1.8,
             label='UEs atribuídas pelo MAB')
    ax2.set_ylabel('UEs')
    ax2.set_xlabel('Tempo (min)')
    if not congelado.empty:
        a, b = congelado['elapsed_min'].min(), congelado['elapsed_min'].max()
        for ax in (ax1, ax2):
            ax.axvspan(a, b, color='#d62728', alpha=0.12, linewidth=0)
        ax1.text((a + b) / 2, 0.95, f'métricas congeladas ({b - a:.0f} min)', transform=ax1.get_xaxis_transform(),
                 ha='center', va='top', color='#d62728', fontsize=10)
    ax1.set_title('mab_lat — VideoStreamingService0 para de responder e o MAB continua mandando UEs')
    lines = ax1.get_legend_handles_labels()[0] + ax1_r.get_legend_handles_labels()[0]
    labels = ax1.get_legend_handles_labels()[1] + ax1_r.get_legend_handles_labels()[1]
    ax1.legend(lines, labels, loc='upper left')
    ax1.grid(alpha=0.3)
    ax2.legend(loc='upper left')
    ax2.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT, 'service0_congelada.png'), dpi=200)
    plt.close(fig)
    print('  [ok] service0_congelada.png')


if __name__ == '__main__':
    os.makedirs(OUT, exist_ok=True)
    plt.style.use('seaborn-v0_8-darkgrid')
    ues_por_instancia_plot()
    service0_plot()
