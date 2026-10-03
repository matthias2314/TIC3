"""Fake ESP32: validates the CONFIG, answers with an ACK, then streams samples
over the transport the server asked for (TCP or UDP).

usage: python esp_test.py [clean|reset|silent]
"""
import socket
import struct
import sys
import time

from protocol import (MSG_FMT, U32_MASK, CONFIG_FMT, CONFIG_SIZE, Config,
                      VALID_RANGES_G, ODR_HZ, TRANSPORT_TCP, TRANSPORT_UDP,
                      MODE_SEQUENTIAL, MODE_PARALLEL,
                      ACK_FMT, ACK_OK, ERR_RANGE, ERR_RATE, ERR_TRANSPORT,
                      ERR_MODE, ERR_SAMPLES, STATUS_TEXT,
                      END_FMT, END_CODE)
from data_channel import recv_exact

HOST = '127.0.0.1'        # the RPi's IP address when testing over the network
CONTROL_PORT = 10001
DATA_PORT = 10000

# Simulated problems (None to disable)
SKIP_SEQ = 5              # never sent: "lost"                  (TCP and UDP)
DUPLICATE_SEQ = 8         # sent twice                          (UDP only)
LATE_SEQ = 10             # sent after LATE_SEQ + 1: "late"     (UDP only)


def validate(config):
    """Check the config like the real firmware will. Returns a status code."""
    if config.range_g not in VALID_RANGES_G:
        return ERR_RANGE
    if config.odr_code not in ODR_HZ:
        return ERR_RATE
    if config.transport not in (TRANSPORT_TCP, TRANSPORT_UDP):
        return ERR_TRANSPORT
    if config.read_mode not in (MODE_SEQUENTIAL, MODE_PARALLEL):
        return ERR_MODE
    if config.num_samples == 0:
        return ERR_SAMPLES
    return ACK_OK


mode = sys.argv[1] if len(sys.argv) > 1 else 'clean'

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as control:
    # 1. CONTROL: receive the config, validate it, answer with a status
    control.connect((HOST, CONTROL_PORT))
    config = Config(*struct.unpack(CONFIG_FMT, recv_exact(control, CONFIG_SIZE)))
    print(f"Config received: {config}")

    status = validate(config)
    control.sendall(struct.pack(ACK_FMT, status))
    if status != ACK_OK:
        print(f"Config rejected ({STATUS_TEXT[status]}), not sending data")
        sys.exit(1)

    use_udp = config.transport == TRANSPORT_UDP
    rate_hz = ODR_HZ[config.odr_code]
    print(f"Config OK: ±{config.range_g} g, {rate_hz} Hz, "
          f"{'UDP' if use_udp else 'TCP'}, {config.num_samples} samples")

    # 2. DATA: open the socket the server asked for
    period = 1 / rate_hz
    sock_type = socket.SOCK_DGRAM if use_udp else socket.SOCK_STREAM
    with socket.socket(socket.AF_INET, sock_type) as data:
        if use_udp:
            def send(packet):
                data.sendto(packet, (HOST, DATA_PORT))   # address on every datagram
        else:
            data.connect((HOST, DATA_PORT))
            def send(packet):
                data.sendall(packet)

        start = time.monotonic()
        held = None                                      # the "late" packet, waiting

        for seq in range(config.num_samples):            # seq always starts at 0
            t_us = int((time.monotonic() - start) * 1_000_000) & U32_MASK
            packet = struct.pack(MSG_FMT, seq, t_us, 100, -200, 16384)

            if seq == SKIP_SEQ:
                pass                                     # lost
            elif use_udp and seq == LATE_SEQ:
                held = packet                            # send it later
            else:
                send(packet)
                if use_udp and seq == DUPLICATE_SEQ:
                    send(packet)                         # duplicate
                if held is not None:
                    send(held)                           # late, after a newer one
                    held = None

            time.sleep(period)

        # 3. END of the session
        if mode == 'silent':
            print("Going silent, without END... (Ctrl+C to quit)")
            time.sleep(3600)
        elif use_udp:
            control.sendall(struct.pack(END_FMT, END_CODE))
            print("END sent on the control channel")
        elif mode == 'reset':
            data.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
            print("Closing with RST")
        else:
            print("Closing cleanly (FIN)")
