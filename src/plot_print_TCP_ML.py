import matplotlib.pyplot as plt
import re
import os
from subprocess import Popen
import socket
from threading import Thread
from typing import Dict, List
from src.senders import Sender
from os.path import join

# запуск сервера
RECEIVER_FILE = "run_receiver.py"
AVERAGE_SEGMENT_SIZE = 80
# файлы очереди
QUEUE_LOG_FILE = "downlink_queue.log"
QUEUE_LOG_TMP_FILE = "downlink_queue_tmp.log"

DROP_LOG = "debug_log.log"
DROP_LOG_TMP_FILE = "debug_log_tmp.log"

def gnt_mah_command(mah_settings: Dict) -> str:
    """Генерирование подключения."""
    if mah_settings.get('loss'):
        loss_directive = "mm-loss downlink %f" % mah_settings.get('loss')
    else:
        loss_directive = ""

    queue_type =  mah_settings.get('queue_type', 'droptail')
    
    if mah_settings.get('downlink_queue_options'):
        downlink_queue_options = "--downlink-queue-args=" + ",".join(
             ["%s=%s" % (key, value)
             for key, value in mah_settings.get('downlink_queue_options').items()]
        )
    else:
        downlink_queue_options = ""

    if mah_settings.get('uplink_queue_options'):
        uplink_queue_options = " ".join(
            ["--downlink-queue-args=%s=%s" % (key, value)
             for key, value in mah_settings.get('uplink_queue_options').items()]
        )
    else:
        uplink_queue_options = ""

    return "mm-delay {delay} {loss_directive} mm-link traces/{trace_file} traces/{trace_file} --downlink-queue={queue_type} {downlink_queue_options} {uplink_queue_options} --downlink-log={queue_log_file}".format(
      delay = mah_settings['delay'],
      downlink_queue_options = downlink_queue_options,
      uplink_queue_options = uplink_queue_options,
      loss_directive = loss_directive,
      trace_file = mah_settings['trace_file'],
      queue_type = queue_type,
      queue_log_file = QUEUE_LOG_FILE)

def open_tcp_port():
    """Открытие порта для подключения"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

    s.bind(('', 0))
    port = s.getsockname()[1]
    s.close()
    return port

colorsen = ["blue", "red", "yellow", "green", "magenta", "cyan", "black"]

def print_performance(senders: Sender, num_seconds: int, episode_num: int, write_to_disk: bool , output_dir: str, experiment_dir:str):
    """Вывод значений основных параметров."""
    if write_to_disk:
        with open(join(experiment_dir,  "episode_" + str(episode_num) + "_stats.txt" ), 'w') as out_stats:
            for sender in senders:
                out_stats.write("Результаты для отправителя %d, с алгоритмом: %s" % (sender.port,sender.algorithm.__class__.__name__) + "\n")
                out_stats.write("Пропускная способность (bytes/s): %f" % (AVERAGE_SEGMENT_SIZE * (sender.algorithm.ack_count/num_seconds)) + "\n")
                out_stats.write("Среднее значение задержки RTT (ms): %f" % ((float(sum(sender.algorithm.rtts))/len(sender.algorithm.rtts)) * 1000) + "\n")
                out_stats.write("\n")
    else:
        for sender in senders:
            print("Результаты для отправителя %d, с алгоритмом: %s" % (sender.port, sender.algorithm.__class__.__name__))
            print("Пропускная способность (бит/с): %f" % (AVERAGE_SEGMENT_SIZE * (sender.algorithm.ack_count/num_seconds)))
            print("Среднее значение задержки RTT (ms): %f" % ((float(sum(sender.algorithm.rtts))/len(sender.algorithm.rtts)) * 1000))
            print("")


    # Вычисляем очередь
    #queue_log_lines = open(QUEUE_LOG_TMP_FILE).read().split("\n")[1:]
    #regex = re.compile("\d+ # (\d+)")
 
    #plt.plot([int(regex.match(line).group(1)) for line in queue_log_lines if regex.match(line) is not None])

    #plt.xlabel("Время")
    #plt.ylabel("Размер очереди канала")
    #plt.grid(True)
    #plt.show()
    
    # save
    #if write_to_disk:
        #plt.savefig(join(experiment_dir, "episode_" + str(episode_num) + "_link-queue-size.png" ))
        #plt.close()
    #else:
       # plt.show()

    handles = []
    for indx, sender in enumerate(senders):
        plt.plot(sender.algorithm.cwnds, c = colorsen[indx], label = sender.algorithm.__class__.__name__)
    plt.legend()
    plt.xlabel("Время (с)")
    plt.ylabel("Размер окна перегрузки")
    plt.grid(True)
    plt.show()
    plt.grid(True)
    print("")

    # save
    if write_to_disk:
        plt.savefig(join(experiment_dir, "episode_" + str(episode_num) + "_cwnd.png" ))
        plt.close()
    else:
        plt.show()
        print("")

    for indx, sender in enumerate(senders):
        plt.plot(sender.algorithm.rtt_recordings, c = colorsen[indx], label=sender.algorithm.__class__.__name__)
    plt.legend()
    plt.xlabel("Время (мс)")
    plt.ylabel("Среднее значение задержки RTT (ms)")
    plt.grid(True)
    plt.show()
    
    # save
    if write_to_disk:
        plt.savefig(join(experiment_dir, "episode_" + str(episode_num) +"_rtt.png" ))
        plt.close()
    else:
        plt.show()

def run_mah_settings(mah_settings: Dict, seconds_to_run: int, senders: List, should_print_performance: bool , episode_num: int, write_to_disk: bool, output_dir: str, experiment_dir: str):
    """Запуск алгоритма с заданными парметрами."""
    
    mah_cmd = gnt_mah_command(mah_settings)    
    sender_ports = " ".join(["$MAHIMAHI_BASE %s" % sender.port for sender in senders])

    cmd = "%s -- sh -c 'python3 %s %s'" % (mah_cmd, RECEIVER_FILE, sender_ports)
    Popen(cmd, shell=True)
    
    for sender in senders:
        sender.handshake()
    threads = [Thread(target=sender.run, args=[seconds_to_run]) for sender in senders]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    os.rename(QUEUE_LOG_FILE, QUEUE_LOG_TMP_FILE)
    #os.rename(DROP_LOG, DROP_LOG_TMP_FILE)

    if should_print_performance:
        print_performance(senders, seconds_to_run, episode_num, write_to_disk, output_dir, experiment_dir)
    Popen("pkill -f mm-link", shell=True).wait()
    Popen("pkill -f run_receiver", shell=True).wait()
    
    
def print_performance_ML(senders: Sender, num_seconds: int, episode_num: int):
    """Вывод значений основных параметров."""
    
    for sender in senders:
        print("Результаты для отправителя %d, с алгоритмом: %s" % (sender.port, sender.algorithm.__class__.__name__))
        print("Пропускная способность (бит/с): %f" % (AVERAGE_SEGMENT_SIZE * (sender.algorithm.ack_count/num_seconds)))
        print("Среднее значение задержки RTT (мс): %f" % ((float(sum(sender.algorithm.rtts))/len(sender.algorithm.rtts)) * 1000))
        print("")


    # Вычисляем очередь
    #queue_log_lines = open(QUEUE_LOG_TMP_FILE).read().split("\n")[1:]
    #regex = re.compile("\d+ # (\d+)")

    #plt.plot([int(regex.match(line).group(1)) for line in queue_log_lines if regex.match(line) is not None])

    #plt.xlabel("Время")
    #plt.ylabel("Размер очереди канала")
    #plt.grid(True)
    #plt.show()
    
    handles = []
    for indx, sender in enumerate(senders):
        plt.plot(sender.algorithm.cwnds, c = colorsen[indx], label = sender.algorithm.__class__.__name__)
    plt.legend()
    plt.xlabel("Время")
    plt.ylabel("Размер окна перегрузки")
    plt.grid(True)
    plt.show()
    print("")

    for indx, sender in enumerate(senders):
        plt.plot(sender.algorithm.rtt_recordings, c = colorsen[indx], label = sender.algorithm.__class__.__name__)
    plt.legend()
    plt.xlabel("Время")
    plt.ylabel("Среднее значение задержки RTT")
    plt.grid(True)
    plt.show()

def run_mah_settings_ML(mah_settings: Dict, seconds_to_run: int, senders: List, should_print_performance_ML: bool , episode_num: int):
    """Запуск алгоритма с заданными парметрами."""
    
    mah_cmd = gnt_mah_command(mah_settings)    
    sender_ports = " ".join(["$MAHIMAHI_BASE %s" % sender.port for sender in senders])

    cmd = "%s -- sh -c 'python3 %s %s'" % (mah_cmd, RECEIVER_FILE, sender_ports)
    Popen(cmd, shell=True)
    
    for sender in senders:
        sender.handshake()
    threads = [Thread(target = sender.run, args = [seconds_to_run]) for sender in senders]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    os.rename(QUEUE_LOG_FILE, QUEUE_LOG_TMP_FILE)
    #os.rename(DROP_LOG, DROP_LOG_TMP_FILE)

    if should_print_performance_ML:
        print_performance_ML(senders, seconds_to_run, episode_num)
    Popen("pkill -f mm-link", shell = True).wait()
    Popen("pkill -f run_receiver", shell = True).wait()

