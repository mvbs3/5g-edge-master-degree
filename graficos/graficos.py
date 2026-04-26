import pandas as pd
import matplotlib.pyplot as plt
import os
import seaborn as sns
from datetime import datetime # Ainda necessário para conversão de timestamp ao carregar, mas não para o eixo X
import numpy as np

# --- Configurações de Estilo para os Gráficos ---
plt.style.use('seaborn-v0_8-darkgrid')
sns.set_palette("tab10") # Uma paleta mais contrastante para comparação de cenários (ex: azul, laranja, verde, vermelho)
plt.rcParams['figure.figsize'] = (14, 8) # Tamanho padrão para os gráficos
plt.rcParams['lines.linewidth'] = 2      # Espessura das linhas
plt.rcParams['axes.titlesize'] = 18      # Tamanho do título do gráfico
plt.rcParams['axes.labelsize'] = 14      # Tamanho dos rótulos dos eixos
plt.rcParams['legend.fontsize'] = 12     # Tamanho da fonte da legenda
plt.rcParams['xtick.labelsize'] = 10     # Tamanho dos rótulos do eixo X
plt.rcParams['ytick.labelsize'] = 10     # Tamanho dos rótulos do eixo Y


# --- Diretório de Saída para os Gráficos ---
OUTPUT_DIR = 'relatorio_graficos'
if not os.path.exists(OUTPUT_DIR):
    os.makedirs(OUTPUT_DIR)
    print(f"Diretório '{OUTPUT_DIR}' criado para salvar os gráficos.")

# --- Função para Carregar e Pré-processar Dados de UM Cenário ---
def load_and_preprocess_scenario_data(csv_file_path, scenario_label):
    """
    Carrega um arquivo CSV, filtra para 'VidProc', e pré-processa as colunas numéricas.
    Adiciona uma coluna de 'cenário' e uma 'sample_index' para identificação e alinhamento.
    Garante que DataFrames vazios retornados contenham as colunas necessárias.
    """
    print(f"Carregando dados do arquivo: {csv_file_path}")
    
    # Define as colunas que devem estar presentes no DataFrame retornado, mesmo que vazio
    # Isso é crucial para pd.concat não dar KeyError e para as funções de plotagem
    REQUIRED_COLS = [
        'timestamp', 'app_type', 'num_services', 'scenario', 'sample_index',
        'avg_cpu_percent', 'max_cpu_percent', 'min_cpu_percent',
        'avg_memory_percent', 'max_memory_percent', 'min_memory_percent',
        'avg_memory_used_mb', 'max_memory_used_mb', 'min_memory_used_mb',
        'avg_queue_size', 'max_queue_size', 'min_queue_size',
        'avg_network_rx_kbps', 'max_network_rx_kbps', 'min_network_rx_kbps',
        'avg_network_tx_kbps', 'max_network_tx_kbps', 'min_network_tx_kbps',
        'avg_throughput_kbps', 'max_throughput_kbps', 'min_throughput_kbps'
        # 'avg_latency_ms' e suas variantes foram removidas
    ]

    try:
        df = pd.read_csv(csv_file_path)
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # --- Adicionar 'scenario' ao DF completo IMEDIATAMENTE após carregar ---
        # Garante que a coluna 'scenario' é criada no DF original
        df['scenario'] = scenario_label
        # --- Fim da adição de 'scenario' ---

        df_vidproc = df[df['app_type'] == 'VidProc'].copy()

        # Verifica se df_vidproc está vazio após a filtragem inicial
        if df_vidproc.empty:
            print(f"  -> Nenhuma linha encontrada para 'VidProc' no arquivo '{csv_file_path}'.")
            # Retorna um DataFrame vazio, mas com as colunas necessárias
            empty_df = pd.DataFrame(columns=REQUIRED_COLS)
            empty_df['scenario'] = scenario_label # Garante que o label é aplicado mesmo no DF vazio
            empty_df['sample_index'] = pd.Series(dtype='int64') # Garante o tipo correto para o índice
            return empty_df

        # --- AQUI ESTÁ A CRIAÇÃO DE 'sample_index' para CADA CENÁRIO ---
        # Este índice será o eixo X para a comparação "ponto a ponto"
        df_vidproc['sample_index'] = np.arange(len(df_vidproc))
        # --- FIM DA CRIAÇÃO DE 'sample_index' ---
        
        # Lista de colunas numéricas para conversão e tratamento de "N/A"
        # Ajustado para remover colunas de latência
        numeric_cols = [
            'avg_cpu_percent', 'max_cpu_percent', 'min_cpu_percent',
            'avg_memory_percent', 'max_memory_percent', 'min_memory_percent',
            'avg_memory_used_mb', 'max_memory_used_mb', 'min_memory_used_mb',
            'avg_queue_size', 'max_queue_size', 'min_queue_size',
            'avg_network_rx_kbps', 'max_network_rx_kbps', 'min_network_rx_kbps',
            'avg_network_tx_kbps', 'max_network_tx_kbps', 'min_network_tx_kbps',
            'avg_throughput_kbps', 'max_throughput_kbps', 'min_throughput_kbps',
            'num_services' # Coluna que representa o número de instâncias
        ]
        for col in numeric_cols:
            if col in df_vidproc.columns: # Verifica se a coluna existe antes de tentar converter
                df_vidproc[col] = pd.to_numeric(df_vidproc[col], errors='coerce')
            else:
                print(f"  AVISO: Coluna '{col}' não encontrada em '{csv_file_path}'. Criando-a com NaN.")
                df_vidproc[col] = np.nan # Cria a coluna com NaN se ela estiver faltando

        # Remover linhas onde métricas críticas são NaN após conversão (garante plots limpos)
        # Ajustada para remover a dependência de 'avg_latency_ms'
        initial_rows = len(df_vidproc)
        df_vidproc.dropna(subset=['avg_cpu_percent', 'num_services', 'avg_throughput_kbps', 'avg_memory_percent'], inplace=True)
        if len(df_vidproc) < initial_rows:
            print(f"  -> Removidas {initial_rows - len(df_vidproc)} linhas com NaN em métricas críticas para '{scenario_label}'.")
            if df_vidproc.empty:
                print(f"  AVISO: '{scenario_label}' ficou vazio após a remoção de NaNs. Gráficos podem não ser gerados para este cenário.")
                empty_df = pd.DataFrame(columns=REQUIRED_COLS)
                empty_df['scenario'] = scenario_label
                empty_df['sample_index'] = pd.Series(dtype='int64') # Garante o tipo correto
                return empty_df

        print(f"  -> Dados carregados com sucesso para '{scenario_label}'. Linhas VidProc após limpeza: {len(df_vidproc)}")
        return df_vidproc
    except FileNotFoundError:
        print(f"AVISO: Arquivo '{csv_file_path}' não encontrado. Este cenário será ignorado.")
        empty_df = pd.DataFrame(columns=REQUIRED_COLS)
        empty_df['scenario'] = scenario_label
        empty_df['sample_index'] = pd.Series(dtype='int64') # Garante o tipo correto
        return empty_df
    except Exception as e:
        print(f"ERRO: Problema ao carregar ou pré-processar '{csv_file_path}': {e}. Este cenário será ignorado.")
        empty_df = pd.DataFrame(columns=REQUIRED_COLS)
        empty_df['scenario'] = scenario_label
        empty_df['sample_index'] = pd.Series(dtype='int64') # Garante o tipo correto
        return empty_df

# --- Função para Gerar Gráficos de Comparação de Métricas (AJUSTADA PARA O EIXO X = 'sample_index') ---
def plot_scenario_comparison(df_to_plot, metric_col, title, ylabel, ylim=None, filename_suffix=""):
    """
    Gera um gráfico de linha comparando uma métrica entre diferentes cenários,
    usando o 'sample_index' da amostra no eixo X para alinhamento.
    """
    if df_to_plot.empty:
        print(f"Não há dados para plotar '{title}' (DataFrame vazio).")
        return

    plt.figure(figsize=(14, 8))
    # sns.lineplot plota a métrica no eixo Y, e usa a coluna 'sample_index' como eixo X
    sns.lineplot(data=df_to_plot, x='sample_index', y=metric_col, hue='scenario', marker='o', linewidth=2)

    plt.title(title, fontsize=16)
    plt.xlabel('Amostra de Coleta', fontsize=12) # Rótulo do eixo X alterado para 'sample_index'
    plt.ylabel(ylabel, fontsize=12)
    plt.grid(True)
    plt.legend(title='Cenário', fontsize=12)

    if ylim:
        plt.ylim(ylim)

    plt.tight_layout()
    filename = os.path.join(OUTPUT_DIR, f"{metric_col}_comparacao_cenarios{filename_suffix}.png")
    plt.savefig(filename, dpi=300)
    print(f"Gráfico salvo: {filename}")
    plt.close() # Fecha a figura para liberar memória

# --- Função para Gerar Gráfico de Comparação de Número de Instâncias (AJUSTADA PARA O EIXO X = 'sample_index') ---
def plot_num_instances_comparison(df_to_plot, filename_suffix=""):
    """
    Gera um gráfico de linha comparando o número de instâncias ativas entre diferentes cenários,
    usando o 'sample_index' da amostra no eixo X para alinhamento.
    """
    if df_to_plot.empty:
        print(f"Não há dados para plotar 'Número de Instâncias Ativas' (DataFrame vazio).")
        return

    plt.figure(figsize=(14, 8))
    sns.lineplot(data=df_to_plot, x='sample_index', y='num_services', hue='scenario', marker='o', linewidth=2)

    plt.title(f'Número de Instâncias Ativas (VidProc) {filename_suffix.replace("_", " ")}', fontsize=16)
    plt.xlabel('Amostra de Coleta', fontsize=12) # Rótulo do eixo X alterado para 'sample_index'
    plt.ylabel('Número de Instâncias', fontsize=12)
    plt.grid(True)
    plt.legend(title='Cenário', fontsize=12)

    plt.yticks(np.arange(0, df_to_plot['num_services'].max() + 1, 1))
    plt.ylim(bottom=0)

    plt.tight_layout()
    filename = os.path.join(OUTPUT_DIR, f"num_instancias_comparacao_cenarios{filename_suffix}.png")
    plt.savefig(filename, dpi=300)
    print(f"Gráfico salvo: {filename}")
    plt.close()

# --- Função Principal para Orquestrar a Geração de Gráficos ---
def main():
    # --- DEFINA AQUI OS CAMINHOS PARA OS SEUS 4 ARQUIVOS CSV ---
    # Certifique-se de que os nomes e caminhos correspondem aos resultados dos seus experimentos.
    # Exemplo:
    scenario_files = {
        'Estresse_GRU': 'rl_input_state_Mape_GRU_CrescenteUE.csv',         # Teste de estresse, crescente, com GRU
        'Estresse_Reativo': 'rl_input_state_Mape_CrescenteUE.csv',     # Teste de estresse, crescente, sem GRU
        'Variavel_GRU': 'rl_input_state_Mape_GRU_RandomUE.csv',         # Usuários variáveis, com GRU
        'Variavel_Reativo': 'rl_input_state_Mape_RandomUE.csv',     # Usuários variáveis, sem GRU
    }
    
    all_dfs = []
    print("\n--- Iniciando o Carregamento e Pré-processamento dos Dados dos Cenários ---")
    for label, path in scenario_files.items():
        df_scenario = load_and_preprocess_scenario_data(path, label)
        if not df_scenario.empty: # Adiciona apenas DataFrames não vazios
            all_dfs.append(df_scenario)
    
    if not all_dfs: # Verifica se algum dado foi carregado
        print("ERRO: Nenhum dado válido encontrado para plotagem de nenhum cenário. Verifique os caminhos dos CSVs e a presença de dados 'VidProc'.")
        return

    # Combina todos os DataFrames pré-processados em um único.
    # Usamos ignore_index=False aqui, pois o 'sample_index' já garante o alinhamento ponto a ponto.
    df_combined_all = pd.concat(all_dfs, ignore_index=False)
    print(f"\nTotal de linhas combinadas para o app_type 'VidProc': {len(df_combined_all)}")
    
    if df_combined_all.empty:
        print("ERRO: O DataFrame combinado está vazio. Nenhuma plotagem pode ser realizada.")
        return

    print("\n--- Gerando Gráficos Comparativos ---")

    # =========================================================================
    # COMPARAÇÕES PRINCIPAIS PARA O ARTIGO (Conforme você solicitou)
    # =========================================================================

    # --- 1. Comparação: Teste de Estresse (Auto-escalonamento Preditivo vs. Reativo) ---
    df_stress_comparison = df_combined_all[
        df_combined_all['scenario'].isin(['Estresse_GRU', 'Estresse_Reativo'])
    ].copy()
    if not df_stress_comparison.empty:
        print("\nGerando gráficos para: Comparação de Teste de Estresse (Com GRU vs. Reativo)")
        plot_scenario_comparison(df_stress_comparison, 'avg_cpu_percent',
                                 'Uso de CPU Médio (Teste de Estresse: Preditivo vs. Reativo)', 'Uso de CPU (%)', ylim=(0, 100), filename_suffix="_Stress_Pred_vs_Reat")
        plot_num_instances_comparison(df_stress_comparison, filename_suffix="_Stress_Pred_vs_Reat")
        # Gráfico de Latência removido conforme sua solicitação
        plot_scenario_comparison(df_stress_comparison, 'avg_throughput_kbps',
                                 'Throughput Médio (Teste de Estresse: Preditivo vs. Reativo)', 'Throughput (Kbps)', filename_suffix="_Stress_Pred_vs_Reat")
        plot_scenario_comparison(df_stress_comparison, 'avg_memory_percent',
                                 'Uso de Memória Médio (Teste de Estresse: Preditivo vs. Reativo)', 'Uso de Memória (%)', ylim=(0, 100), filename_suffix="_Stress_Pred_vs_Reat")
    else:
        print("AVISO: Dados insuficientes para a Comparação de Teste de Estresse.")


    # --- 2. Comparação: Cenário de Usuários Variáveis (Auto-escalonamento Preditivo vs. Reativo) ---
    df_variavel_comparison = df_combined_all[
        df_combined_all['scenario'].isin(['Variavel_GRU', 'Variavel_Reativo'])
    ].copy()
    if not df_variavel_comparison.empty:
        print("\nGerando gráficos para: Comparação de Cenário de Usuários Variáveis (Com GRU vs. Reativo)")
        plot_scenario_comparison(df_variavel_comparison, 'avg_cpu_percent',
                                 'Uso de CPU Médio (Usuários Variáveis: Preditivo vs. Reativo)', 'Uso de CPU (%)', ylim=(0, 100), filename_suffix="_Variavel_Pred_vs_Reat")
        plot_num_instances_comparison(df_variavel_comparison, filename_suffix="_Variavel_Pred_vs_Reat")
        # Gráfico de Latência removido conforme sua solicitação
        plot_scenario_comparison(df_variavel_comparison, 'avg_throughput_kbps',
                                 'Throughput Médio (Usuários Variáveis: Preditivo vs. Reativo)', 'Throughput (Kbps)', filename_suffix="_Variavel_Pred_vs_Reat")
        plot_scenario_comparison(df_variavel_comparison, 'avg_memory_percent',
                                 'Uso de Memória Médio (Usuários Variáveis: Preditivo vs. Reativo)', 'Uso de Memória (%)', ylim=(0, 100), filename_suffix="_Variavel_Pred_vs_Reat")
    else:
        print("AVISO: Dados insuficientes para Comparação de Usuários Variáveis.")


    # =========================================================================
    # COMPARAÇÕES ADICIONAIS (Opcional, se fizer sentido para o artigo)
    # =========================================================================
    # Exemplo: Comparar o desempenho da abordagem Preditiva em diferentes tipos de carga
    df_proativo_load_type_comparison = df_combined_all[
        df_combined_all['scenario'].isin(['Estresse_GRU', 'Variavel_GRU'])
    ].copy()
    if not df_proativo_load_type_comparison.empty:
        print("\nGerando gráficos para: Comparação de Tipo de Carga (Abordagem Preditiva: Estresse vs. Variável)")
        plot_scenario_comparison(df_proativo_load_type_comparison, 'avg_cpu_percent',
                                 'Uso de CPU Médio (Preditivo: Estresse vs. Variável)', 'Uso de CPU (%)', ylim=(0, 100), filename_suffix="_Pred_Estresse_vs_Variavel")
        plot_num_instances_comparison(df_proativo_load_type_comparison, filename_suffix="_Pred_Estresse_vs_Variavel")
        # Adicione outras métricas conforme necessário para esta comparação
    else:
        print("AVISO: Dados insuficientes para Comparação de Tipo de Carga (Abordagem Preditiva).")


    print("\n--- Todos os gráficos comparativos foram gerados com sucesso! ---")
    print(f"Os arquivos PNG foram salvos na pasta '{OUTPUT_DIR}'.")

# Bloco de execução principal do script
if __name__ == "__main__":
    main()