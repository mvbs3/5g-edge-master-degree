"""Round-robin baseline controller — drop-in replacement for
mab_controller.controller. Mantém a mesma interface pública pra que o
mec_app_inteligence.py funcione sem mudanças adicionais (apenas alterando o
import). Persiste em CSV no mesmo formato que o MAB (com colunas alpha/beta
preenchidas com '' nos eventos), pra que o analyze_mab.py e o graficos
funcionem nos dois cenários.
"""

import csv
import itertools
import os
import time

# Caminhos ancorados ao diretório do módulo (não dependem da cwd).
_RESULTS_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'Results'
)
DEFAULT_PROB_CSV = os.path.join(_RESULTS_DIR, 'arm_probabilities.csv')
DEFAULT_REWARDS_CSV = os.path.join(_RESULTS_DIR, 'rewards.csv')


class RoundRobin:
    """Distribuidor circular puro. Sem aprendizagem.

    Mantém um dict `arms` (com placeholders alpha/beta=1.0) só pra preservar
    a API esperada por mec_app_inteligence.py (`controller.model.arms`).
    """

    def __init__(
        self,
        prob_csv=DEFAULT_PROB_CSV,
        rewards_csv=DEFAULT_REWARDS_CSV,
        decay=1.0,
    ):
        self.arms = {}
        self.prob_csv = prob_csv
        self.rewards_csv = rewards_csv
        self._cycle = None
        self.total_reward = 0
        self.total_reward_history = []
        self.history = []

        self._init_csvs()

    @property
    def num_arms(self):
        return len(self.arms)

    def _init_csvs(self):
        os.makedirs(os.path.dirname(self.prob_csv), exist_ok=True)
        if not os.path.exists(self.prob_csv):
            with open(self.prob_csv, 'w', newline='') as f:
                csv.writer(f).writerow([
                    'timestamp', 'event', 'arm',
                    'alpha_before', 'beta_before', 'sampled_prob',
                ])
        if not os.path.exists(self.rewards_csv):
            with open(self.rewards_csv, 'w', newline='') as f:
                csv.writer(f).writerow([
                    'timestamp', 'user_id', 'arm',
                    'latency_ms', 'reward', 'alpha_after', 'beta_after',
                ])

    def _save_snapshot(self, event):
        ts = time.time()
        with open(self.prob_csv, 'a', newline='') as f:
            writer = csv.writer(f)
            for name in self.arms:
                writer.writerow([round(ts, 6), event, name, '', '', ''])

    def set_arms(self, arm_names):
        new_set = set(arm_names)
        existing = set(self.arms.keys())
        if new_set == existing and self._cycle is not None:
            return
        if existing - new_set:
            self._save_snapshot('remove_arms')
        self.arms = {name: {'alpha': 1.0, 'beta': 1.0} for name in sorted(new_set)}
        self._cycle = itertools.cycle(self.arms.keys()) if self.arms else None

    def select_action(self):
        if not self.arms or self._cycle is None:
            return None
        action = next(self._cycle)
        self._save_snapshot('select')
        return action

    def update(self, arm_name, reward):
        # RR não aprende — registra evento pra manter o pipeline analítico
        # capaz de contar pulls e success rate por braço.
        if arm_name not in self.arms:
            return
        self.history.append((arm_name, reward))
        self.total_reward += int(reward)
        self.total_reward_history.append(self.total_reward)
        self._save_snapshot('update')

    def log_reward_event(self, user_id, arm, latency, reward):
        try:
            lat = float(latency)
        except (TypeError, ValueError):
            lat = float('nan')
        with open(self.rewards_csv, 'a', newline='') as f:
            csv.writer(f).writerow([
                round(time.time(), 6),
                user_id,
                arm,
                round(lat, 4),
                int(reward),
                '',
                '',
            ])

    def end_episode(self):
        self.history = []


class controller:
    """Drop-in equivalente ao mab_controller.controller, mas com Round Robin."""

    def __init__(self, latency_ref, csv_file=os.path.join(_RESULTS_DIR, 'model_info.csv'), decay=1.0):
        self.latency_ref = latency_ref
        self.csv_file = csv_file
        self.episode = 0
        self.action_history = []
        self.user_action = {}
        self.user_assignment_time = {}
        self.model = RoundRobin(decay=decay)

    def set_arms(self, arm_names):
        self.model.set_arms(arm_names)

    def get_arm_ts(self, userId, current_time=None):
        action_name = self.model.select_action()
        if action_name is None:
            return None
        print(f'[MEC] round_robin_action = {action_name}')
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
        self.model.log_reward_event(userId, arm_name, latency, reward)
        self.action_history.append([arm_name, reward])

    def reassign(self, userId, new_arm_name, current_time=None):
        if new_arm_name in self.model.arms:
            self.user_action[userId] = new_arm_name
            if current_time is not None:
                self.user_assignment_time[userId] = current_time

    def remove_user(self, userId):
        self.user_action.pop(userId, None)
        self.user_assignment_time.pop(userId, None)

    def reward(self, latency):
        return 1 if latency <= self.latency_ref else 0
