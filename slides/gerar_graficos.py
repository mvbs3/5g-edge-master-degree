"""Gera as figuras da apresentacao a partir do rl_input_state.csv.

Uso:
    python3 slides/gerar_graficos.py

Saida: slides/figuras/*.png
"""

import os

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_PATH = os.path.join(BASE_DIR, "mec_apps", "rl_input_state.csv")
OUT_DIR = os.path.join(BASE_DIR, "slides", "figuras")

CPU_QUOTA_PCT = 20.0  # --cpus=0.20 => teto de 20% de um core
TAU_UP = 10.0
TAU_DOWN = 5.0
SLA_MS = 200.0
FROZEN_MS = 855.91


def load():
    df = pd.read_csv(CSV_PATH, low_memory=False)
    df = df[df["app_type"] == "VidProc"].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce")
    for col in ("num_services", "max_cpu_percent", "avg_avg_latency_ms"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["timestamp"]).sort_values("timestamp")


def fig_instancias(df):
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.step(df["timestamp"], df["num_services"], where="post", lw=2)
    ax.axhline(10, ls="--", c="tab:red", lw=1, label="N_max = 10")
    ax.axhline(2, ls="--", c="tab:green", lw=1, label="N_min = 2")
    ax.set_ylim(0, 11)
    ax.set_ylabel("Instâncias VidProc ativas")
    ax.set_xlabel("Tempo")
    ax.set_title("MAPE-K satura em N_max nos primeiros minutos e nunca desescala")
    ax.grid(alpha=0.3)
    ax.legend(loc="lower right")
    fig.autofmt_xdate()
    save(fig, "instancias_vs_tempo.png")


def fig_cpu(df):
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(df["timestamp"], df["max_cpu_percent"], lw=1.2, label="CPU máx entre instâncias")
    ax.axhline(CPU_QUOTA_PCT, ls="-", c="tab:red", lw=1.5, label="teto da cota (--cpus=0.20 → 20%)")
    ax.axhline(TAU_UP, ls="--", c="tab:orange", lw=1.2, label=f"τ_up = {TAU_UP:.0f}%")
    ax.axhline(TAU_DOWN, ls="--", c="tab:green", lw=1.2, label=f"τ_down = {TAU_DOWN:.0f}%")
    ax.set_ylim(0, 22)
    ax.set_ylabel("CPU (% de um core)")
    ax.set_xlabel("Tempo")
    ax.set_title("As instâncias ficam coladas no teto da própria cota de CPU")
    ax.grid(alpha=0.3)
    ax.legend(loc="center right", fontsize=8)
    fig.autofmt_xdate()
    save(fig, "cpu_teto.png")


def fig_latencia(df):
    fig, ax = plt.subplots(figsize=(10, 4.5))
    ax.plot(df["timestamp"], df["avg_avg_latency_ms"], lw=1.5)
    ax.axhline(FROZEN_MS, ls="--", c="tab:red", lw=1, label=f"valor congelado ({FROZEN_MS} ms)")
    ax.axhline(SLA_MS, ls="--", c="tab:green", lw=1, label=f"SLA = {SLA_MS:.0f} ms")
    ax.set_ylabel("Latência média (ms)")
    ax.set_xlabel("Tempo")
    ax.set_title("Latência congela após ~10 min: métrica inválida (agregador sem TTL)")
    ax.grid(alpha=0.3)
    ax.legend(loc="center right")
    fig.autofmt_xdate()
    save(fig, "latencia_congelada.png")


def save(fig, name):
    os.makedirs(OUT_DIR, exist_ok=True)
    path = os.path.join(OUT_DIR, name)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    print("gerado:", path)


def main():
    df = load()
    print(f"amostras VidProc: {len(df)} | {df['timestamp'].min()} -> {df['timestamp'].max()}")
    fig_instancias(df)
    fig_cpu(df)
    fig_latencia(df)


if __name__ == "__main__":
    main()
