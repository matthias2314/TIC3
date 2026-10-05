"""Main program: runs one acquisition session after another.

usage: python server.py [tcp|udp] [--range G] [--rate HZ] [--mode sequential|parallel] [--samples N]
"""
import argparse
import socket

from protocol import (Config, odr_code_for, STATUS_TEXT, ACK_OK,
                      TRANSPORT_TCP, TRANSPORT_UDP, MODE_SEQUENTIAL, MODE_PARALLEL)
from control_channel import send_config, receive_ack
from data_channel import (receive_samples_tcp, receive_samples_udp,
                          drain_udp, print_sample, print_summary, ClientClosed)
from storage import CsvWriter

HOST = '0.0.0.0'          # all interfaces
CONTROL_PORT = 10001
DATA_PORT = 10000         # used by both TCP and UDP (they are separate ports)
CLIENT_TIMEOUT = 20.0     # seconds of silence before we give up on a client


def read_config():
    """Build the session's Config from the command line (later: from the GUI)."""
    p = argparse.ArgumentParser(description="RPi acquisition server")
    p.add_argument('transport', nargs='?', choices=['tcp', 'udp'], default='tcp')
    p.add_argument('--range', type=int, default=2, help="full scale in g: 2, 4, 8, 16")
    p.add_argument('--rate', type=float, default=100, help="sample rate in Hz, e.g. 12.5")
    p.add_argument('--mode', choices=['sequential', 'parallel'], default='sequential')
    p.add_argument('--samples', type=int, default=20, help="samples per session")
    args = p.parse_args()

    try:
        odr_code = odr_code_for(args.rate)
    except ValueError as e:
        p.error(str(e))               # prints the message and exits

    return Config(
        range_g=args.range,
        odr_code=odr_code,
        transport=TRANSPORT_UDP if args.transport == 'udp' else TRANSPORT_TCP,
        read_mode=MODE_PARALLEL if args.mode == 'parallel' else MODE_SEQUENTIAL,
        num_samples=args.samples,
    )


def open_listener(port):
    """Create a TCP socket listening on `port`."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, port))
    s.listen()
    return s


def open_udp(port):
    """Create a UDP socket bound to `port`."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((HOST, port))
    return s


def session_outputs(config):
    """Decide where one session's results go. Call it once per session.

    Returns two lists of functions:
      consumers  receive each Sample
      finishers  receive the final stats when the session ends
    """
    writer = CsvWriter(config)                       # opens a new file
    consumers = [print_sample, writer.write]
    finishers = [print_summary, writer.close]
    return consumers, finishers


def main():
    config = read_config()
    use_udp = config.transport == TRANSPORT_UDP

    with open_listener(CONTROL_PORT) as control_listener, \
         open_listener(DATA_PORT) as data_listener, \
         open_udp(DATA_PORT) as udp_sock:
        # The control listener waits forever for the ESP32 to appear,
        # but once configured, the data must arrive in time.
        data_listener.settimeout(CLIENT_TIMEOUT)
        udp_sock.settimeout(CLIENT_TIMEOUT)

        print(f"Listening: control on :{CONTROL_PORT}, "
              f"data ({'UDP' if use_udp else 'TCP'}) on :{DATA_PORT}")
        print(f"Session config: {config}")

        while True:
            control, address = control_listener.accept()
            control.settimeout(CLIENT_TIMEOUT)
            print(f"ESP32 connected from {address}")

            try:
                with control:
                    # 0. UDP: throw away datagrams left from a previous session
                    if use_udp:
                        stale = drain_udp(udp_sock)
                        if stale:
                            print(f"Discarded {stale} stale datagram(s)")

                    # 1. CONTROL: configure the ESP32
                    send_config(control, config)
                    status = receive_ack(control)
                    if status != ACK_OK:
                        reason = STATUS_TEXT.get(status, "unknown error")
                        print(f"ESP32 rejected the config (status={status}: {reason})")
                        continue
                    print("Config accepted")

                    # 2. DATA
                    if use_udp:
                        print("Receiving samples over UDP...")
                        consumers, finishers = session_outputs(config)
                        receive_samples_udp(udp_sock, control, address[0], config,
                                            consumers, finishers)
                        print(f"Session with {address} finished (END received)")
                    else:
                        print("Waiting for the TCP data connection...")
                        data, data_address = data_listener.accept()
                        if data_address[0] != address[0]:
                            print(f"Unexpected data connection from {data_address}, ignoring")
                            data.close()
                            continue

                        data.settimeout(CLIENT_TIMEOUT)
                        print(f"Data connection from {data_address}")
                        with data:
                            consumers, finishers = session_outputs(config)
                            receive_samples_tcp(data, config, consumers, finishers)

            except ClientClosed:
                print(f"Client {address} disconnected cleanly")
            except TimeoutError:
                print(f"Client {address} silent for {CLIENT_TIMEOUT}s, ending session")
            except ConnectionError as e:
                print(f"Client {address} disconnected abruptly: {e}")
            except OSError as e:
                print(f"Socket error with {address}: {e}")


if __name__ == "__main__":
    main()
