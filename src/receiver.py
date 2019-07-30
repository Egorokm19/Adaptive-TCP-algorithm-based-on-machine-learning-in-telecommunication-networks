import sys
import json
import socket
import select
import time
from typing import List, Dict, Tuple

# Используем метод POLL() - метод опроса сокетов
READ_FLAGS = select.POLLIN | select.POLLPRI # метод приема входящих данных
WRITE_FLAGS = select.POLLOUT # метод перадчи исходящих данных
ERR_FLAGS = select.POLLERR | select.POLLHUP | select.POLLNVAL
READ_ERR_FLAGS = READ_FLAGS | ERR_FLAGS
ALL_FLAGS = READ_FLAGS | WRITE_FLAGS | ERR_FLAGS

# Инициализируем значение для размещения размера окна перегрузки
RECEIVE_WINDOW = 100000

class Peer():
    """Считывание основных парметров."""
    def __init__(self, port: int, window_size: int) -> None:
        self.window_size = window_size # размер окна перегрузки
        self.port = port # порт
        self.seq_num = -1 # seq_num - начальное значение передачи
        self.attempts = 0
        self.previous_ack = None
        self.high_water_mark = -1
        self.window: List[Dict] = [] # значение окна

    def window_has_no_missing_segments(self):
        """Работа окна перегрузки при отсутствии сегментов."""
        seq_nums = [seg['seq_num'] for seg in self.window]
        return all([seq_nums[i] + 1 ==  seq_nums[i+1] for i in range(len(seq_nums[:-1]))])

    def process_window(self):
        """Процесс заполнения окна."""
        seq_nums = [seg['seq_num'] for seg in self.window]
        if self.window_has_no_missing_segments():
            self.high_water_mark = max(self.high_water_mark, self.window[-1]['seq_num'])
            self.window = self.window[-1:]
        elif len(self.window) == self.window_size:
            self.window = self.window[:-1]
            print("Разделение окна")

    def add_segment(self, ack: Dict):
        """Добавление сегментов."""
        seq_num = ack['seq_num']

        if all([seq_num != item['seq_num'] for item in self.window]):
            self.window.append(ack)
        self.window.sort(key=lambda a: a['seq_num'])

        self.process_window()

    def next_ack(self):
        for i in range(len(self.window[:-1])):
            if self.window[i + 1]['seq_num'] > self.window[i]['seq_num'] + 1:
                return self.window[i]
        else:
            return self.window[-1]

class Receiver():
    """Получатель пакетов."""
    def __init__(self, peers: List[Tuple[str, int]], window_size: int = RECEIVE_WINDOW) -> None:
        self.recv_window_size = window_size
        self.peers: Dict[Tuple, Peer] = {}
        for peer in peers:
            self.peers[peer] = Peer(peer[1], window_size)

        # UDP socket и poller
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        self.poller = select.poll()
        self.poller.register(self.sock, ALL_FLAGS)

    def cleanup(self):
        """Выход из соединения."""
        self.sock.close()

    def construct_ack(self, serialized_data: str):
        """Создаем ACK, который подтверждает переданную дейтаграмму."""
        data = json.loads(serialized_data)
        return {
          'seq_num': data['seq_num'],
          'send_ts': data['send_ts'],
          'ack_bytes': len(serialized_data)
        }

    def perform_handshakes(self):
        """Рукопожатие с равноправным отправителем, вызывается через run()."""

        self.sock.setblocking(0)  # non-blocking TCP socket

        TIMEOUT = 1000  # мс

        retry_times = 0
        self.poller.modify(self.sock, READ_ERR_FLAGS)
        # копируем знаения self.peers
        unconnected_peers = list(self.peers.keys())

        while len(unconnected_peers) > 0:
            for peer in unconnected_peers:
                self.sock.sendto(json.dumps({'handshake': True}).encode(), peer)

            events = self.poller.poll(TIMEOUT)

            if not events:  # timed out
                retry_times += 1
                if retry_times > 10:
                    sys.stderr.write(
                        '[получатель] Рукопожатие не удалось после 10 попыток\n')
                    return
                else:
                    sys.stderr.write(
                        '[получатель] Время рукопожатия истекло и повторная попытка...\n')
                    continue

            for fd, flag in events:
                assert self.sock.fileno() == fd

                if flag & ERR_FLAGS:
                    sys.exit('Канал закрыт или произошла ошибка')

                if flag & READ_FLAGS:
                    msg, addr = self.sock.recvfrom(1600)

                    if addr in unconnected_peers:
                        if json.loads(msg.decode()).get('handshake'):
                            unconnected_peers.remove(addr)

    def run(self):
        self.sock.setblocking(1)  # блокирование TCP socket
        
        while True:
            serialized_data, addr = self.sock.recvfrom(1600)

            if addr in self.peers:
                peer = self.peers[addr]

                data = json.loads(serialized_data)
                seq_num = data['seq_num']
                if seq_num > peer.high_water_mark:
                    ack = self.construct_ack(serialized_data)
                    peer.add_segment(ack)
                    print(len(peer.window))

                    if peer.next_ack() is not None:
                        self.sock.sendto(json.dumps(peer.next_ack()).encode(), addr)
