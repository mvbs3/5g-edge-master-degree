# Experimento: MAB vs Round Robin

Compara dois controllers de roteamento de UEs sobre um MAPE-K que escala
instâncias VidProc dinamicamente.

## Pré-requisitos (uma vez)

1. Subir o stack inteiro (Core, RAN, MEP, MEC apps, intelligence, catcher, mapeK).
   O jeito mais rápido é rodar `automacao_script.py` opção 1, mas **comente**
   o trecho que dispara as 100 UEs no final — quem cuida disso agora é o
   `run_workload.sh` no container nr_ue.

2. Iniciar o `mec_app_inteligence.py` com a env var **CONTROLLER_TYPE**:
   ```bash
   # Para MAB:
   CONTROLLER_TYPE=mab python3 mec_apps/mec_app_inteligence.py
   # Para Round Robin:
   CONTROLLER_TYPE=rr  python3 mec_apps/mec_app_inteligence.py
   ```
   Sem essa var, o default é `mab`.

3. Rodar o `mapeK.py` (em terminal separado):
   ```bash
   python3 mec_apps/mapeK.py
   ```

## Rodar os 2 experimentos

```bash
# Cenário 1 — MAB
# (mate e reinicie mec_app_inteligence com CONTROLLER_TYPE=mab antes!)
./run_experiment.sh mab

# Cenário 2 — Round Robin
# (mate e reinicie mec_app_inteligence com CONTROLLER_TYPE=rr antes!)
./run_experiment.sh rr
```

Cada experimento dura **60 min** com 5 fases:

| Fase    | Tempo       | UEs          |
|---------|-------------|--------------|
| Warmup  | 0–10 min    | 10 UEs       |
| Ramp    | 10–25 min   | 10 → 100     |
| Peak    | 25–40 min   | 100 sustenta |
| Drain   | 40–55 min   | 100 → 10     |
| Settle  | 55–60 min   | 10 UEs       |

Override de duração:
```bash
DURATION_MIN=30 ./run_experiment.sh mab
```

Os CSVs ficam arquivados em `runs/<scenario>_<timestamp>/` e uma cópia
nomeada vai pra `graficos/rl_input_state_{mab,rr}.csv`.

## Gerar gráficos comparativos

Depois dos 2 experimentos:
```bash
cd graficos
python3 graficos_compare.py
```

Gera em `graficos/relatorio_compare/`:
- `cpu.png`, `memoria.png`, `throughput.png`, `latency.png`, `queue.png`
- `num_instancias.png` — decisões do MAPE-K nos 2 cenários
- `cpu_vs_instancias.png` — CPU sobreposta a nº instâncias por cenário
- `resumo_kpi.csv` — latência média/p50/p95/p99, taxa de violação SLA,
  instance-minutes, número de mudanças de scaling

## Análise do MAB (após cada run)

```bash
cd mec_apps
python3 analyze_mab.py
```
Gera `Results/arm_summary.csv`, `Results/plots/*.png`.
Faz sentido SÓ pro cenário MAB — RR não aprende.

## Tunings já aplicados

- `mapeK.py`: `COOLDOWN_SEC=30` (era 10, evita flapping); `CPU_THRESHOLD_DOWN=8`.
- `MAX_INSTANCES=10`, `MIN_INSTANCES=2` mantidos.

## Bug conhecido — agregador de latência

Em runs longas a `avg_latency_ms` pode congelar num valor exato (vista nos
testes anteriores em 855.91ms por 8h). Provável causa: média acumulada sem
janela deslizante / TTL no `mec_app_metric_catcher.py`. Não bloqueia este
experimento, mas o paper se beneficia se o catcher for migrado pra **janela
deslizante de 60s** ou **histograma com p50/p95**.
