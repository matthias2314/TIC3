"""Acquisition: the thread that talks to the ESP32 for the web page.

It keeps the ESP32's control connection open and, each time the page asks
for it (request_start), runs one session:

    CONFIG -> ACK -> samples (TCP or UDP) -> END

It knows nothing about HTTP or the page. It reports everything through
`hub`, any object with these three methods (web_server.py's Hub):

    hub.update_status(**fields)   the general state changed
    hub.publish(event, data)      something happened: 'session', 'samples', 'summary'
    hub.set_progress(progress)    remember the progress (no event)

So the layers are:
    protocol.py, network.py, control_channel.py, data_channel.py   the network
    storage.py                                                      the files
    acquisition.py                                                  the session logic
    web_server.py + web/                                            the GUI
"""
import math
import queue
import select
import struct
import threading
import time

from protocol import (describe_config, ODR_HZ, STATUS_TEXT, ACK_OK, TRANSPORT_UDP,
                      STOP_BY_COUNT, STOP_BY_TIME, STOP_FMT, STOP_CODE)
from control_channel import send_config, receive_ack
from data_channel import (receive_samples_tcp, receive_samples_udp, drain_udp,
                          print_summary, ClientClosed)
from network import CLIENT_TIMEOUT
from storage import CsvWriter

ACK_TIMEOUT = 5.0         # seconds to wait for the ACK after sending CONFIG
BATCH_PERIOD = 0.1        # seconds between live updates sent to the page


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
    """The thread that talks to the ESP32. request_start() and request_stop()
    are called from other threads (the web page's requests)."""

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
        """One session: CONFIG, ACK, samples, END."""
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
                                        consumers, finishers)
                else:
                    data, data_address = self.data_listener.accept()
                    with data:
                        if data_address[0] != esp_ip:
                            raise ConnectionError(f"unexpected data connection from {data_address[0]}")
                        data.settimeout(CLIENT_TIMEOUT)
                        receive_samples_tcp(data, control, config, consumers, finishers)
            finally:
                with self.lock:
                    self.receiving = False
                live.flush()                       # the last few samples

            self.publish_summary(summary, config, live, file, problem=None)
            if summary['result'] == 'failed':
                self.hub.update_status(state='error', error="The ESP32 ended the session "
                                       "early: its sensor or its sending failed")
            else:
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
        """Send the final counters, with a one-line note on how it ended
        (stats['result'] comes from the ESP32's END, see data_channel.py)."""
        progress = live.progress()
        reached = f"{progress['done']} / {progress['total']:g} {progress['unit']}"
        result = stats['result']
        if result == 'interrupted':
            note = f"Interrupted: {problem or 'no END from the ESP32'}"
        elif result == 'stopped':
            note = f"Stopped by user at {reached}"
        elif result == 'failed':
            note = f"Ended early by the ESP32 at {reached}"
        elif config.stop_mode == STOP_BY_TIME:
            note = f"Completed: {stats['expected']} samples in {config.limit / 1000:g} s"
        else:
            note = "Completed"
        self.hub.publish('summary', {**stats, 'file': file, 'note': note})
