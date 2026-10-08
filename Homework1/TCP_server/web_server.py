"""Web server: the page in web/ controls the acquisition.

usage: python web_server.py [--test] [--port 8080]

Then open the address it prints (http://<this computer's IP>:8080) in a
browser, on this computer or on any device in the same network.

Two jobs run at the same time, in different threads:

  WEB          serves the page, receives Start / Stop, and streams live data
               to every open page through /events (Server-Sent Events).
               ThreadingHTTPServer gives each browser request its own thread.
  ACQUISITION  talks to the ESP32: keeps its control connection open and,
               when Start arrives, runs one session the same way server.py
               does (CONFIG -> ACK -> samples -> END / FIN).

They share two objects:
  Hub          the current status, and the list of open pages to notify
  Acquisition  its start / stop requests are called from the web threads

Use --test whenever the client is esp_test.py, as with server.py.
"""
import argparse
import json
import math
import queue
import select
import socket
import struct
import threading
import time
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

from protocol import (Config, odr_code_for, describe_config, ODR_HZ, STATUS_TEXT, ACK_OK,
                      TRANSPORT_TCP, TRANSPORT_UDP, MODE_SEQUENTIAL, MODE_PARALLEL,
                      STOP_BY_COUNT, STOP_BY_TIME, STOP_FMT, STOP_CODE, U32_MASK)
from control_channel import send_config, receive_ack
from data_channel import (receive_samples_tcp, receive_samples_udp, drain_udp,
                          print_summary, ClientClosed)
from storage import CsvWriter, REAL_DIR, TEST_DIR
from network import open_listener, open_udp, CONTROL_PORT, DATA_PORT, CLIENT_TIMEOUT

WEB_DIR = Path(__file__).resolve().parent / "web"
WEB_PORT = 8080
ACK_TIMEOUT = 5.0         # seconds to wait for the ACK after sending CONFIG
BATCH_PERIOD = 0.1        # seconds between live updates sent to the page
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
# LiveFeed: a consumer that sends the samples to the page in batches
# ---------------------------------------------------------------------------
class LiveFeed:
    """Consumer for one session. Instead of one message per sample (up to
    1600 per second), it collects them and sends a batch every BATCH_PERIOD.
    It also keeps the mean and the jitter (standard deviation) of dt."""

    def __init__(self, hub, config):
        self.hub = hub
        self.config = config
        self.t, self.ax, self.ay, self.az = [], [], [], []
        self.last = None              # the newest sample
        self.last_sent = time.monotonic()
        # Running mean and variance of dt, without storing every dt
        # (Welford's method): n values, their mean, and m2 = sum of squared deviations
        self.n_dt = 0
        self.mean_dt = 0.0
        self.m2_dt = 0.0

    def add(self, sample):
        if sample.late:
            return                    # it belongs back in time: the chart only moves forward
        self.last = sample
        self.t.append(round(sample.t_s, 6))
        self.ax.append(round(sample.ax, 4))
        self.ay.append(round(sample.ay, 4))
        self.az.append(round(sample.az, 4))

        if sample.dt_ms is not None:
            self.n_dt += 1
            delta = sample.dt_ms - self.mean_dt
            self.mean_dt += delta / self.n_dt
            self.m2_dt += delta * (sample.dt_ms - self.mean_dt)

        if time.monotonic() - self.last_sent >= BATCH_PERIOD:
            self.flush()

    def progress(self):
        if self.last is None:
            done = 0
        elif self.config.stop_mode == STOP_BY_COUNT:
            done = self.last.seq + 1
        else:
            done = round(self.last.t_s, 2)
        if self.config.stop_mode == STOP_BY_COUNT:
            return {'done': done, 'total': self.config.limit, 'unit': 'samples'}
        return {'done': done, 'total': self.config.limit / 1000, 'unit': 's'}

    def timing(self):
        jitter = math.sqrt(self.m2_dt / (self.n_dt - 1)) if self.n_dt > 1 else None
        return {'mean_ms': self.mean_dt if self.n_dt else None, 'jitter_ms': jitter}

    def flush(self):
        """Send what has been collected since the last batch."""
        self.last_sent = time.monotonic()
        if self.last is None:
            return
        progress = self.progress()
        self.hub.publish('samples', {
            't': self.t, 'ax': self.ax, 'ay': self.ay, 'az': self.az,
            'latest': {'ax': self.last.ax, 'ay': self.last.ay, 'az': self.last.az,
                       'dt_ms': self.last.dt_ms},
            'timing': self.timing(),
            'progress': progress,
        })
        self.hub.set_progress(progress)
        self.t, self.ax, self.ay, self.az = [], [], [], []


# ---------------------------------------------------------------------------
# Acquisition: the thread that talks to the ESP32
# ---------------------------------------------------------------------------
class Acquisition(threading.Thread):

    def __init__(self, hub, data_dir, control_listener, data_listener, udp_sock):
        super().__init__(daemon=True)     # daemon: it ends when the program ends
        self.hub = hub
        self.data_dir = data_dir
        self.control_listener = control_listener
        self.data_listener = data_listener
        self.udp_sock = udp_sock
        self.commands = queue.Queue()     # web -> acquisition: the Config to run

        # Shared with the web threads, protected by self.lock
        self.lock = threading.Lock()
        self.control = None               # the ESP32's control socket, while connected
        self.busy = False                 # a Start was accepted and is not finished yet
        self.receiving = False            # samples are flowing: Stop makes sense
        self.stop_event = threading.Event()

    # --- Called from the WEB threads ---------------------------------------
    def request_start(self, config):
        """Queue a session. Returns None, or the reason it can't start."""
        with self.lock:
            if self.control is None:
                return "The ESP32 is not connected"
            if self.busy:
                return "A session is already running"
            self.busy = True
        self.commands.put(config)
        return None

    def request_stop(self):
        """Send STOP to the ESP32. Returns None, or the reason it can't."""
        with self.lock:
            if not self.receiving or self.control is None:
                return "No session is running"
            if self.stop_event.is_set():
                return "Stop was already sent"
            self.stop_event.set()
            # Sending from this thread while the acquisition thread reads the
            # same socket is fine: sending and receiving are independent.
            self.control.sendall(struct.pack(STOP_FMT, STOP_CODE))
        print("STOP sent to the ESP32")
        return None

    # --- The acquisition thread itself -------------------------------------
    def run(self):
        waiting = None                    # a connection accepted but not served yet
        while True:
            if waiting is None:
                waiting = self.control_listener.accept()
            control, address = waiting
            waiting = self.serve_esp(control, address[0])

    def serve_esp(self, control, esp_ip):
        """Keep one ESP32 connected and run the sessions the page asks for.
        Returns a NEW connection if the ESP32 reconnected, otherwise None."""
        print(f"ESP32 connected from {esp_ip}")
        while not self.commands.empty():  # Starts left over from before: ignore them
            self.commands.get_nowait()
        with self.lock:
            self.control = control
            self.busy = False
        self.hub.update_status(state='ready', esp=esp_ip, error=None)

        try:
            with control:
                while True:
                    # Wait for Start, but look at the sockets every 0.2 s
                    try:
                        config = self.commands.get(timeout=0.2)
                    except queue.Empty:
                        new = self.check_idle(control)
                        if new is not None:
                            print("The ESP32 connected again; dropping the old connection")
                            return new
                        continue
                    self.run_session(control, esp_ip, config)
        except (ConnectionError, TimeoutError, OSError) as e:
            print(f"Lost the ESP32 {esp_ip}: {e}")
            self.hub.update_status(state='waiting', esp=None,
                                   error=f"ESP32 disconnected ({e})")
        finally:
            with self.lock:
                self.control = None
                self.busy = False
        return None

    def check_idle(self, control):
        """While idle, the ESP32 sends nothing. So if its socket becomes
        readable, it closed the connection. Also, a new connection waiting on
        the listener means the ESP32 restarted (RESET) and came back."""
        readable, _, _ = select.select([control, self.control_listener], [], [], 0)
        if self.control_listener in readable:
            return self.control_listener.accept()
        if control in readable and control.recv(1) == b"":
            raise ClientClosed("the ESP32 closed the control connection")
        return None

    def run_session(self, control, esp_ip, config):
        """One session, like server.py: CONFIG, ACK, samples, end."""
        use_udp = config.transport == TRANSPORT_UDP
        settings = describe_config(config)
        self.stop_event.clear()
        summary = {}                      # filled by the finisher summary.update

        try:
            # 0. UDP: throw away datagrams left from a previous session
            if use_udp:
                drain_udp(self.udp_sock)

            # 1. CONTROL: configure the ESP32
            control.settimeout(ACK_TIMEOUT)
            send_config(control, config)
            status = receive_ack(control)          # TimeoutError if it doesn't answer
            control.settimeout(CLIENT_TIMEOUT)
            if status != ACK_OK:
                reason = STATUS_TEXT.get(status, f"unknown status {status}")
                print(f"ESP32 rejected the config ({reason})")
                self.hub.update_status(state='error', config=settings,
                                       error=f"ESP32 rejected the config: {reason}")
                return

            # 2. DATA: outputs for this session
            writer = CsvWriter(config, self.data_dir)
            live = LiveFeed(self.hub, config)
            file = f"{writer.csv_path.parent.name}/{writer.csv_path.name}"
            consumers = [writer.write, live.add]
            finishers = [writer.close, print_summary, summary.update]

            self.hub.publish('session', {
                'config': settings,
                'file': file,
                'expected_interval_ms': 1000 / ODR_HZ[config.odr_code],
            })
            self.hub.update_status(state='running', error=None, config=settings,
                                   file=file, progress=live.progress())
            with self.lock:
                self.receiving = True
            print(f"Session started: {settings}")

            try:
                if use_udp:
                    receive_samples_udp(self.udp_sock, control, esp_ip, config,
                                        consumers, finishers, self.stop_event)
                else:
                    data, data_address = self.data_listener.accept()
                    with data:
                        if data_address[0] != esp_ip:
                            raise ConnectionError(f"unexpected data connection from {data_address[0]}")
                        data.settimeout(CLIENT_TIMEOUT)
                        try:
                            receive_samples_tcp(data, config, consumers, finishers,
                                                self.stop_event)
                        except ClientClosed:
                            pass                   # the ESP32 closed the data connection: the normal end
            finally:
                with self.lock:
                    self.receiving = False
                live.flush()                       # the last few samples

            self.publish_summary(summary, config, live, file, problem=None)
            self.hub.update_status(state='finished', error=None)

        except (ConnectionError, TimeoutError, OSError) as e:
            # Tell the page what happened, then let serve_esp() drop the ESP32
            if summary:
                self.publish_summary(summary, config, live, file, problem=str(e))
            raise
        finally:
            with self.lock:
                self.busy = False

    def publish_summary(self, stats, config, live, file, problem):
        if problem:
            note = f"Interrupted: {problem}"
        elif stats['stopped']:
            progress = live.progress()
            note = f"Stopped by user at {progress['done']} / {progress['total']:g} {progress['unit']}"
        elif config.stop_mode == STOP_BY_TIME:
            note = f"Completed: {stats['expected']} samples in {config.limit / 1000:g} s"
        else:
            note = "Completed"
        self.hub.publish('summary', {**stats, 'file': file, 'note': note,
                                     'interrupted': problem is not None})


# ---------------------------------------------------------------------------
# Web: the page, /events, /start and /stop
# ---------------------------------------------------------------------------
def config_from_form(form):
    """Build a Config from the page's form. Raises ValueError with a readable
    message. Like server.py, the range and 0 are left for the ESP32 to check."""
    try:
        rate = float(form['rate'])
        range_g = int(form['range'])
        if form['stop'] == 'time':
            seconds = float(form['duration'])
            if seconds < 0:
                raise ValueError("The duration can't be negative")
            stop_mode, limit = STOP_BY_TIME, round(seconds * 1000)
        else:
            samples = int(form['samples'])
            if samples < 0:
                raise ValueError("The number of samples can't be negative")
            stop_mode, limit = STOP_BY_COUNT, samples
    except (KeyError, TypeError) as e:
        raise ValueError(f"Missing or invalid field: {e}")
    if limit > U32_MASK:
        raise ValueError("That session is far too long")

    return Config(
        range_g=range_g,
        odr_code=odr_code_for(rate),            # ValueError if it's not a BMI270 rate
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
                config = config_from_form(json.loads(self.rfile.read(length) or b"{}"))
            except ValueError as e:              # also catches bad JSON
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
