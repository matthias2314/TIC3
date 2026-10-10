"""Fake ESP32: validates the CONFIG, answers with an ACK, then streams samples
over the transport the server asked for (TCP or UDP). Like the real firmware,
it then stays connected and waits for the next CONFIG, and it ends a session
early when the server sends STOP. It exits when the server closes the control
connection.

usage: python esp_test.py [clean|reset|silent]
    clean   (default) every session ends normally, with END
    reset   simulates a crash: no END (and RST on a TCP data connection)
    silent  after the samples, sends nothing more (no END) and waits
"""
import select
import socket
import struct
import sys
import time

from protocol import (MSG_FMT, U32_MASK, CONFIG_FMT, CONFIG_SIZE, Config,
                      VALID_RANGES_G, ODR_HZ, TRANSPORT_TCP, TRANSPORT_UDP,
                      MODE_SEQUENTIAL, MODE_PARALLEL,
                      STOP_BY_COUNT, STOP_BY_TIME, MAX_DURATION_MS,
                      ACK_FMT, ACK_OK, ERR_RANGE, ERR_RATE, ERR_TRANSPORT,
                      ERR_MODE, ERR_SAMPLES, ERR_STOP, ERR_DURATION, STATUS_TEXT,
                      END_FMT, END_CODE, END_COMPLETED, END_STOPPED, STOP_CODE)
from data_channel import recv_exact, ClientClosed

HOST = '127.0.0.1'        # the RPi's IP address when testing over the network
CONTROL_PORT = 10001
DATA_PORT = 10000

# Simulated problems (None to disable)
SKIP_SEQ = 5              # never sent: "lost"                  (TCP and UDP)
DUPLICATE_SEQ = 8         # sent twice                          (UDP only)
LATE_SEQ = 10             # sent after LATE_SEQ + 1: "late"     (UDP only)

SAMPLES_PER_DATAGRAM = 8  # UDP: samples that travel together in one datagram


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
    if config.stop_mode == STOP_BY_COUNT:
        if config.limit == 0:
            return ERR_SAMPLES
    elif config.stop_mode == STOP_BY_TIME:
        if config.limit == 0 or config.limit > MAX_DURATION_MS:
            return ERR_DURATION
    else:
        return ERR_STOP
    return ACK_OK


def session_running(config, seq, start):
    """True while the session must go on: by count, or by time."""
    if config.stop_mode == STOP_BY_COUNT:
        return seq < config.limit
    return time.monotonic() - start < config.limit / 1000


def stop_requested(control):
    """Like the firmware: look at the control channel WITHOUT waiting.
    True if STOP arrived, or if the server closed the connection."""
    readable, _, _ = select.select([control], [], [], 0)    # timeout 0: just look
    if not readable:
        return False
    byte = control.recv(1)
    return byte == b"" or byte[0] == STOP_CODE


def recv_config(control):
    """Wait for the next CONFIG. A STOP that arrived too late (after the
    session had already ended) is skipped. Returns None when the server
    closes the connection."""
    try:
        first = recv_exact(control, 1)
        while first[0] == STOP_CODE:
            first = recv_exact(control, 1)
        rest = recv_exact(control, CONFIG_SIZE - 1)
    except ClientClosed:
        return None
    return Config(*struct.unpack(CONFIG_FMT, first + rest))


def run_session(control, config, mode):
    """Stream one session's samples, then end it like the firmware does."""
    use_udp = config.transport == TRANSPORT_UDP
    rate_hz = ODR_HZ[config.odr_code]
    if config.stop_mode == STOP_BY_COUNT:
        length = f"{config.limit} samples"
    else:
        length = f"{config.limit / 1000} s"
    print(f"Config OK: ±{config.range_g} g, {rate_hz} Hz, "
          f"{'UDP' if use_udp else 'TCP'}, {length}")

    # 2. DATA: open the socket the server asked for
    period = 1 / rate_hz
    sock_type = socket.SOCK_DGRAM if use_udp else socket.SOCK_STREAM
    with socket.socket(socket.AF_INET, sock_type) as data:
        if use_udp:
            waiting = []                                 # samples for the next datagram
            def flush():
                if waiting:
                    data.sendto(b"".join(waiting), (HOST, DATA_PORT))   # address on every datagram
                    waiting.clear()
            def send(packet):
                waiting.append(packet)
                if len(waiting) >= SAMPLES_PER_DATAGRAM:
                    flush()
        else:
            data.connect((HOST, DATA_PORT))
            def flush():
                pass                                     # TCP groups the bytes by itself
            def send(packet):
                data.sendall(packet)

        start = time.monotonic()
        held = None                                      # the "late" packet, waiting
        seq = 0                                          # seq always starts at 0
        stopped = False

        while session_running(config, seq, start):
            if stop_requested(control):
                stopped = True
                break

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

            seq += 1
            time.sleep(period)

        flush()                                          # the samples still waiting
        if stopped:
            print(f"STOP received after {seq} samples")

        # 3. END of the session (TCP and UDP), unless simulating a failure
        if mode == 'silent':
            print("Going silent, without END... (Ctrl+C to quit)")
            time.sleep(3600)
        elif mode == 'reset':
            if not use_udp:
                data.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack('ii', 1, 0))
            print("Simulating a crash: no END" + ("" if use_udp else ", data closed with RST"))
            sys.exit(1)
        else:
            result = END_STOPPED if stopped else END_COMPLETED
            control.sendall(struct.pack(END_FMT, END_CODE, result, seq))   # seq = samples taken
            print(f"END sent on the control channel ({seq} samples taken)"
                  + ("" if use_udp else ", then closing the data connection (FIN)"))


mode = sys.argv[1] if len(sys.argv) > 1 else 'clean'

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as control:
    control.connect((HOST, CONTROL_PORT))
    print("Connected to the server, waiting for CONFIG...")

    while True:
        # 1. CONTROL: receive the config, validate it, answer with a status
        config = recv_config(control)
        if config is None:
            print("The server closed the control connection, bye")
            break
        print(f"Config received: {config}")

        status = validate(config)
        control.sendall(struct.pack(ACK_FMT, status))
        if status != ACK_OK:
            print(f"Config rejected ({STATUS_TEXT[status]}), waiting for another")
            continue

        run_session(control, config, mode)
        print("Waiting for the next CONFIG...")
