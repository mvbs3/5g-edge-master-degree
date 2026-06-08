import csv
import os
import numpy as np

RED = '\033[31m'
RESET = '\033[0m'


class ThompsonSamplingBandit:
    """
    Thompson Sampling com braços identificados por NOME (não por posição).
    Preserva estatísticas dos braços que sobrevivem entre operações de
    set_arms — essencial quando MAPE-K adiciona/remove instâncias MEC
    no meio do experimento.
    """

    def __init__(self, prob_csv='./Results/arm_probabilities.csv', decay=1.0):
        # arms = {arm_name: {'alpha': float, 'beta': float}}
        self.arms = {}

        self.total_reward = 0
        self.total_reward_history = []

        self.n_step = 1
        self.history = []  # [(arm_name, reward), ...]

        self.prob_csv = prob_csv
        self.decay = decay  # 1.0 = sem decay; <1.0 = forgetting (não-estacionário)

        self._init_prob_csv()

    @property
    def num_arms(self):
        return len(self.arms)

    def _init_prob_csv(self):
        os.makedirs(os.path.dirname(self.prob_csv), exist_ok=True)

        if not os.path.exists(self.prob_csv):
            with open(self.prob_csv, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'event',
                    'arm',
                    'alpha_before',
                    'beta_before',
                    'sampled_prob'
                ])

    def _save_arm_snapshot(self, event, sampled_values=None):
        with open(self.prob_csv, mode='a', newline='') as f:
            writer = csv.writer(f)

            for name, params in self.arms.items():
                sampled = (
                    sampled_values.get(name, '')
                    if sampled_values is not None
                    else ''
                )

                writer.writerow([
                    event,
                    name,
                    round(params['alpha'], 6),
                    round(params['beta'], 6),
                    round(sampled, 6) if sampled != '' else ''
                ])

    def _warm_prior(self):
        # Novo braço herda a média dos braços existentes, mas com evidência
        # limitada (cap em 10) para preservar exploração.
        if not self.arms:
            return 1.0, 1.0

        alphas = [a['alpha'] for a in self.arms.values()]
        betas = [a['beta'] for a in self.arms.values()]

        mean_alpha = float(np.mean(alphas))
        mean_beta = float(np.mean(betas))

        total = mean_alpha + mean_beta
        if total > 10.0:
            factor = 10.0 / total
            return max(1.0, mean_alpha * factor), max(1.0, mean_beta * factor)

        return max(1.0, mean_alpha), max(1.0, mean_beta)

    def set_arms(self, arm_names):
        """
        Sincroniza o conjunto de braços com a lista atual de instâncias MEC.
        Braços existentes preservam (alpha, beta); novos recebem warm prior;
        removidos perdem estado.
        """
        new_set = set(arm_names)
        existing = set(self.arms.keys())

        to_remove = existing - new_set
        to_add = new_set - existing

        if not to_remove and not to_add:
            return

        if to_remove:
            self._save_arm_snapshot(event='remove_arms')

            for name in to_remove:
                del self.arms[name]

            self.history = [
                (n, r) for n, r in self.history if n in self.arms
            ]

        if to_add:
            warm_alpha, warm_beta = self._warm_prior()
            for name in to_add:
                self.arms[name] = {
                    'alpha': warm_alpha,
                    'beta': warm_beta,
                }

    def select_action(self):
        """Retorna o NOME do braço amostrado (None se não houver braços)."""
        if not self.arms:
            return None

        sampled_values = {
            name: float(np.random.beta(
                self.arms[name]['alpha'],
                self.arms[name]['beta']
            ))
            for name in self.arms
        }

        self._save_arm_snapshot(
            event='select',
            sampled_values=sampled_values
        )

        return max(sampled_values, key=sampled_values.get)

    def update(self, arm_name, reward):
        if arm_name not in self.arms:
            return

        self.history.append((arm_name, reward))

        if len(self.history) >= self.n_step:
            G = sum(r for _, r in self.history[:self.n_step])
            name, _ = self.history.pop(0)

            if name not in self.arms:
                return

            self._save_arm_snapshot(event='update')

            if self.decay < 1.0:
                self.arms[name]['alpha'] = max(
                    1.0, self.arms[name]['alpha'] * self.decay
                )
                self.arms[name]['beta'] = max(
                    1.0, self.arms[name]['beta'] * self.decay
                )

            self.arms[name]['alpha'] += G
            self.arms[name]['beta'] += self.n_step - G

            self.total_reward += G
            self.total_reward_history.append(self.total_reward)

    def end_episode(self):
        self.history = []


class controller:

    def __init__(
        self,
        latency_ref,
        csv_file='./Results/model_info.csv',
        decay=1.0,
    ):
        self.latency_ref = latency_ref
        self.csv_file = csv_file

        self.episode = 0
        self.action_history = []

        # user_action mapeia userId -> NOME da instância (não índice)
        self.user_action = {}
        self.user_assignment_time = {}

        self.model = ThompsonSamplingBandit(decay=decay)

    def set_arms(self, arm_names):
        self.model.set_arms(arm_names)

    def get_arm_ts(self, userId, current_time=None):
        action_name = self.model.select_action()

        if action_name is None:
            return None

        print(f'[MEC] thompson_sampling_action = {action_name}')

        self.user_action[userId] = action_name
        if current_time is not None:
            self.user_assignment_time[userId] = current_time

        return action_name

    def update_model(self, userId, state):
        if userId not in self.user_action:
            return

        latency = state[0]
        reward = self.reward(latency)
        arm_name = self.user_action[userId]

        self.model.update(arm_name, reward)

        self.action_history.append([arm_name, reward])

    def reassign(self, userId, new_arm_name, current_time=None):
        """
        Força a atribuição de um UE a um braço específico (ex: drenagem
        de instância). Mantém user_action coerente com o app real para que
        update_model atribua reward ao braço correto.
        """
        if new_arm_name in self.model.arms:
            self.user_action[userId] = new_arm_name
            if current_time is not None:
                self.user_assignment_time[userId] = current_time

    def remove_user(self, userId):
        self.user_action.pop(userId, None)
        self.user_assignment_time.pop(userId, None)

    def reward(self, latency):
        # Menor latência é melhor: reward=1 quando latency <= ref.
        if latency <= self.latency_ref:
            return 1
        return 0


def main():
    import time

    m_controller = controller(latency_ref=100)

    m_controller.set_arms(['svc1', 'svc2'])
    print(f'Braços iniciais: {m_controller.model.num_arms}')

    action = m_controller.get_arm_ts(userId=1, current_time=time.time())
    print(f'Ação escolhida: {action}')

    # latência 80ms <= 100ms -> reward 1 (correto: latência baixa é boa)
    m_controller.update_model(userId=1, state=[80])

    m_controller.set_arms(['svc1', 'svc2', 'svc3', 'svc4'])
    print(f'Braços após adicionar svc3,svc4: {m_controller.model.num_arms}')
    print(f'  svc1 stats: {m_controller.model.arms["svc1"]}')

    # Remover svc2 — svc1, svc3, svc4 preservam stats
    m_controller.set_arms(['svc1', 'svc3', 'svc4'])
    print(f'Braços após remover svc2: {m_controller.model.num_arms}')
    print(f'  svc1 stats preservadas: {m_controller.model.arms["svc1"]}')


if __name__ == '__main__':
    main()
