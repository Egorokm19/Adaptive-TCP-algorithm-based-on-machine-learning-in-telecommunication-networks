import random
import torch
import torch.nn as nn
import torch.nn.functional as F

from collections import namedtuple

# Transition - именованный кортеж, представляющий один переход в нашей среде и составляет пары состояния или действия ('state', 'action') с их результатом ('next_state', 'reward')
Transition = namedtuple('Transition',
                        ('state', 'action', 'next_state', 'reward'))

def optimize_model(policy_net, target_net, device, optimizer, transitions, batch_size, reward_decay):
    """Шаг оптимизации."""
    
    if (len(transitions) < batch_size):
        return

    transitions = random.sample(transitions, batch_size) # именованный кортеж
    batch = Transition(*zip(*transitions)) # пакет
    state_batch = torch.cat(batch.state) # определение состояния пакета 
    action_batch = torch.cat(batch.action) # активация
    reward_batch = torch.cat(batch.reward) # награда за определение пакета

    predicted_actions = policy_net(state_batch) # прогнозируемое действие

    state_action_values = predicted_actions.gather(1, action_batch.unsqueeze(-1)) # определение значения состояния активации

    next_state_values = target_net(state_batch).max(1)[0].detach() # определение следующего значения
    expected_state_action_values = (next_state_values * reward_decay) + reward_batch # ожидаемое значение активации
    loss = F.smooth_l1_loss(state_action_values, expected_state_action_values.unsqueeze(1)) # определение потери

    optimizer.zero_grad() # устанавливаем значение градиента на 0, прежде чем активировать обратные связи
    loss.backward() # накапливаем значения градиента при каждом вызове

    for param in policy_net.parameters():
        param.grad.data.clamp_(-1, 1)
    optimizer.step()

    return loss.data.item()


class LSTM_DQN(nn.Module):
    """Использование Q-функции."""
    def __init__(self, config, device, use_cuda=False):
        super(LSTM_DQN, self).__init__()
        self.config = config
        self.device = device # использование GPU
        self.W = nn.LSTM(config["input_dim"], config["hidden_dim"], batch_first=True, bidirectional=config["bidirectional"], num_layers=config["num_layers"]) # матрица параметров
        # присвоение значение параметру веса, где bidirectional - соединяют два скрытых слоя противоположных направлений к одному выходу, hidden_dim - скрытые слои, input_dim - количество признаков
        # обратное распространение по времени bidirectional
        if config["bidirectional"]:
            self.h0, self.c0 = (torch.zeros(2 * config["num_layers"], 1, config["hidden_dim"], device=device),
                    torch.zeros(2 * config["num_layers"], 1, config["hidden_dim"], device=device))
            # h0 - выходной вектро и c0 - вектор состояний
            self.U = nn.Linear(config["hidden_dim"] * 2, config["output_dim"]) # матрица параметров
        else:
            self.h0, self.c0 = (torch.zeros(config["num_layers"], 1, config["hidden_dim"], device=device),
                    torch.zeros(config["num_layers"], 1, config["hidden_dim"], device=device)) # h0 - выходной вектро и c0 - вектор состояний
            self.U = nn.Linear(config["hidden_dim"],config["output_dim"])  # матрица параметров
        
        # if use_cuda:
        #     self.h0.cuda()
        #     self.c0.cuda()

        for param in self.W.parameters():
            if len(param.size()) > 1:
                nn.init.orthogonal_(param)

        for param in self.U.parameters():
            if len(param.size()) > 1:
                nn.init.orthogonal_(param)

    def forward(self, x):
        """Применение LSTM."""
        
        # определеяем выборку значений
        batch_len, _, _ = x.size()

        # обработка матриц
        h0 = self.h0.repeat(1, batch_len, 1).to(device=self.device)
        c0 = self.c0.repeat(1, batch_len, 1).to(device=self.device)

        out, _ = self.W(x, (h0,c0))

        return self.U(out[:,-1,:])
