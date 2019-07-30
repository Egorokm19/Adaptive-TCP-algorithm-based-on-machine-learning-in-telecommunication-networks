import matplotlib.pyplot as plt
from subprocess import Popen
import socket
from threading import Thread
from typing import Dict, List
from src.senders import Sender

# запуск сервера
RECEIVER_FILE = "run_receiver.py"
AVERAGE_SEGMENT_SIZE = 80 # средний размер сегмента

def gnt_mah_command(mah_settings: Dict) -> str:
    """Генерирование подключения."""
    if mah_settings.get('loss'):
        loss_directive = "mm-loss downlink %f" % mah_settings.get('loss')
    else:
        loss_directive = ""
    return "mm-delay {delay} {loss_directive} mm-link traces/{trace_file} traces/{trace_file} --downlink-queue=droptail --downlink-queue-args=bytes={queue_size}".format(
      delay=mah_settings['delay'],
      queue_size=mah_settings['queue_size'],
      loss_directive=loss_directive,
      trace_file=mah_settings['trace_file']
    )
def open_tcp_port():
    """Открытие порта для подключения"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

colorsen = ["blue", "red", "yellow", "green", "magenta", "cyan", "black"]  
    
def print_performance(senders: List[Sender], num_seconds: int):
    """Вывод значений основных параметров."""
    
    for sender in senders:
        print("Результаты для отправителя %d, с алгоритмом: %s" % (sender.port, sender.algorithm.__class__.__name__))
        print("Всего Acks: %d" % sender.algorithm.total_acks)
        print("Количество дубликатов Acks: %d" % sender.algorithm.num_duplicate_acks)

        print("%% дубликат acks: %f" % ((float(sender.algorithm.num_duplicate_acks * 100))/sender.algorithm.total_acks))
        print("Пропускная способность (бит/с): %f" % (AVERAGE_SEGMENT_SIZE * (sender.algorithm.ack_count/num_seconds)))
        print("Среднее значение задержки RTT (мс): %f" % ((float(sum(sender.algorithm.rtts))/len(sender.algorithm.rtts)) * 1000))
        print("\n")

        timestamps = [ ack[0] for ack in sender.algorithm.times_of_acknowledgements]
        seq_nums = [ ack[1] for ack in sender.algorithm.times_of_acknowledgements]

        plt.scatter(timestamps, seq_nums)
        plt.xlabel("Временные метки")
        plt.ylabel("Порядковый номер")
        plt.grid(True)
        plt.show()

    handles = []
    for index, sender in enumerate(senders):
        plt.plot(sender.algorithm.cwnds, c = colorsen[index], label = sender.algorithm.__class__.__name__)
    plt.legend()
    plt.xlabel("Время (мс)")
    plt.ylabel("Размер окна перегрузки")
    plt.grid(True)
    plt.show()
    print("")

    for index, sender in enumerate(senders):
        plt.plot(sender.algorithm.rtt_recordings, c = colorsen[index], label = sender.algorithm.__class__.__name__)
    plt.legend()
    plt.xlabel("Время (мс)")
    plt.ylabel("Среднее значение задержки RTT")
    plt.grid(True)
    plt.show()
    
    for index, sender in enumerate(senders):
        if len(sender.algorithm.slow_start_thresholds) > 0:
            plt.plot(sender.algorithm.slow_start_thresholds, c = colorsen[index], label = sender.algorithm.__class__.__name__)
    if any([len(sender.algorithm.slow_start_thresholds) > 0 for sender in senders]):
        plt.legend()
        plt.xlabel("Время (мс)")
        plt.ylabel("Порог медленного старта")
        plt.grid(True)
        plt.show()
    print("")
    
def run_mah_settings(mah_settings: Dict, seconds_to_run: int, senders: List):
    """Запуск алгоритма с заданными парметрами."""
    mah_cmd = gnt_mah_command(mah_settings)

    sender_ports = " ".join(["$MAHIMAHI_BASE %s" % sender.port for sender in senders])
    
    cmd = "%s -- sh -c 'python3 %s %s'" % (mah_cmd, RECEIVER_FILE, sender_ports)
    receiver_process = Popen(cmd, shell=True)
    for sender in senders:
        sender.handshake()
    threads = [Thread(target=sender.run, args=[seconds_to_run]) for sender in senders]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    
    print_performance(senders, seconds_to_run)
    receiver_process.kill()
