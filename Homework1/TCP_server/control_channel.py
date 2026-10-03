import struct

from protocol import CONFIG_FMT, ACK_FMT, ACK_SIZE
from data_channel import recv_exact


def send_config(sock, fields):
    sock.sendall(struct.pack(CONFIG_FMT, *fields))


def receive_ack(sock):
    (status,) = struct.unpack(ACK_FMT, recv_exact(sock, ACK_SIZE))
    return status
