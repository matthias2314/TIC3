"""Network settings and sockets shared by the servers (web_server.py and server.py)."""
import socket

HOST = '0.0.0.0'          # all interfaces
CONTROL_PORT = 10001
DATA_PORT = 10000         # used by both TCP and UDP (they are separate ports)
CLIENT_TIMEOUT = 20.0     # seconds of silence before we give up on a client


def open_listener(port):
    """Create a TCP socket listening on `port`."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Allow restarting the server right away, without "Address already in use"
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind((HOST, port))
    s.listen()
    return s


def open_udp(port):
    """Create a UDP socket bound to `port`."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind((HOST, port))
    return s
