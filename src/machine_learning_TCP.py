import time
import random
import math
import json
import torch
from operator import itemgetter
from typing import List, Dict, Tuple, Optional
from src.algorithm import SenderAlgorithm
from src.pytorch_TCP_MachineLearning import optimize_model, Transition, LSTM_DQN

DEFAULT_TIMEOUT = 2 # значение тайм-аута по умолчанию
BETA_CUBIC = 0.7 # значение коэффициента алгоритма КУБИК
CUBIC_CONSTANT = 4 # Параметр алгоритма Кубик

class ReinforcementAlgorithm(SenderAlgorithm):
    """Обучение с подкреплением с использованием LSTM(долгой краткосрочной памяти) и Q-функции."""

    def __init__(self, policy_net: LSTM_DQN, target_net: LSTM_DQN, device: torch.device, optimizer, hyperparameters: Dict, episode_num: int, transitions: List[Dict]) -> None:
        
        self.device = device # использование GPU
        self.cwnd = 1 # # начальное значение окна перегрузки
        self.fast_retransmit_packet = None # # пакет быстрой повторной передачи
        self.time_since_retransmit = None # # время с момента повторной передачи
        self.retransmitting_packet = False # # передача пакетов
        self.ack_count = 0 # 
        self.timeout = DEFAULT_TIMEOUT # 
        self.fast_retransmitted_packets_in_flight = [] # 

        self.duplicated_ack = None #  # дублирование ack
        self.slow_start_thresholds = [] #  # значение порога медленного старта

        self.next_packet_rewards = {} # Отображение порядкового номера в комбинации действие/состояние

        self.sequence_history_dict = {} # список с фиксированным размером
        self.transitions = transitions # именованный кортеж, представляющий один переход в нашей среде и составляет пары состояния или действия ('state', 'action') с их результатом ('next_state', 'reward')
        self.base_rtt = None # размер круговой задержки
        # Инициализация машинного обучения (ML)
        self.policy_net = policy_net # политика сети
        self.target_net = target_net # целевое подключение
        self.optimizer = optimizer # оптимизация модели
        self.episode = episode_num # количество эпизодов подключения
        self.losses = [] # потери
        self.hyperparameters = hyperparameters # определение гиперпараметров сети
        self.time_since_last_drop = time.time() # время с последней потери пакета

        # переменные CUBIC
        self.w_max = 42
        
        super().__init__() # наследование от класса родителя параметров

    def select_next_action(self, state: torch.tensor):
        """Выполнение следующего действия."""
        
        sample = random.random() # определяем выборку значений
        eps_threshold = self.hyperparameters['EPS_END'] + (self.hyperparameters['EPS_START'] - self.hyperparameters['EPS_END']) * \
            math.exp(-1. * self.episode / self.hyperparameters['EPS_DECAY'])
        if sample > eps_threshold:
            with torch.no_grad():
                return self.policy_net(state.unsqueeze(0)).max(1)[1].view(1, 1)
        else:
            return torch.tensor([[random.randrange(len(self.hyperparameters['Actions']))]], device=self.device, dtype=torch.long)


    def window_is_open(self) -> bool:
        """Открытие окна передачи."""
        # next_ack - порядковый номер следующего подтверждения, которое ожидает получатель. 
        # Если промежуток между next_ack и seq_num больше, чем у окна перегрузки, тогда нам нужно дождаться появления новых подтверждений.
        return self.seq_num - self.next_ack < self.cwnd

    def next_packet_to_send(self) -> Optional[str]:
        """Организация передачи."""
        
        send_data = None
        in_greater_than_one_retransmit = False
        if self.retransmitting_packet and self.time_of_retransmit and time.time() - self.time_of_retransmit > self.timeout:
            # Если время повторной передачи истекло, то отправление пакета происходит повторно
            self.retransmitting_packet = False
            in_greater_than_one_retransmit = True

        if self.fast_retransmit_packet and not self.retransmitting_packet:
            # Логика повторной отправки пакета
            self.unacknowledged_packets[self.fast_retransmit_packet['seq_num']]['send_ts'] = time.time()
            send_data = self.fast_retransmit_packet
            send_data['is_retransmit'] = True
            serialized_data = json.dumps(send_data)
            self.retransmitting_packet = True
            self.time_of_retransmit = time.time()

        elif self.window_is_open():
            send_data = {
                'seq_num': self.seq_num,
                'send_ts': time.time(),
                'cwnd': self.cwnd,
                'is_retransmit': False
            }

            self.unacknowledged_packets[self.seq_num] = send_data
            self.seq_num += 1
        elif not self.fast_retransmit_packet:
            # Проверяем, не истек ли тайм-аут каких-либо сегментов.
            # Традиционный TCP использует экспоненциальный откат для вычисления тайм-аутов
            for seq_num, segment in self.unacknowledged_packets.items():
                if seq_num < self.seq_num and time.time() - segment['send_ts'] > self.timeout:
                    segment['send_ts'] = time.time()
                    segment['is_retransmit'] = True
                    # Обновление обучения с подкреплением на основе предыдущего увеличения размера окна перегрузки
                    self.handle_packet_loss(seq_num, segment)
                    return json.dumps(segment)

        if send_data is None:
            return None
        else:
            return json.dumps(send_data)

    def handle_packet_loss(self, seq_num: int, segment: Dict):
        """Исправление потери пакетов."""
        self.fast_retransmitted_packets_in_flight.append(seq_num)
        self.fast_retransmit_packet = segment
        self.sequence_history_dict[seq_num] = {
            'cwnd': segment['cwnd'],
            'rtt': 0,
            'dropped_packet': True
        }
        current_state = self.compute_state(max(seq_num - self.hyperparameters['STATE_WINDOW_SIZE'], 0), seq_num)
        current_state = self.state_to_tensor(current_state)

        current_action = self.select_next_action(current_state)
        self.take_action(current_action)
        self.update_q_function(seq_num, 0, True)

    def compute_w_cubic(self, t: float) -> int:
        """Вычисление параметров."""
        k = (self.w_max * ((1 - BETA_CUBIC)/CUBIC_CONSTANT)) ** (1/3)
        return 4 * (((t)-k) ** 3) + self.w_max

    def process_ack(self, serialized_ack: str) -> None:
        """Реализация процесса передачи следующего пакета."""
        ack = json.loads(serialized_ack)
        if ack.get('handshake'):
            return

        self.total_acks += 1
        self.times_of_acknowledgements.append(((time.time() - self.start_time), ack['seq_num']))

        if self.unacknowledged_packets.get(ack['seq_num']) is None:
            # Дублирование ack
            self.num_duplicate_acks += 1
            if self.duplicated_ack and ack['seq_num'] == self.duplicated_ack['seq_num']:
                self.curr_duplicate_acks += 1
            else:
                self.duplicated_ack = ack
                self.curr_duplicate_acks = 1

            if self.curr_duplicate_acks == 3 and (ack['seq_num'] + 1) not in self.fast_retransmitted_packets_in_flight:
                # При получении 3 дублированных подтверждений возникает повторная передача
                self.handle_packet_loss(ack['seq_num'] + 1, self.unacknowledged_packets[ack['seq_num'] + 1])
        elif ack['seq_num'] >= self.next_ack:
            if self.fast_retransmit_packet is not None:
                self.fast_retransmit_packet = None
                self.retransmitting_packet = False
                self.curr_duplicate_acks = 0
                self.seq_num = ack['seq_num'] + 1

                self.fast_retransmitted_packets_in_flight = []

            # Подтверждаем все пакеты, где seq_num <ack ['seq_num']
            self.unacknowledged_packets = {
                k:v
                for k,v in
                self.unacknowledged_packets.items()
                if k > ack['seq_num']
            }
            self.next_ack = max(self.next_ack, ack['seq_num'] + 1)
            self.seq_num = self.next_ack
            self.ack_count += 1
            self.sent_bytes = ack['ack_bytes']
            rtt = float(time.time() - ack['send_ts'])
            self.rtts.append(rtt)
            self.rtt_recordings.append((rtt))
            if self.base_rtt is None:
                self.base_rtt = rtt

            self.timeout = rtt * 1.2
            self.sequence_history_dict[ack['seq_num']] = {
                'cwnd': self.cwnd,
                'rtt': rtt,
                'dropped_packet': False,
                'seq_num': ack['seq_num']
            }
            
            current_state = self.compute_state(max(ack['seq_num'] - self.hyperparameters['STATE_WINDOW_SIZE'], 0), ack['seq_num'])
            current_state = self.state_to_tensor(current_state)

            current_action = self.select_next_action(current_state)
            self.take_action(current_action)

            # переход к q-функции
            if len(self.unacknowledged_packets.keys()) == 0:
                reward_packet = int(self.cwnd) + ack['seq_num']
            else:
                reward_packet =  (int(self.cwnd) - len(self.unacknowledged_packets)) + max(self.unacknowledged_packets.keys())

            self.next_packet_rewards[reward_packet] = (
                (max(ack['seq_num'] - self.hyperparameters['STATE_WINDOW_SIZE'], 0), ack['seq_num']),
                torch.tensor([int(current_action)], device=self.device, dtype=torch.long)
            )
            self.update_q_function(ack['seq_num'], rtt)

        self.cwnds.append((self.cwnd))

    def state_to_tensor(self, state: List) -> torch.Tensor:
        """Построение многомерной матрицы состояний."""
        
        current_state = [[ elem[feature] for feature in self.hyperparameters['FEATURES'] ] for elem in state ]
        pad = [[0.0] * len(self.hyperparameters['FEATURES']) ] * (self.hyperparameters['STATE_WINDOW_SIZE'] - len(current_state))
        current_state = pad + current_state
        return torch.tensor(current_state, device=self.device)

    def take_action(self, action: int):
        """Выполнение действий"""
        if action == self.hyperparameters['Actions']['INCREASE_QUADRATIC']:
            self.cwnd = self.compute_w_cubic(time.time() - self.time_since_last_drop)
        elif action == self.hyperparameters['Actions']['INCREASE_ABSOLUTE']:
            self.cwnd = self.cwnd + self.hyperparameters['ABSOLUTE_CHANGE']/self.cwnd
        elif action == self.hyperparameters['Actions']['DECREASE_PERCENT']:
            self.cwnd = max(self.cwnd * (1 - self.hyperparameters['PERCENT_CHANGE']), 1)
        elif action == self.hyperparameters['Actions']['DECREASE_ABSOLUTE']:
            self.cwnd = max(self.cwnd - self.hyperparameters['ABSOLUTE_CHANGE'], 1)
        elif action == self.hyperparameters['Actions']['DECREASE_DRAMATIC']:
            self.cwnd = max(self.cwnd * (1 - self.hyperparameters['DRAMATIC_PERCENT_CHANGE']), 1)
        elif action == self.hyperparameters['Actions']['STAY']:
            self.cwnd = self.cwnd
        elif action == self.hyperparameters['Actions']['UPDATE_WMAX']:
            self.w_max = self.cwnd
        elif action == self.hyperparameters['Actions']['RESET_CONGESTION_AVOIDANCE_TIME']:
            self.time_since_last_drop = time.time()

    def update_q_function(self, seq_num: int, rtt: float = None, dropped_packet: bool = False):
        """Обновление Q-функции."""

        if self.next_packet_rewards.get(seq_num):
            # Теперь можно добавить к функции Q состояния, награду за выполнение и следующее состояние 
            sequence_range, action = self.next_packet_rewards.get(seq_num)

            state = self.compute_state(*sequence_range) # состояние
            next_state = self.compute_state(max(seq_num - self.hyperparameters['STATE_WINDOW_SIZE'], 0), seq_num) # следующее состояние

            reward = self.compute_reward(rtt, action, dropped_packet) # награда

            self.transitions.append(
                Transition(
                    self.state_to_tensor(state).unsqueeze(0),
                    action,
                    self.state_to_tensor(next_state).unsqueeze(0),
                    torch.tensor([reward], device=self.device, dtype=torch.float)
                )
            )
            loss = optimize_model(
                policy_net=self.policy_net,
                target_net=self.target_net,
                device=self.device,
                optimizer=self.optimizer,
                transitions=self.transitions,
                batch_size=self.hyperparameters['BATCH_SIZE'],
                reward_decay=self.hyperparameters['REWARD_DECAY']
            )
            self.losses.append(loss)

            del self.next_packet_rewards[seq_num]

    def compute_state(self, begin: int, end: int) -> List[Dict]:
        """Вычисление состояний."""
        return list(list(zip(*sorted([(seq_num, state)
            for seq_num, state in self.sequence_history_dict.items()
            if seq_num >= begin and seq_num <= end], key=itemgetter(0))[-self.hyperparameters['STATE_WINDOW_SIZE']:]))[1])

    def compute_reward(self, rtt: float, action: int, dropped_packet: bool):
        """Вычисление награды."""
        if dropped_packet:
            return self.hyperparameters['Rewards']['DROPPED_PACKET']
        elif rtt > (self.base_rtt * 10):
            return self.hyperparameters['Rewards']['RTT_IS_WAY_TOO_BIG']
        elif rtt > (self.base_rtt * self.hyperparameters['RTT_DRAMATIC_CHANGE_THRESHOLD']):
            return self.hyperparameters['Rewards']['DRAMATIC_RTT_INCREASE']
        elif rtt > (self.base_rtt * self.hyperparameters['RTT_CHANGE_THRESHOLD']):
            return self.hyperparameters['Rewards']['INCREASED_RTT']
        elif rtt > (self.base_rtt * 1.4):
            return self.hyperparameters['Rewards']['MINOR_RTT_INCREASE']
        elif action == self.hyperparameters['Actions']['INCREASE_QUADRATIC']:
            return self.hyperparameters['Rewards']['INCREASED_CWND_PERCENTAGE']
        elif action == self.hyperparameters['Actions']['INCREASE_ABSOLUTE']:
            return self.hyperparameters['Rewards']['INCREASED_CWND_ABSOLUTE']
        else:
            return self.hyperparameters['Rewards']['NO_REWARD']
