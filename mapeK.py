import time
import requests
import docker # Embora importado, não está sendo usado diretamente no seu `execute_plan` simulado.
import subprocess
import signal
import sys
import socket
import os
import re
import numpy as np # Adicionado para np.nan

# Constantes e configurações que guiam as decisões do sistema.
create_app = {"container_name": "mec_app1_instance", "port": 8090, "py_file": "examples/mec_app1.py", "mec_name": "VideoStreamingService", "mec_host": "10.0.0.", "initial_ip":186, "instance_numer": 1}

# --- KNOWLEDGE (Conhecimento) ---
# Você pode querer ajustar esses limiares, já que agora está usando uma PREVISÃO
# Por exemplo, se a previsão é menos volátil, os limiares podem ser mais apertados.
CPU_THRESHOLD_UP = 12    # Limiar em % de CPU. Se a média de CPU subir acima disso, o sistema considera um SCALE_UP.
CPU_THRESHOLD_DOWN = 6  # Limiar em % de CPU. Se a média de CPU cair abaixo disso, o sistema considera um SCALE_DOWN.
MIN_INSTANCES = 1        # Número mínimo de instâncias MEC de vídeo que o sistema deve manter.
MAX_INSTANCES = 3        # Número máximo de instâncias MEC de vídeo que o sistema pode ter.
processos_abertos = []   # Uma lista para manter referências a processos abertos por 'abrir_terminal'. Útil para gerenciamento.
METRICS_POLLING_INTERVAL = 10 # Tempo em segundos entre as coleções de médias de CPU e PREVISÃO.
MEP_ADDRESS = os.getenv("MEP_ADDRESS", "192.168.70.2")
MONITOR_URL = f"http://{MEP_ADDRESS}/traffic_inteligence/cpu_percent"
# URL do endpoint na sua MEC Intelligence que fornece a média de CPU e a PREVISÃO.

# Funções auxiliares (parte do seu "conhecimento" sobre o ambiente)
def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('8.8.8.8', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP

def abrir_terminal(comando, diretorio=None, abrir_terminal_visivel=True, minimizar_terminal=False):
    """
    Abre um terminal GNOME e executa um comando, ou executa o comando em background.
    """
    if diretorio:
        comando_completo = f'cd "{diretorio}" && {comando}'
    else:
        comando_completo = comando

    if abrir_terminal_visivel:
        terminal_cmd = ['gnome-terminal']
        if minimizar_terminal:
            terminal_cmd.append('--minimize')
        terminal_cmd.extend(['--', 'bash', '-c', comando_completo + '; exec bash'])
        processo = subprocess.Popen(terminal_cmd)
    else:
        processo = subprocess.Popen(
            comando_comando_completo,
            shell=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

    processos_abertos.append(processo)
    return processo

# As funções iniciar_recptor_terminal e matar_ultimo_receptor_v2 não estão no escopo da alteração do MAPE-K, mas você pode mantê-las se forem relevantes para outras partes do seu sistema.
# def iniciar_recptor_terminal():
#     global receptores_aberto
#     processo=abrir_terminal('source mec_app1/bin/activate && python3 app_testes/receptorV2Tester.py', diretorio='examples')
#     receptores_aberto.append(processo)
#     time.sleep(5)
# def matar_ultimo_receptor_v2():
#     global receptores_aberto
#     if not receptores_aberto:
#         print("Nenhum terminal de receptor V2 ativo para matar.")
#         return
#     processo_receptor = receptores_aberto.pop()
#     print(f"💀 Tentando matar o último terminal de receptor V2 (PID: {processo_receptor.pid})...")
#     try:
#         processo_receptor.terminate()
#         processo_receptor.wait(timeout=5)
#         if processo_receptor.poll() is None:
#             processo_receptor.kill()
#             processo_receptor.wait(timeout=5)
#         print(f"✅ Terminal do último receptor V2 (PID: {processo_receptor.pid}) encerrado.")
#     except Exception as e:
#         print(f"❌ Erro ao encerrar o terminal do receptor V2: {e}")
   
# --- MONITOR (Monitorar) ---
def collect_metrics():
    """
    Coleta as métricas de CPU (atual e prevista) do endpoint da MEC Intelligence.
    """
    try:
        response = requests.get(MONITOR_URL)
        response.raise_for_status() 
        metrics = response.json() 
        
        current_cpu = metrics.get("current_avg_cpu_percent", None)
        predicted_cpu = metrics.get("predicted_next_avg_cpu_percent", None)
        
        # Converte "N/A" ou "Erro na Previsão" para None ou np.nan para tratamento numérico
        if isinstance(current_cpu, str) and (current_cpu == "N/A" or "Erro" in current_cpu):
            current_cpu = np.nan
        if isinstance(predicted_cpu, str) and (predicted_cpu == "N/A" or "Erro" in predicted_cpu):
            predicted_cpu = np.nan
        
        print(f"Métricas Coletadas: CPU Atual = {current_cpu:.2f}%" if not np.isnan(current_cpu) else f"Métricas Coletadas: CPU Atual = {current_cpu}", end="")
        print(f", CPU Prevista = {predicted_cpu:.2f}%" if not np.isnan(predicted_cpu) else f", CPU Prevista = {predicted_cpu}")

        return current_cpu, predicted_cpu # Retorna ambos os valores
    except requests.exceptions.RequestException as e:
        print(f"Erro ao coletar métricas do {MONITOR_URL}: {e}")
        return None, None # Retorna None para ambos em caso de erro na requisição
    except Exception as e:
        print(f"Erro inesperado ao processar métricas: {e}")
        return None, None

# --- ANALYZE (Analisar) ---
def analyze_metrics(current_cpu, predicted_cpu, current_num_instances):
    """
    Analisa as métricas de CPU (priorizando a prevista) para decidir a ação de escalonamento.
    """
    # Verifica se a previsão está disponível e é um número finito
    if predicted_cpu is None or np.isnan(predicted_cpu):
        print("Análise: Previsão de CPU indisponível ou inválida. Usando CPU atual se disponível.")
        # Se a previsão não estiver disponível, tenta usar a CPU atual como fallback
        if current_cpu is None or np.isnan(current_cpu):
            print("Análise: Dados de CPU atuais também indisponíveis. Nenhuma ação.")
            return "NO_ACTION"
        else:
            cpu_to_analyze = current_cpu
            print(f"Análise: Usando CPU atual como fallback: {cpu_to_analyze:.2f}%")
    else:
        cpu_to_analyze = predicted_cpu
        print(f"Análise: Usando CPU Prevista para decisão = {cpu_to_analyze:.2f}%, Instâncias Ativas = {current_num_instances}")

    # Verifica as condições para SCALE_UP
    if cpu_to_analyze > CPU_THRESHOLD_UP and current_num_instances < MAX_INSTANCES:
        print(f"Análise: Necessidade de SCALE_UP. CPU {cpu_to_analyze:.2f}% > {CPU_THRESHOLD_UP}% e Instâncias {current_num_instances} < {MAX_INSTANCES}.")
        return "SCALE_UP"
    # Verifica as condições para SCALE_DOWN
    elif cpu_to_analyze < CPU_THRESHOLD_DOWN and current_num_instances > MIN_INSTANCES:
        print(f"Análise: Necessidade de SCALE_DOWN. CPU {cpu_to_analyze:.2f}% < {CPU_THRESHOLD_DOWN}% e Instâncias {current_num_instances} > {MIN_INSTANCES}.")
        return "SCALE_DOWN"
    else:
        print("Análise: Nenhuma ação de escalonamento necessária no momento.")
        return "NO_ACTION"

# --- PLAN (Planejar) ---
def plan_action(analysis_result, current_num_instances): 
    # ... (mesmo código que você já tem) ...
    plan = {"action": analysis_result, "details": {}}
    
    if analysis_result == "SCALE_UP":
        new_instance_num = create_app["instance_numer"]
        plan["details"]["new_instance_num"] = new_instance_num
        plan["details"]["new_instance_port"] = create_app["port"] + new_instance_num
        plan["details"]["new_instance_host"] = get_local_ip()
        print(f"Planejamento: Criar nova instância 'mec_app1_instance{new_instance_num}' na porta {plan['details']['new_instance_port']}.")
    
    elif analysis_result == "SCALE_DOWN":
        instance_to_remove_num = create_app["instance_numer"] - 1
        if instance_to_remove_num >= MIN_INSTANCES:
            plan["details"]["instance_to_remove_num"] = instance_to_remove_num
            print(f"Planejamento: Remover instância 'mec_app1_instance{instance_to_remove_num}'.")
        else:
            print("Planejamento: Não é possível escalar para baixo, pois atingiria o número mínimo de instâncias.")
            plan["action"] = "NO_ACTION"
    
    return plan

# --- EXECUTE (Executar) ---
def execute_plan(plan):
    # ... (mesmo código que você já tem) ...
    action = plan["action"]
    print(f"Executando Plano: {action}")

    if action == "SCALE_UP":
        new_instance_num = plan["details"]["new_instance_num"]
        port = plan["details"]["new_instance_port"] # Não está sendo usado no comando
        host = plan["details"]["new_instance_host"] # Não está sendo usado no comando
        
        print(f"Executando SCALE_UP: Criando container 'mec_app1_instance{new_instance_num}'...")
        try:
            # Comando corrigido para usar a porta e o host calculados, se o mec_instance_manager aceitar
            abrir_terminal(f'python3 mec_instance_manager.py start mec_app1_instance{new_instance_num} {plan["details"]["new_instance_port"]} examples/mec_app1.py --mec_name VideoStreamingService{new_instance_num} --mec_host {plan["details"]["new_instance_host"]}')
            
            # Atualiza o contador de instância para o próximo ID disponível
            create_app["instance_numer"] = new_instance_num + 1 
            
            print(f"  --> Comando de criação para 'mec_app1_instance{new_instance_num}' enviado.")
            time.sleep(15) # Dá tempo para a nova instância subir e ser registrada
            return True
        except Exception as e:
            print(f"Erro ao criar container 'mec_app1_instance{new_instance_num}': {e}")
            return False 

    elif action == "SCALE_DOWN":
        instance_to_remove_num = plan["details"]["instance_to_remove_num"]
        print(f"Executando SCALE_DOWN: Removendo container 'mec_app1_instance{instance_to_remove_num}'...")
        try:
            requests.post(
                f"http://{MEP_ADDRESS}/traffic_inteligence/shut_down_mec_app",
                json={
                    "app_type": "VidProc",
                    "instance_name": f"VideoStreamingService{instance_to_remove_num}",
                    "container_name": f"mec_app1_instance{instance_to_remove_num}"
                },
                timeout=10
            )
            print(f"  --> Comando de remoção para 'mec_app1_instance{instance_to_remove_num}' enviado.")
            create_app["instance_numer"] -=1
            return True
        except Exception as e:
            print(f"Erro ao remover container 'mec_app1_instance{instance_to_remove_num}': {e}")
            return False 
    
    print("Nenhuma ação de execução realizada.")
    return True

# --- Função principal do MAPE-K (o loop de controle) ---
def run_mape_k_cycle():
    # Inicializa o número de instâncias com base no seu cenário.
    # Se você já tem 1 instância rodando no início, comece com 1.
    create_app["instance_numer"] = 1

    while True:
        print("\n--- Iniciando Ciclo MAPE-K ---")
        
        # 1. MONITOR
        # Agora coletamos a CPU atual E a prevista
        current_cpu, predicted_cpu = collect_metrics()
        
        # Verificar se a previsão está disponível e válida
        if predicted_cpu is None or (isinstance(predicted_cpu, (str, float)) and (predicted_cpu == "N/A" or np.isnan(predicted_cpu))):
            print("Previsão de CPU indisponível ou inválida neste ciclo. Re-tentando em 10 segundos...")
            #time.sleep(10)
            #continue # Pula para o próximo ciclo se a previsão não for utilizável
        
        # 2. ANALYZE
        # Passa a CPU prevista (ou a atual como fallback) para a análise
        analysis_result = analyze_metrics(current_cpu, predicted_cpu, create_app["instance_numer"])
        
        # 3. PLAN
        plan = plan_action(analysis_result, create_app["instance_numer"])
        
        # 4. EXECUTE
        execution_successful = execute_plan(plan)
        
        print("--- Ciclo MAPE-K Concluído ---")
        time.sleep(METRICS_POLLING_INTERVAL + 5) # Espera um pouco mais para dar tempo das métricas serem atualizadas e o sistema reagir

# --- Gerenciamento de Sinal (Ctrl+C) ---
def signal_handler(sig, frame):
    print("\nCtrl+C detectado. Encerrando todos os processos abertos pelo controlador MAPE-K...")
    for processo in processos_abertos:
        try:
            processo.terminate()
            processo.wait(timeout=5)
            if processo.poll() is None:
                processo.kill()
        except Exception as e:
            print(f"Erro ao encerrar processo (PID {processo.pid}): {e}")
    print("Processos encerrados. Saindo...")
    sys.exit(0)

if __name__ == "__main__":
    signal.signal(signal.SIGINT, signal_handler)
    
    print("Iniciando controlador MAPE-K...")
    # Inicia o ciclo MAPE-K
    run_mape_k_cycle()