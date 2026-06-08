#!/usr/bin/env python3
"""
Analisa as métricas do MAB Thompson Sampling produzidas por mab_controller.py
e gera tabelas de probabilidade de sucesso/falha por braço.

Lê:
  ./Results/rewards.csv            (1 linha por evento de feedback)
  ./Results/arm_probabilities.csv  (snapshots de alpha/beta por evento)

Produz:
  ./Results/arm_summary.csv               tabela final por braço
  ./Results/success_rate_timeseries.csv   rolling success rate por braço
  ./Results/plots/arm_success_failure.png       (se matplotlib instalado)
  ./Results/plots/arm_alpha_beta_evolution.png  (se matplotlib instalado)
  ./Results/plots/posterior_distributions.png   (se matplotlib + scipy)

Uso:
  python3 analyze_mab.py                       # usa ./Results
  python3 analyze_mab.py --results-dir ./out
  python3 analyze_mab.py --window 50 --no-plots
"""

import argparse
import csv
import os
import sys
from collections import defaultdict

import numpy as np

try:
    from scipy.stats import beta as beta_dist
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False

try:
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


def _safe_float(v, default=None):
    if v is None or v == '':
        return default
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def load_rewards(path):
    if not os.path.exists(path):
        return []

    rows = []
    with open(path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for r in reader:
            ts = _safe_float(r.get('timestamp'))
            reward = _safe_float(r.get('reward'))
            if ts is None or reward is None:
                continue
            rows.append({
                'timestamp': ts,
                'user_id': r.get('user_id', ''),
                'arm': r.get('arm', ''),
                'latency_ms': _safe_float(r.get('latency_ms')),
                'reward': int(reward),
                'alpha_after': _safe_float(r.get('alpha_after')),
                'beta_after': _safe_float(r.get('beta_after')),
            })
    return rows


def load_probabilities(path):
    if not os.path.exists(path):
        return []

    rows = []
    with open(path, 'r', newline='') as f:
        reader = csv.DictReader(f)
        for r in reader:
            rows.append({
                'timestamp': _safe_float(r.get('timestamp')),
                'event': r.get('event', ''),
                'arm': r.get('arm', ''),
                'alpha': _safe_float(r.get('alpha_before')),
                'beta': _safe_float(r.get('beta_before')),
                'sampled_prob': _safe_float(r.get('sampled_prob')),
            })
    return rows


def per_arm_summary(rewards):
    by_arm = defaultdict(
        lambda: {'pulls': 0, 'successes': 0, 'failures': 0, 'latencies': []}
    )

    for r in rewards:
        a = by_arm[r['arm']]
        a['pulls'] += 1
        if r['reward'] == 1:
            a['successes'] += 1
        else:
            a['failures'] += 1
        if r['latency_ms'] is not None and not np.isnan(r['latency_ms']):
            a['latencies'].append(r['latency_ms'])

    summary = []
    for arm, s in sorted(by_arm.items()):
        n = s['pulls']
        succ = s['successes']
        fail = s['failures']
        emp_succ = succ / n if n > 0 else 0.0

        # Posterior Beta(1+succ, 1+fail) com prior uniforme Beta(1,1)
        alpha_post = 1 + succ
        beta_post = 1 + fail
        post_mean = alpha_post / (alpha_post + beta_post)
        post_var = (
            alpha_post * beta_post
            / ((alpha_post + beta_post) ** 2 * (alpha_post + beta_post + 1))
        )

        if HAS_SCIPY and n > 0:
            ci_low, ci_high = beta_dist.interval(
                0.95, alpha_post, beta_post
            )
        else:
            ci_low = ci_high = None

        latencies = s['latencies']
        summary.append({
            'arm': arm,
            'pulls': n,
            'successes': succ,
            'failures': fail,
            'empirical_p_success': round(emp_succ, 4),
            'empirical_p_failure': round(1 - emp_succ, 4),
            'posterior_alpha': alpha_post,
            'posterior_beta': beta_post,
            'posterior_mean_p_success': round(post_mean, 4),
            'posterior_std': round(np.sqrt(post_var), 4),
            'ci95_low': round(ci_low, 4) if ci_low is not None else '',
            'ci95_high': round(ci_high, 4) if ci_high is not None else '',
            'avg_latency_ms': (
                round(float(np.mean(latencies)), 2) if latencies else ''
            ),
            'p50_latency_ms': (
                round(float(np.percentile(latencies, 50)), 2) if latencies else ''
            ),
            'p95_latency_ms': (
                round(float(np.percentile(latencies, 95)), 2) if latencies else ''
            ),
        })
    return summary


def rolling_success_rate(rewards, window=20):
    by_arm = defaultdict(list)
    for r in rewards:
        by_arm[r['arm']].append(r)

    out = []
    for arm, events in by_arm.items():
        events.sort(key=lambda x: x['timestamp'])
        window_buf = []
        for i, e in enumerate(events):
            window_buf.append(e['reward'])
            if len(window_buf) > window:
                window_buf.pop(0)
            rate = sum(window_buf) / len(window_buf)
            out.append({
                'timestamp': e['timestamp'],
                'arm': arm,
                'pull_index': i + 1,
                'rolling_p_success': round(rate, 4),
                'cumulative_pulls': i + 1,
                'cumulative_successes': sum(
                    1 for ev in events[:i + 1] if ev['reward'] == 1
                ),
            })
    out.sort(key=lambda x: x['timestamp'])
    return out


def write_csv(rows, path, columns):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    with open(path, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def plot_success_failure_bar(summary, out_path):
    if not HAS_MPL or not summary:
        return
    arms = [s['arm'] for s in summary]
    p_succ = [s['empirical_p_success'] for s in summary]
    p_fail = [s['empirical_p_failure'] for s in summary]

    x = np.arange(len(arms))
    width = 0.35
    fig, ax = plt.subplots(figsize=(max(7, len(arms) * 1.3), 5))
    ax.bar(x - width / 2, p_succ, width, label='P(sucesso)', color='#2ecc71')
    ax.bar(x + width / 2, p_fail, width, label='P(falha)', color='#e74c3c')

    for i, s in enumerate(summary):
        ax.text(
            i - width / 2, p_succ[i] + 0.01,
            f"{s['successes']}/{s['pulls']}",
            ha='center', fontsize=8,
        )

    ax.set_xlabel('Braço (instância MEC)')
    ax.set_ylabel('Probabilidade empírica')
    ax.set_ylim(0, 1.1)
    ax.set_title('Probabilidade de sucesso/falha por braço')
    ax.set_xticks(x)
    ax.set_xticklabels(arms, rotation=30, ha='right')
    ax.legend()
    ax.grid(axis='y', alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_alpha_beta_evolution(prob_rows, out_path):
    if not HAS_MPL or not prob_rows:
        return

    by_arm = defaultdict(lambda: {'ts': [], 'alpha': [], 'beta': []})
    for r in prob_rows:
        if r['timestamp'] is None or r['alpha'] is None:
            continue
        by_arm[r['arm']]['ts'].append(r['timestamp'])
        by_arm[r['arm']]['alpha'].append(r['alpha'])
        by_arm[r['arm']]['beta'].append(r['beta'])

    if not by_arm:
        return

    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True)
    all_ts = [t for d in by_arm.values() for t in d['ts']]
    if not all_ts:
        return
    t0 = min(all_ts)

    for arm, data in by_arm.items():
        rel = [t - t0 for t in data['ts']]
        ax1.plot(rel, data['alpha'], label=arm, linewidth=1.5)
        ax2.plot(rel, data['beta'], label=arm, linewidth=1.5)

    ax1.set_ylabel('alpha (acumulado de sucessos)')
    ax1.legend(loc='upper left', fontsize=8)
    ax1.grid(alpha=0.3)
    ax2.set_ylabel('beta (acumulado de falhas)')
    ax2.set_xlabel('Tempo (s desde o início)')
    ax2.legend(loc='upper left', fontsize=8)
    ax2.grid(alpha=0.3)
    fig.suptitle('Evolução de alpha/beta por braço ao longo do tempo')
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def plot_posterior_distributions(summary, out_path):
    if not HAS_MPL or not HAS_SCIPY or not summary:
        return

    fig, ax = plt.subplots(figsize=(10, 6))
    x = np.linspace(0, 1, 500)
    for s in summary:
        a = s['posterior_alpha']
        b = s['posterior_beta']
        pdf = beta_dist.pdf(x, a, b)
        label = f"{s['arm']} (α={a}, β={b}, n={s['pulls']})"
        ax.plot(x, pdf, label=label, linewidth=1.8)

    ax.set_xlabel('P(sucesso) — latência ≤ ref')
    ax.set_ylabel('Densidade posterior')
    ax.set_title('Distribuição posterior Beta de cada braço')
    ax.legend(fontsize=8, loc='best')
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=120)
    plt.close(fig)


def print_table(summary):
    if not summary:
        print('(sem dados em rewards.csv)')
        return

    header = (
        f'{"arm":<28} {"pulls":>6} {"succ":>5} {"fail":>5} '
        f'{"P(s)":>6} {"P(f)":>6} {"post.μ":>7} {"CI95_low":>9} {"CI95_hi":>9} '
        f'{"avg_lat":>9}'
    )
    print(header)
    print('-' * len(header))
    for s in summary:
        cil = f'{s["ci95_low"]:.3f}' if s['ci95_low'] != '' else '   -   '
        cih = f'{s["ci95_high"]:.3f}' if s['ci95_high'] != '' else '   -   '
        avg = (
            f'{s["avg_latency_ms"]:.1f}' if s['avg_latency_ms'] != '' else '  -  '
        )
        print(
            f'{s["arm"]:<28} {s["pulls"]:>6} {s["successes"]:>5} {s["failures"]:>5} '
            f'{s["empirical_p_success"]:>6.3f} {s["empirical_p_failure"]:>6.3f} '
            f'{s["posterior_mean_p_success"]:>7.3f} {cil:>9} {cih:>9} {avg:>9}'
        )


def main():
    parser = argparse.ArgumentParser(
        description='Análise de probabilidades do MAB Thompson Sampling',
    )
    parser.add_argument(
        '--results-dir', default='./Results',
        help='Diretório dos CSVs (default: ./Results)',
    )
    parser.add_argument(
        '--window', type=int, default=20,
        help='Janela do rolling success rate (default: 20)',
    )
    parser.add_argument(
        '--no-plots', action='store_true',
        help='Não gerar plots',
    )
    args = parser.parse_args()

    rdir = args.results_dir
    rewards = load_rewards(os.path.join(rdir, 'rewards.csv'))
    probs = load_probabilities(os.path.join(rdir, 'arm_probabilities.csv'))

    if not rewards:
        print(
            f'AVISO: nenhum reward encontrado em {rdir}/rewards.csv',
            file=sys.stderr,
        )

    summary = per_arm_summary(rewards)

    summary_cols = [
        'arm', 'pulls', 'successes', 'failures',
        'empirical_p_success', 'empirical_p_failure',
        'posterior_alpha', 'posterior_beta',
        'posterior_mean_p_success', 'posterior_std',
        'ci95_low', 'ci95_high',
        'avg_latency_ms', 'p50_latency_ms', 'p95_latency_ms',
    ]
    summary_path = os.path.join(rdir, 'arm_summary.csv')
    write_csv(summary, summary_path, summary_cols)
    print(f'[OK] Tabela final por braço: {summary_path}')
    print()
    print_table(summary)

    rolling = rolling_success_rate(rewards, window=args.window)
    rolling_cols = [
        'timestamp', 'arm', 'pull_index',
        'rolling_p_success', 'cumulative_pulls', 'cumulative_successes',
    ]
    rolling_path = os.path.join(rdir, 'success_rate_timeseries.csv')
    write_csv(rolling, rolling_path, rolling_cols)
    print(f'\n[OK] Time series rolling (window={args.window}): {rolling_path}')

    if not args.no_plots:
        if HAS_MPL:
            plot_dir = os.path.join(rdir, 'plots')
            os.makedirs(plot_dir, exist_ok=True)
            plot_success_failure_bar(
                summary, os.path.join(plot_dir, 'arm_success_failure.png'),
            )
            plot_alpha_beta_evolution(
                probs, os.path.join(plot_dir, 'arm_alpha_beta_evolution.png'),
            )
            if HAS_SCIPY:
                plot_posterior_distributions(
                    summary,
                    os.path.join(plot_dir, 'posterior_distributions.png'),
                )
            print(f'[OK] Plots em {plot_dir}/')
        else:
            print('[INFO] matplotlib não instalado — pulando plots. pip install matplotlib')

    if not HAS_SCIPY:
        print('[INFO] scipy não instalado — CIs e plot de posterior pulados. pip install scipy')


if __name__ == '__main__':
    main()
