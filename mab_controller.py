import csv
import os
import numpy as np

RED = '\033[31m'
RESET = '\033[0m'

class ThompsonSamplingBandit:
    def __init__(self, num_arms, prob_csv='./Results/arm_probabilities.csv'):
        self.num_arms = num_arms
        self.alpha = np.ones(num_arms)
        self.beta = np.ones(num_arms)
        self.total_reward = 0
        self.total_reward_history = []
        self.n_step = 1
        self.history = []
        self.prob_csv = prob_csv
        self._init_prob_csv()

    def _init_prob_csv(self):
        """Cria o CSV com cabeçalho se ainda não existir."""
        os.makedirs(os.path.dirname(self.prob_csv), exist_ok=True)
        if not os.path.exists(self.prob_csv):
            with open(self.prob_csv, mode='w', newline='') as f:
                writer = csv.writer(f)
                writer.writerow(['event', 'arm', 'alpha_before', 'beta_before', 'sampled_prob'])

    def _save_arm_snapshot(self, event: str, sampled_values=None):
        """
        Salva snapshot de alpha, beta e probabilidade amostrada para cada braço.
        
        - event: 'update' | 'remove_arms'
        - sampled_values: array com os valores amostrados (opcional)
        """
        with open(self.prob_csv, mode='a', newline='') as f:
            writer = csv.writer(f)
            for arm in range(self.num_arms):
                sampled = sampled_values[arm] if sampled_values is not None else ''
                writer.writerow([
                    event,
                    arm,
                    round(self.alpha[arm], 6),
                    round(self.beta[arm], 6),
                    round(sampled, 6) if sampled != '' else ''
                ])

    def update_arms(self, new_num_arms):
        if new_num_arms == self.num_arms:
            return

        if new_num_arms < self.num_arms:
            # Salva snapshot ANTES de remover braços
            self._save_arm_snapshot(event='remove_arms')
            self.alpha = self.alpha[:new_num_arms]
            self.beta = self.beta[:new_num_arms]
            self.history = [(a, r) for a, r in self.history if a < new_num_arms]
        else:
            extra = new_num_arms - self.num_arms
            self.alpha = np.append(self.alpha, np.ones(extra))
            self.beta = np.append(self.beta, np.ones(extra))

        self.num_arms = new_num_arms

    def select_action(self):
        sampled_values = np.random.beta(self.alpha, self.beta)
        # Salva snapshot com as probabilidades amostradas antes de agir
        self._save_arm_snapshot(event='select', sampled_values=sampled_values)
        action = np.argmax(sampled_values)
        return action

    def update(self, action, reward):
        self.history.append((action, reward))
        if len(self.history) >= self.n_step:
            G = sum([self.history[i][1] for i in range(self.n_step)])
            a, _ = self.history.pop(0)

            # Salva snapshot ANTES de atualizar alpha/beta
            self._save_arm_snapshot(event='update')

            self.alpha[a] += G
            self.beta[a] += self.n_step - G

            self.total_reward += G
            self.total_reward_history.append(self.total_reward)

    def end_episode(self):
        self.history = []


class controller:
    def __init__(self, metric_a_ref, metric_b_ref, num_arms=2, csv_file='./Results/model_info.csv') -> None:
        self.metric_a_ref = metric_a_ref
        self.metric_b_ref = metric_b_ref
        self.csv_file = csv_file
        self.episode = 0
        self.action_history = []
        self.user_action = {}
        self.model = ThompsonSamplingBandit(num_arms)  # <-- corrigido: era m_model

    def set_num_arms(self, new_num_arms):
        """Atualiza o número de braços no modelo TS."""
        self.model.update_arms(new_num_arms)
        print(f'[Controller] Número de braços atualizado para {new_num_arms}')

    def get_arm_ts(self, userId):
        thompson_sampling_action = self.model.select_action()
        print(f'[MEC] thompson_sampling_action = {thompson_sampling_action}')
        self.user_action[userId] = thompson_sampling_action
        return thompson_sampling_action

    def update_model(self, userId, state):
        thompson_sampling_reward = self.reward(state[0], state[1])
        arm = self.user_action[userId]
        self.lock = self.model.update(arm, thompson_sampling_reward)
        self.action_history.append([arm, thompson_sampling_reward])

    def reward(self, metric_a, metric_b):
        if self.metric_a_ref >= metric_a and self.metric_b_ref <= metric_b:
            return 1
        return 0


def main():
    m_controller = controller(metric_a_ref=0.3, metric_b_ref=2, num_arms=2)

    # Simula mudança dinâmica no número de braços disponíveis
    print(f'Braços iniciais: {m_controller.model.num_arms}')

    action = m_controller.get_arm_ts(userId=1)

    # TODO: Add time sleep

    m_controller.update_model(userId=1, state=[0.5, 2])

    # Atualiza para 4 braços disponíveis
    m_controller.set_num_arms(4)
    print(f'Braços após atualização: {m_controller.model.num_arms}')

    # Reduz para 3 braços
    m_controller.set_num_arms(3)
    print(f'Braços após redução: {m_controller.model.num_arms}')

if __name__ == '__main__':
    main()