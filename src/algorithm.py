import json
import time
from typing import List, Dict, Tuple, Optional


class SenderAlgorithm():
    """Алгоритм отправителя."""
    def __init__(self) -> None:
        self.seq_num = 0 # seq_num - начальное времея передачи
        self.next_ack = 0 # передача следующего пакета
        self.sent_bytes = 0 # send_bytes - значение бита при передаче
        self.start_time = time.time() # начальное время передачи
        self.total_acks = 0 # значение передачи следующего пакета при передаче
        self.num_duplicate_acks = 0 # номер переданного дублированного пакета
        self.curr_duplicate_acks = 0 
        self.rtts: List[float] = [] # значение времени распространение пакета при приеме-передаче (круговая задержка)
        self.cwnds: List[int] = [] # значение окна перегрузки
        self.rtt_recordings: List[Tuple] = [] # значение круговой задержки
        self.unacknowledged_packets: Dict = {} # значение потерянных пакетов 
        self.times_of_acknowledgements: List[Tuple[float, int]] = [] # время подтверждения
        self.ack_count = 0 
        self.slow_start_thresholds: List[Tuple] = [] # значение медленного старта
        self.time_of_retransmit: Optional[float] = None # время передачи 

    def next_packet_to_send(self):
        """Создание следующего пакета для отправки."""
        raise NotImplementedError # создание абстрактного метода для переопределения значений

    def process_ack(self, ack: str):
        """Процесс передачи следующего пакета."""
        raise NotImplementedError  # создание абстрактного метода для переопределения значений


class FixedWindowAlgorithm(SenderAlgorithm):
    """Реализация алгоритма фиксированного окна."""
    def __init__(self, cwnd: int) -> None:
        self.cwnd = cwnd

        super().__init__()

    def window_is_open(self) -> bool:
        """Возвращает True, если окно перегрузки не заполнено.""" 
        return self.seq_num - self.next_ack < self.cwnd

    def next_packet_to_send(self) -> Optional[str]:
        if not self.window_is_open():
            return None

        serialized_data = json.dumps({
            'seq_num': self.seq_num,
            'send_ts': time.time(),
            'sent_bytes': self.sent_bytes
        })
        self.unacknowledged_packets[self.seq_num] = True
        self.seq_num += 1
        return serialized_data

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
            self.curr_duplicate_acks += 1

            if self.curr_duplicate_acks == 3:
                # При получении 3 дублированных подтверждений возникает повторная передача
                self.curr_duplicate_acks = 0
                self.seq_num = ack['seq_num'] + 1
        else:
            del self.unacknowledged_packets[ack['seq_num']]
            self.next_ack = max(self.next_ack, ack['seq_num'] + 1)
            self.sent_bytes += ack['ack_bytes']
            rtt = float(time.time() - ack['send_ts'])
            self.rtts.append(rtt)
            self.rtt_recordings.append(rtt)
            self.timeout = rtt * 1.2
            self.ack_count += 1
        self.cwnds.append(self.cwnd)


class TahoeAlgorithm(SenderAlgorithm):
    """Реализация алгоритма TCP Tahoe."""
    def __init__(self, slow_start_thresh: int, initial_cwnd: int) -> None:
        self.slow_start_thresh = slow_start_thresh # значение медленного старта

        self.cwnd = initial_cwnd # начальное значение окна перегрузки
        self.fast_retransmit_packet = None # пакет быстрой повторной передачи
        self.time_since_retransmit = None # время с момента повторной передачи
        self.retransmitting_packet = False # передача пакетов
        self.ack_count = 0

        self.duplicated_ack = None # дублирование ack
        self.slow_start_thresholds = [] # значение порога медленного старта

        super().__init__()

    def window_is_open(self) -> bool:
        """Открытие окна передачи."""
        # next_ack - порядковый номер следующего подтверждения, которое ожидает получатель. 
        # Если промежуток между next_ack и seq_num больше, чем у окна перегрузки, тогда нам нужно дождаться появления новых подтверждений.
        return self.seq_num - self.next_ack < self.cwnd

    def next_packet_to_send(self) -> Optional[str]:
        """Организация передачи."""
        send_data = None
        if self.retransmitting_packet and self.time_of_retransmit and time.time() - self.time_of_retransmit > 1:
            # Если время повторной передачи истекло, то отправление пакета происходит повторно
            self.retransmitting_packet = False

        if self.fast_retransmit_packet and not self.retransmitting_packet:
            # Логика повторной отправки пакета
            self.unacknowledged_packets[self.fast_retransmit_packet['seq_num']]['send_ts'] = time.time()
            send_data = self.fast_retransmit_packet
            serialized_data = json.dumps(send_data)
            self.retransmitting_packet = True

            self.time_of_retransmit = time.time()

        elif self.window_is_open():
            send_data = {
                'seq_num': self.seq_num,
                'send_ts': time.time()
            }

            self.unacknowledged_packets[self.seq_num] = send_data
            self.seq_num += 1
        else:
            # Проверяем, не истек ли тайм-аут каких-либо сегментов.
            # Традиционный TCP использует экспоненциальный откат для вычисления тайм-аутов
            for seq_num, segment in self.unacknowledged_packets.items():
                if time.time() - segment['send_ts'] > 4:
                    self.unacknowledged_packets[seq_num]['send_ts'] = time.time()
                    return json.dumps(segment)

        if send_data is None:
            return None
        else:
            return json.dumps(send_data)


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

            if self.curr_duplicate_acks == 3:
                # При получении 3 дублированных подтверждений возникает повторная передача
                self.fast_retransmit_packet = self.unacknowledged_packets[ack['seq_num'] + 1]
                self.slow_start_thresh = int(max(1, self.cwnd/2))
                self.cwnd = 1
        elif ack['seq_num'] >= self.next_ack:
            if self.fast_retransmit_packet:
                self.fast_retransmit_packet = None
                self.retransmitting_packet = False
                self.curr_duplicate_acks = 0
                self.seq_num = ack['seq_num'] + 1

            # Подтверждаем все пакеты, где seq_num <ack ['seq_num']
            self.unacknowledged_packets = {
                k:v
                for k,v in
                self.unacknowledged_packets.items()
                if k > ack['seq_num']
            }
            self.next_ack = max(self.next_ack, ack['seq_num'] + 1)
            self.ack_count += 1
            self.sent_bytes += ack['ack_bytes']
            rtt = float(time.time() - ack['send_ts'])
            self.rtts.append(rtt)
            self.rtt_recordings.append(rtt)
            self.timeout = rtt * 1.2
            if self.cwnd < self.slow_start_thresh:
                # В медленном старте
                self.cwnd += 1
            elif (ack['seq_num'] + 1) % self.cwnd == 0:
                # В контроле перегрузки
                self.cwnd += 1

        self.cwnds.append(self.cwnd)
        self.slow_start_thresholds.append(self.slow_start_thresh)
        #self.rtt_recordings.append(self.rtts)

BETA_CUBIC = 0.7 # значение коэффициента алгоритма КУБИК
DEFAULT_TIMEOUT = 2
        
class CubicAlgorithm(SenderAlgorithm):
    """Реализация алгоритма TCP CUBIC."""
    def __init__(self, c: int) -> None:

        self.cwnd = 2 # начальное значение окна перегрузки
        self.fast_retransmit_packet = None # пакет быстрой повторной передачи
        self.time_since_retransmit = None # время с момента повторной передачи
        self.retransmitting_packet = False # передача пакетов
        self.ack_count = 0

        self.c = c
        self.slow_start_threshold = 42 # значение порога медленного старта
        self.w_max = 42

        self.congestion_avoidance_began_at = None # предотвращение перегрузки
        self.fast_retransmitted_packets_in_flight = [] # быстрая передаяа пакетов

        self.duplicated_ack = None # дублирование ack
        self.slow_start_thresholds = [] # значение порога медленного старта
        self.first_rtt = None
        self.timeout = DEFAULT_TIMEOUT # значение тайм-аута по умолчанию

        super().__init__() # наследование от класса родителя параметров

    def compute_w_est(self) -> int:
        """Вычисление параметров."""
        average_rtt = sum(self.rtts)/len(self.rtts) # средний RTT

        return (
            self.w_max * BETA_CUBIC + (
              ((3*(1 - BETA_CUBIC)) * (
                  (time.time() - self.congestion_avoidance_began_at)/self.first_rtt) ) /(1 + BETA_CUBIC)
            )
        )

    def compute_w_cubic(self, t: float) -> int:
        """Вычисление параметров."""
        k = (self.w_max * ((1 - BETA_CUBIC)/self.c)) ** (1/3)
        return self.c * (((t)-k) ** 3) + self.w_max

    def average_rtt(self):
        """Средний RTT."""
        return sum(self.rtts)/len(self.rtts)

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
                    self.w_max = self.cwnd
                    self.slow_start_threshold = self.cwnd * BETA_CUBIC # BETA_CUBIC = 0.7 значение коэффициента алгоритма КУБИК
                    self.slow_start_threshold = max(self.slow_start_threshold, 2)
                    self.cwnd = self.cwnd * BETA_CUBIC # 1 , BETA_CUBIC = 0.7 значение коэффициента алгоритма КУБИК
                    self.congestion_avoidance_began_at = None
                    self.fast_retransmitted_packets_in_flight.append(seq_num)
                    self.fast_retransmit_packet = segment

                    return json.dumps(segment)

        if send_data is None:
            return None
        else:
            return json.dumps(send_data)


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
                self.fast_retransmitted_packets_in_flight.append(ack['seq_num'] + 1)
                self.fast_retransmit_packet = self.unacknowledged_packets[ack['seq_num'] + 1]
                self.w_max = self.cwnd
                self.slow_start_threshold = self.cwnd * BETA_CUBIC
                self.slow_start_threshold = max(self.slow_start_threshold, 2)
                self.congestion_avoidance_began_at = None
                self.cwnd = self.cwnd * BETA_CUBIC #1
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
            if self.first_rtt is None:
                self.first_rtt = rtt
            self.rtts.append(rtt)
            self.rtt_recordings.append(rtt)
            self.timeout = rtt * 1.2

            if self.congestion_avoidance_began_at is None and self.cwnd >= self.slow_start_threshold:
                self.congestion_avoidance_began_at = time.time()

            if self.cwnd < self.slow_start_threshold:

                # В медленном старте
                self.cwnd += 1

            else:
                # В контроле перегрузки
                w_est = self.compute_w_est()
                t = (time.time() - self.congestion_avoidance_began_at)
                w_cubic = self.compute_w_cubic(t)

                if w_cubic > w_est:
                    a = (self.compute_w_cubic(t + self.first_rtt) - self.cwnd)/self.cwnd
                    self.cwnd += a
                else:
                    self.cwnd = w_est
        self.cwnds.append(self.cwnd)
        self.slow_start_thresholds.append(self.w_max)
        #self.rtt_recordings.append(self.rtts)
        
class TahoeAlgorithm1(SenderAlgorithm):
    """Реализация алгоритма TCP Tahoe.."""
    def __init__(self, slow_start_thresh: int, initial_cwnd: int) -> None:
        self.slow_start_thresh = slow_start_thresh # значение медленного старта

        self.cwnd = initial_cwnd # начальное значение окна перегрузки
        self.fast_retransmit_packet = None # пакет быстрой повторной передачи
        self.time_since_retransmit = None # время с момента повторной передачи
        self.retransmitting_packet = False # передача пакетов
        self.ack_count = 0 
        self.timeout = DEFAULT_TIMEOUT # значение тайм-аута по умолчанию
        self.fast_retransmitted_packets_in_flight = [] # быстрая передаяа пакетов

        self.duplicated_ack = None # дублирование ack
        self.slow_start_thresholds = [] # значение порога медленного старта

        super().__init__() # наследование от класса родителя параметров

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
                    self.slow_start_thresh = int(max(1, self.cwnd/2))
                    self.cwnd = 1

                    self.fast_retransmitted_packets_in_flight.append(seq_num)
                    self.fast_retransmit_packet = segment

                    return json.dumps(segment)

        if send_data is None:
            return None
        else:
            return json.dumps(send_data)


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
                self.fast_retransmitted_packets_in_flight.append(ack['seq_num'] + 1)
                self.fast_retransmit_packet = self.unacknowledged_packets[ack['seq_num'] + 1]
                self.slow_start_thresh = int(max(1, self.cwnd/2))
                self.cwnd = 1
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
            self.rtt_recordings.append(rtt)
            self.timeout = rtt * 1.2
            if self.cwnd < self.slow_start_thresh:
                # В медленном старте
                self.cwnd += 1
            elif (ack['seq_num'] + 1):
                # В контроле перегрузки
                self.cwnd += 1.0/self.cwnd

        self.cwnds.append(self.cwnd)
        self.slow_start_thresholds.append(self.slow_start_thresh)
        #self.rtt_recordings.append(self.rtts)
        
class RenoAlgorithm(SenderAlgorithm):
    """Реализация алгоритма TCP Tahoe."""
    def __init__(self, slow_start_thresh: int, initial_cwnd: int) -> None:
        self.slow_start_thresh = slow_start_thresh # значение медленного старта

        #self.initial_cwnd = initial_cwnd
        self.cwnd = initial_cwnd # начальное значение окна перегрузки
        self.fast_retransmit_packet = None # пакет быстрой повторной передачи
        self.time_since_retransmit = None # время с момента повторной передачи
        self.retransmitting_packet = False # передача пакетов
        self.ack_count = 0

        self.duplicated_ack = None # дублирование ack
        self.slow_start_thresholds = [] # значение порога медленного старта

        super().__init__()

    def window_is_open(self) -> bool:
        """Открытие окна передачи."""
        # next_ack - порядковый номер следующего подтверждения, которое ожидает получатель. 
        # Если промежуток между next_ack и seq_num больше, чем у окна перегрузки, тогда нам нужно дождаться появления новых подтверждений.
        return self.seq_num - self.next_ack < self.cwnd

    def next_packet_to_send(self) -> Optional[str]:
        """Организация передачи."""
        send_data = None
        if self.retransmitting_packet and self.time_of_retransmit and time.time() - self.time_of_retransmit > 1:
            # Если время повторной передачи истекло, то отправление пакета происходит повторно
            self.retransmitting_packet = False

        if self.fast_retransmit_packet and not self.retransmitting_packet:
            # Логика повторной отправки пакета
            self.unacknowledged_packets[self.fast_retransmit_packet['seq_num']]['send_ts'] = time.time()
            send_data = self.fast_retransmit_packet
            serialized_data = json.dumps(send_data)
            self.retransmitting_packet = True

            self.time_of_retransmit = time.time()

        elif self.window_is_open():
            send_data = {
                'seq_num': self.seq_num,
                'send_ts': time.time()
            }

            self.unacknowledged_packets[self.seq_num] = send_data
            self.seq_num += 1
        else:
            # Проверяем, не истек ли тайм-аут каких-либо сегментов.
            # Традиционный TCP использует экспоненциальный откат для вычисления тайм-аутов
            for seq_num, segment in self.unacknowledged_packets.items():
                if time.time() - segment['send_ts'] > 4:
                    self.unacknowledged_packets[seq_num]['send_ts'] = time.time()
                    return json.dumps(segment)

        if send_data is None:
            return None
        else:
            return json.dumps(send_data)


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

            if self.curr_duplicate_acks == 3:
                # При получении 3 дублированных подтверждений возникает повторная передача
                self.fast_retransmit_packet = self.unacknowledged_packets[ack['seq_num'] + 1]
                self.curr_duplicate_acks = 0
                self.seq_num = ack['seq_num'] + 1
                self.slow_start_thresh = self.cwnd/2
                self.cwnd = self.slow_start_thresh
        elif ack['seq_num'] >= self.next_ack:
            if self.fast_retransmit_packet:
                self.fast_retransmit_packet = None
                self.retransmitting_packet = False
                

            # Подтверждаем все пакеты, где seq_num <ack ['seq_num']
            self.unacknowledged_packets = {
                k:v
                for k,v in
                self.unacknowledged_packets.items()
                if k > ack['seq_num']
            }
            self.next_ack = max(self.next_ack, ack['seq_num'] + 1)
            self.ack_count += 1
            self.sent_bytes += ack['ack_bytes']
            rtt = float(time.time() - ack['send_ts'])
            self.rtts.append(rtt)
            self.rtt_recordings.append(rtt)
            self.timeout = rtt * 1.2
            if self.cwnd < self.slow_start_thresh:
                # В медленном старте
                self.cwnd += 1
            elif (ack['seq_num'] + 1) % self.cwnd == 0:
                # В контроле перегрузки
                self.cwnd += 1

        self.cwnds.append(self.cwnd)
        self.slow_start_thresholds.append(self.slow_start_thresh)
        #self.rtt_recordings.append(self.rtts)