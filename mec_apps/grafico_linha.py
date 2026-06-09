import argparse
import os
import sys

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

CSV_FILE = "rl_input_state.csv"
LATENCY_COL = "avg_avg_latency_ms"  # média da avg_latency_ms entre serviços VidProc
PLATEAU_WINDOW = 70  # nº de amostras iguais consecutivas pra considerar "travado"
TAIL_AFTER_FREEZE = 30  # quantas amostras do platô mostrar depois do congelamento


def detect_freeze_index(series, window):
    """Retorna o índice da PRIMEIRA amostra do platô, ou None se nunca trava.

    Critério: primeira posição i tal que series[i:i+window] são todos iguais.
    """
    vals = series.values
    n = len(vals)
    for i in range(n - window + 1):
        if all(vals[j] == vals[i] for j in range(i, i + window)):
            return i
    return None


def main():
    parser = argparse.ArgumentParser(
        description="Plot da avg_latency_ms cortando o platô para ficar legível."
    )
    parser.add_argument("--csv", default=CSV_FILE, help=f"CSV (default: {CSV_FILE})")
    parser.add_argument(
        "--out", default="avg_latency_transient.png", help="PNG de saída"
    )
    parser.add_argument(
        "--cutoff",
        default=None,
        help="Timestamp manual de corte (ex: '2026-06-09 00:56:00'). "
        "Se omitido, detecta automaticamente o início do platô.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Plota o range completo, sem cortar (igual ao script original).",
    )
    args = parser.parse_args()

    if not os.path.exists(args.csv):
        sys.exit(f"CSV não encontrado: {args.csv}")

    df = pd.read_csv(args.csv)
    df = df[df["app_type"] == "VidProc"].copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df[LATENCY_COL] = pd.to_numeric(df[LATENCY_COL], errors="coerce")
    df = df.dropna(subset=[LATENCY_COL]).sort_values("timestamp").reset_index(drop=True)

    if df.empty:
        sys.exit("Sem dados de latência VidProc.")

    print(f"Amostras VidProc com latência válida: {len(df)}")

    freeze_ts = None
    df_plot = df

    if args.cutoff:
        cutoff_ts = pd.to_datetime(args.cutoff)
        df_plot = df[df["timestamp"] <= cutoff_ts]
        freeze_ts = cutoff_ts
        print(f"Corte manual em {cutoff_ts}: {len(df_plot)} amostras")
    elif not args.full:
        freeze_idx = detect_freeze_index(df[LATENCY_COL], PLATEAU_WINDOW)
        if freeze_idx is not None:
            keep_until = min(freeze_idx + TAIL_AFTER_FREEZE, len(df) - 1)
            df_plot = df.iloc[: keep_until + 1]
            freeze_ts = df.iloc[freeze_idx]["timestamp"]
            print(
                f"Platô detectado em {freeze_ts} (idx={freeze_idx}, valor={df.iloc[freeze_idx][LATENCY_COL]:.2f}ms)"
            )
            print(
                f"Plotando primeiras {len(df_plot)} amostras (até {df_plot.iloc[-1]['timestamp']})"
            )
        else:
            print("Sem platô detectado — plotando série completa.")

    fig, ax = plt.subplots(figsize=(13, 6))
    ax.plot(
        df_plot["timestamp"],
        df_plot[LATENCY_COL],
        marker="o",
        markersize=4,
        linewidth=1.8,
        color="#1f77b4",
        label="Latência média (ms)",
    )

    if freeze_ts is not None and freeze_ts in df_plot["timestamp"].values:
        ax.axvline(
            freeze_ts,
            color="red",
            linestyle="--",
            alpha=0.7,
            label=f"Início do platô ({freeze_ts:%H:%M:%S})",
        )

    ax.set_title("Latência média (ms) — período transitório")
    ax.set_xlabel("Tempo")
    ax.set_ylabel("Latência (ms)")
    ax.grid(True, alpha=0.3)
    ax.legend(loc="best")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
    fig.autofmt_xdate(rotation=30)

    fig.tight_layout()
    fig.savefig(args.out, dpi=200)
    print(f"\nGráfico salvo: {args.out}")


if __name__ == "__main__":
    main()
