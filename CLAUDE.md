# CLAUDE.md

Contexto do projeto de mestrado para sessões do Claude Code abertas nesta pasta.

## Objetivo

Comparar dois roteadores de tráfego em um MEC 5G com auto-scaling: **MAB (Thompson
Sampling) vs Round Robin**, decidindo qual instância MEC atende cada UE, sobre um loop
**MAPE-K** que escala instâncias VidProc dinamicamente.

Métricas do paper: latência média/p50/p95/p99, % de violação de SLA (> 200 ms),
instance-minutes (custo) e número de scaling changes (estabilidade).

Documentos de referência no repo — **leia antes de mudar qualquer coisa**:

- `EXPERIMENTO.md` — como rodar os dois cenários, fases da carga, tunings aplicados
- `EXPERIMENTO_DESCRICAO.txt` — descrição completa: o que as UEs requisitam, vazão por
  UE, agregados no peak, justificativa numérica
- `algoritmos_experimento.tex` — pseudocódigo dos algoritmos para o texto da dissertação

## Arquitetura

```
100 UEs (UERANSIM) → 1 gNB → Open5GS Core → MEC Platform (MEP)
                                                │
                                   ┌────────────┴────────────┐
                                   ↓                         ↓
                         MEC Intelligence              Service Registry
                         (MAB ou RR roteia)
                                   ↓
                     Pool de VidProc (2-10 instâncias auto-scaled)
                         ↑                                ↑
                         └─ MAPE-K monitora CPU max ──────┘
                            (UP > 10%, DOWN < 5%)
```

| Pasta / arquivo | Papel |
|---|---|
| `5g_core/` | Open5GS (SA deploy, Makefile, confs) |
| `5g_ran/` | UERANSIM — gNB (`docker-compose-ran.yaml`) e UEs (`docker-compose-nrue.yaml`) |
| `5g_mep/` | MEC Platform e Config Manager |
| `mec_apps/` | Aplicações e controle: ver tabela abaixo |
| `prometheus/` | Coleta de métricas consumida pelo catcher |
| `graficos/` | `graficos.py` (um cenário), `graficos_compare.py` (MAB vs RR) |
| `automacao_script.py` | Sobe/derruba o stack inteiro (opção 1 = subir tudo) |
| `run_experiment.sh` | Roda um cenário completo: `./run_experiment.sh {mab,rr}` |
| `mec_instance_manager.py` | Cria/mata instâncias VidProc (limite `--cpus=0.20`) |

Dentro de `mec_apps/`:

| Arquivo | Papel |
|---|---|
| `mec_app_inteligence.py` | Roteia UE → instância; escolhe controller via `CONTROLLER_TYPE` |
| `mab_controller.py` | Thompson Sampling |
| `rr_controller.py` | Baseline round-robin, mesma interface pública do MAB |
| `mapeK.py` | Loop MAPE-K de scale up/down |
| `mec_app_metric_catcher.py` | Recebe `/latency` e `/app_metrics`, agrega e escreve o CSV |
| `analyze_mab.py` | Análise dos braços (só faz sentido no cenário MAB) |

## Como rodar

```bash
# 1. subir o stack (comente o trecho que dispara as 100 UEs — quem faz isso é o
#    run_workload.sh dentro do container nr_ue)
python3 automacao_script.py        # opção 1

# 2. intelligence com o controller do cenário (default é mab)
CONTROLLER_TYPE=mab python3 mec_apps/mec_app_inteligence.py
CONTROLLER_TYPE=rr  python3 mec_apps/mec_app_inteligence.py

# 3. MAPE-K em outro terminal
python3 mec_apps/mapeK.py

# 4. o cenário (60 min: warmup → ramp → peak → drain → settle)
./run_experiment.sh mab
DURATION_MIN=30 ./run_experiment.sh rr    # override de duração

# 5. comparação
cd graficos && python3 graficos_compare.py
```

Ao trocar de cenário é obrigatório **matar e reiniciar** o `mec_app_inteligence.py` com o
novo `CONTROLLER_TYPE` — ele não troca de controller em runtime.

Saídas: CSVs arquivados em `runs/<scenario>_<timestamp>/`, cópia em
`graficos/rl_input_state_{mab,rr}.csv`, gráficos em `graficos/relatorio_compare/`.

## Parâmetros que importam

| Parâmetro | Valor | Onde |
|---|---|---|
| `CPU_THRESHOLD_UP` / `DOWN` | 10 / 5 | `mapeK.py` |
| `MIN_INSTANCES` / `MAX_INSTANCES` | 2 / 10 | `mapeK.py` |
| `COOLDOWN_SEC` | 30 (era 10, causava flapping) | `mapeK.py` |
| `POLLING_INTERVAL` | 5 s | `mapeK.py` |
| Limite de CPU por instância | `--cpus=0.20` | `mec_instance_manager.py` |
| SLA de latência | 200 ms | métricas do paper |
| Latência simulada do `/infer` | `sleep(0.05–0.2)` | `mec_app1.py` |
| Carga por UE | 2 threads: POST `/infer` a cada 0.1–0.5 s + GET `/video` contínuo | `ue_client.py` |

## Estado (14/09/2026)

- Último commit: `68a6015` "corrigindo a escrita no csv", de 15/06/2026. Árvore limpa.
- `mec_apps/rl_input_state.csv` tem dados de 09/06/2026 (~5.9k linhas).
- **Não existe pasta `runs/`** — os dois cenários de 60 min do protocolo atual
  aparentemente ainda não rodaram (ou rodaram sem arquivar).
- O bug do platô de latência **já tem correção implementada**: `_purge_stale_latencies`
  com `LATENCY_TTL_SEC` no `mec_app_metric_catcher.py` remove amostras velhas, que era a
  causa do valor travado em 855.91 ms por 8 h.

## Pendências conhecidas

1. **Rodar os dois cenários completos** e gerar `graficos/relatorio_compare/` +
   `resumo_kpi.csv` — é o dado central do paper.
2. **Round Robin não capturava latência** e o cenário começava já com ~10 video streamings
   ativos (problema relatado em 11/06/2026). Validar se ainda ocorre depois do TTL e do
   commit `bd3c17f` "deixando cenarios independentes".
3. **Sistema é I/O-bound, não CPU-bound:** a CPU max saturou em ~20% porque o `/infer` é
   `time.sleep`. Isso limita o quanto o MAPE-K (que decide por CPU) tem para decidir — vale
   discutir no texto ou trocar o gatilho por latência/fila.
4. Migrar o agregador de latência para **janela deslizante de 60 s ou histograma p50/p95**,
   em vez de média acumulada (o TTL mitigou, não substituiu).

## Convenções

- Docs e comentários do repo em português; código e identificadores em inglês.
- Caminhos nos módulos são ancorados em `os.path.dirname(__file__)`, não na cwd — mantenha
  esse padrão para os scripts rodarem de qualquer lugar.
- O `rr_controller` preenche colunas `alpha`/`beta` vazias para manter o mesmo formato de
  CSV do MAB, e assim `analyze_mab.py` e os gráficos funcionam nos dois cenários. Não
  quebre esse contrato.
