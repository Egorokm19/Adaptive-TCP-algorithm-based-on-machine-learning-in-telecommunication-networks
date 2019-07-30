import sys
import json
import socket
import select
import time
from typing import List, Dict, Optional
from src.algorithm import SenderAlgorithm

# Используем метод POLL() - метод опроса сокетов
READ_FLAGS = select.POLLIN | select.POLLPRI # метод приема входящих данных
WRITE_FLAGS = select.POLLOUT # метод перадчи исходящих данных
ERR_FLAGS = select.POLLERR | select.POLLHUP | select.POLLNVAL
READ_ERR_FLAGS = READ_FLAGS | ERR_FLAGS
ALL_FLAGS = READ_FLAGS | WRITE_FLAGS | ERR_FLAGS


class Sender():
    """Класс отправителя."""
    def __init__(self, port: int, algorithm: SenderAlgorithm) -> None:
        self.port = port # порт отправителя
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM) # создаем сокет
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1) # просулшиваем соединение
        self.sock.bind(('0.0.0.0', port)) # подключаемся
        self.poller = select.poll() # метод опроса сокетов, используется в Linux
        self.poller.register(self.sock, ALL_FLAGS)
        self.poller.modify(self.sock, ALL_FLAGS)
        self.peer_addr = None

        self.algorithm = algorithm

    def send(self) -> None:
        next_segment =  self.algorithm.next_packet_to_send()
        if next_segment is not None:
            self.sock.sendto(next_segment.encode(), self.peer_addr) # type: ignore
        time.sleep(0)

    def recv(self):
        serialized_ack, addr = self.sock.recvfrom(1600)
        self.algorithm.process_ack(serialized_ack.decode())


    def handshake(self):
        """Алгоритм рукопожатие для установления связи с приемником."""

        while True:
            msg, addr = self.sock.recvfrom(1600)
            parsed_handshake = json.loads(msg.decode())
            if parsed_handshake.get('handshake') and self.peer_addr is None:
                self.peer_addr = addr
                self.sock.sendto(json.dumps({'handshake': True}).encode(), self.peer_addr)
                print('[Отправитель] Подключен к получателю: %s:%s\n' % addr)
                break
        self.sock.setblocking(0)

    def run(self, seconds_to_run: int):
        """Запуск соединения."""
        curr_flags = ALL_FLAGS
        TIMEOUT = 1000  # мс
        start_time = time.time()

        while time.time() - start_time < seconds_to_run:

            events = self.poller.poll(TIMEOUT)
            if not events:
                self.send()
            for fd, flag in events:
                assert self.sock.fileno() == fd

                if flag & ERR_FLAGS:
                    sys.exit('Произошла ошибка в канале')

                if flag & READ_FLAGS:
                    self.recv()

                if flag & WRITE_FLAGS:
                    self.send()
