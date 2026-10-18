import pandas as pd
import matplotlib.pyplot as plt

CSV_FILE = "metrics.csv"  # troque pelo nome do seu csv

# Carrega o csv
df = pd.read_csv(CSV_FILE, header=None)

# Filtra apenas linhas do VidProc
df = df[df[1] == "VidProc"].copy()

# Timestamp
df["timestamp"] = pd.to_datetime(df[0])

# Pelo trecho enviado, a avg_latency_ms está na coluna 24
df["avg_latency_ms"] = pd.to_numeric(df[24], errors="coerce")

# Remove valores inválidos
df = df.dropna(subset=["avg_latency_ms"])

# Gráfico
plt.figure(figsize=(12, 6))
plt.plot(
    df["timestamp"],
    df["avg_latency_ms"],
    marker="o"
)

plt.title("Average Latency Over Time")
plt.xlabel("Time")
plt.ylabel("Latency (ms)")
plt.grid(True)

plt.xticks(rotation=45)
plt.tight_layout()

plt.savefig("avg_latency_over_time.png", dpi=300)
plt.show()