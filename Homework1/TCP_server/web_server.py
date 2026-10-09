"""Web server: the GUI. The page in web/ controls the acquisition.

usage: python web_server.py [--test] [--port 8080]

Then open the address it prints (http://<this computer's IP>:8080) in a
browser, on this computer or on any device in the same network.

Two jobs run at the same time, in different threads:

  WEB          (this file) serves the page, receives Start / Stop, and
               streams live data to every open page through /events
               (Server-Sent Events). ThreadingHTTPServer gives each browser
               request its own thread.
  ACQUISITION  (acquisition.py) talks to the ESP32: keeps its control
               connection open and, when Start arrives, runs one session.

They share two objects:
  Hub          the current status, and the list of open pages to notify
  Acquisition  its start / stop requests are called from the web threads

Use --test whenever the client is esp_test.py (the fake ESP32): those
sessions are saved in sensores_test/, apart from the real ones.
"""
import argparse
import json
import queue
import socket
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from protocol import (Config, odr_code_for, ODR_HZ, TRANSPORT_TCP, TRANSPORT_UDP,
                      MODE_SEQUENTIAL, MODE_PARALLEL, STOP_BY_COUNT, STOP_BY_TIME, U32_MASK)
from acquisition import Acquisition
from storage import REAL_DIR, TEST_DIR
from network import open_listener, open_udp, CONTROL_PORT, DATA_PORT, CLIENT_TIMEOUT

WEB_DIR = Path(__file__).resolve().parent / "web"
WEB_PORT = 8080
KEEPALIVE = 15.0          # seconds of quiet before /events sends a "still here" line


def sse(event, data):
    """One Server-Sent Event, as the bytes the browser expects:
        event: samples
        data: {"t": [...], ...}
        (empty line = end of the message)"""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n".encode()


# ---------------------------------------------------------------------------
# Hub: the shared status, and the pages listening to it
# ---------------------------------------------------------------------------
class Hub:
    """Shared between the threads. Every change goes through `self.lock`,
    so two threads never modify it at the same moment."""

    def __init__(self):
        self.lock = threading.Lock()
        self.listeners = []       # one queue per open page (/events connection)
        self.status = {
            'state': 'waiting',   # waiting | ready | running | finished | error
            'esp': None,          # the ESP32's IP while it is connected
            'error': None,        # text for the error box, or None
            'config': None,       # the running / last session's settings
            'file': None,         # the running / last session's CSV
            'progress': None,     # {'done', 'total', 'unit'}
        }

    def publish(self, event, data):
        """Send one event to every open page."""
        message = sse(event, data)
        with self.lock:
            for q in self.listeners:
                try:
                    q.put_nowait(message)
                except queue.Full:
                    pass          # a page that stopped reading loses messages; the rest don't wait

    def update_status(self, **changes):
        """Change some status fields and tell every page."""
        with self.lock:
            self.status.update(changes)
            snapshot = dict(self.status)
        self.publish('status', snapshot)

    def set_progress(self, progress):
        """Remember the progress for pages opened mid-session (no event:
        the 'samples' events already carry it)."""
        with self.lock:
            self.status['progress'] = progress

    def add_listener(self):
        q = queue.Queue(maxsize=500)
        with self.lock:
            self.listeners.append(q)
            q.put_nowait(sse('status', dict(self.status)))   # a new page starts with the current state
        return q

    def remove_listener(self, q):
        with self.lock:
            self.listeners.remove(q)


# ---------------------------------------------------------------------------
# Web: the page, /events, /start and /stop
# ---------------------------------------------------------------------------
def form_value(form, name, kind, problem):
    """One field of the form converted with `kind` (int or float). If it is
    missing or doesn't convert, raise ValueError with `problem`, a message
    written for the page (not Python's own, like "invalid literal for int()")."""
    try:
        return kind(form[name])
    except (KeyError, TypeError, ValueError):
        raise ValueError(problem)


def config_from_form(form):
    """Build a Config from the page's form. Raises ValueError with a message
    for the page. The range, and a limit of 0, are left for the ESP32 to
    check, as it does with any CONFIG."""
    rate = form_value(form, 'rate', float, "Choose a sample rate")
    range_g = form_value(form, 'range', int, "Choose a range")
    try:
        odr_code = odr_code_for(rate)
    except ValueError:
        valid = ", ".join(f"{hz:g}" for hz in sorted(ODR_HZ.values()))
        raise ValueError(f"{rate:g} Hz is not a BMI270 rate (valid: {valid} Hz)")

    if form.get('stop') == 'time':
        seconds = form_value(form, 'duration', float,
                             "Duration (T) must be a number of seconds")
        if seconds < 0:
            raise ValueError("Duration (T) can't be negative")
        stop_mode, limit = STOP_BY_TIME, round(seconds * 1000)
    else:
        samples = form_value(form, 'samples', int,
                             "Samples (N) must be a whole number")
        if samples < 0:
            raise ValueError("Samples (N) can't be negative")
        stop_mode, limit = STOP_BY_COUNT, samples
    if limit > U32_MASK:
        raise ValueError("That session is far too long")

    return Config(
        range_g=range_g,
        odr_code=odr_code,
        transport=TRANSPORT_UDP if form.get('transport') == 'udp' else TRANSPORT_TCP,
        read_mode=MODE_PARALLEL if form.get('mode') == 'parallel' else MODE_SEQUENTIAL,
        stop_mode=stop_mode,
        limit=limit,
    )


class Handler(SimpleHTTPRequestHandler):
    """One object per browser request. GET serves the files in web/ (that is
    what SimpleHTTPRequestHandler does, and it never serves anything outside
    that folder) plus /events; POST handles /start and /stop."""

    hub = None              # set in main()
    acquisition = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB_DIR), **kwargs)

    def log_message(self, format, *args):
        pass                # don't print a line for every request

    def do_GET(self):
        if self.path == '/events':
            self.stream_events()
        else:
            super().do_GET()                    # a file: index.html, style.css, app.js

    def do_POST(self):
        if self.path == '/start':
            try:
                length = int(self.headers.get('Content-Length', 0))
                form = json.loads(self.rfile.read(length) or b"{}")
                if not isinstance(form, dict):
                    raise ValueError
            except ValueError:
                return self.reply(400, {'error': "The request from the page could not be read"})
            try:
                config = config_from_form(form)
            except ValueError as e:
                return self.reply(400, {'error': str(e)})
            problem = self.acquisition.request_start(config)
        elif self.path == '/stop':
            problem = self.acquisition.request_stop()
        else:
            return self.reply(404, {'error': 'unknown address'})

        if problem:
            self.reply(409, {'error': problem})  # 409 Conflict: not possible right now
        else:
            self.reply(200, {'ok': True})

    def reply(self, code, data):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def stream_events(self):
        """The answer to /events never ends: each event is written as soon as
        it is published, until the page is closed."""
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()

        q = self.hub.add_listener()
        try:
            while True:
                try:
                    message = q.get(timeout=KEEPALIVE)
                except queue.Empty:
                    message = b": keepalive\n\n"  # a comment line: the browser ignores it
                self.wfile.write(message)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass                                 # the page was closed
        finally:
            self.hub.remove_listener(q)


def local_ip():
    """This computer's IP in the local network (to print the address).
    Connecting a UDP socket sends nothing: it only picks the route."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except OSError:
            return "127.0.0.1"


def main():
    p = argparse.ArgumentParser(description="Acquisition web server")
    p.add_argument('--port', type=int, default=WEB_PORT, help="web page port (default 8080)")
    p.add_argument('--test', action='store_true',
                   help="the client is esp_test.py: save in sensores_test/")
    args = p.parse_args()
    data_dir = TEST_DIR if args.test else REAL_DIR

    # The sockets are opened here, before any thread starts, so that a
    # problem (e.g. "Address already in use") stops the program right away.
    with open_listener(CONTROL_PORT) as control_listener, \
         open_listener(DATA_PORT) as data_listener, \
         open_udp(DATA_PORT) as udp_sock, \
         ThreadingHTTPServer(('0.0.0.0', args.port), Handler) as web:
        data_listener.settimeout(CLIENT_TIMEOUT)
        udp_sock.settimeout(CLIENT_TIMEOUT)

        hub = Hub()
        acquisition = Acquisition(hub, data_dir, control_listener, data_listener, udp_sock)
        Handler.hub = hub
        Handler.acquisition = acquisition
        acquisition.start()

        print(f"ESP32: control on :{CONTROL_PORT}, data on :{DATA_PORT} (TCP and UDP)")
        print(f"Saving sessions in {data_dir.name}/"
              + (" (TEST data)" if data_dir == TEST_DIR else ""))
        print(f"Open http://{local_ip()}:{args.port} in a browser (Ctrl+C to quit)")
        try:
            web.serve_forever()
        except KeyboardInterrupt:
            print("\nBye")


if __name__ == "__main__":
    main()
