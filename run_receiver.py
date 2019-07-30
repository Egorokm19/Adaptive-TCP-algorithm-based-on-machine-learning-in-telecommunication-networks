import argparse
from src.receiver import Receiver
# argparse выполянет обработку опций и аргументов командной строки, с которой вызывается скрипт

def main() -> None:
    """Функция запуска сервера."""
    
    parser = argparse.ArgumentParser()
    parser.add_argument('ip_port_pairs', nargs='*')
    args = parser.parse_args()
    peers = args.ip_port_pairs

    receiver = Receiver([(peers[i], int(float(peers[i+1]))) for i in range(0, len(peers), 2)])

    try:
        receiver.perform_handshakes()
        receiver.run()
    except KeyboardInterrupt:
        pass
    finally:
        receiver.cleanup()


if __name__ == '__main__':
    main()
