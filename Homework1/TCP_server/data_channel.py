"""Data channel: receive and decode the samples sent by the ESP32 (TCP or UDP)."""
import select
import struct
import time
from collections import namedtuple

from protocol import (MSG_FMT, MSG_SIZE, U32_MASK, END_FMT, END_SIZE, END_CODE,
                      END_RESULT, STOP_BY_COUNT, scale_for)

UDP_BUFFER = 2048          # larger than any valid datagram, so bad sizes can be detected
END_GRACE = 0.2            # seconds to wait for datagrams still in flight after END

Sample = namedtuple('Sample', 'seq t_s rx_s dt_ms ax ay az ax_raw ay_raw az_raw late')


class ClientClosed(ConnectionError):
    """The client closed the connection cleanly (FIN)."""


def recv_exact(sock, n):
    """Receive exactly n bytes from a TCP socket, or raise ClientClosed."""
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ClientClosed("client closed the connection")
        buf += chunk
    return buf


class SampleTracker:
    def __init__(self, config):
        self.scale = scale_for(config.range_g)   # from THIS session's config
        # How many samples the session should have. In count mode we know it
        # from the start; in time mode we don't. Either way, the final number
        # comes from END (see stats).
        if config.stop_mode == STOP_BY_COUNT:
            self.expected = config.limit
        else:
            self.expected = None
        self.end = None              # (result, total) from END; None = no END yet
        self.next_seq = 0            # every session starts at seq 0
        self.pending = set()         # skipped so far: lost, or still on their way
        self.last_t = None           # t_us of the previous sample
        self.elapsed_us = 0          # ESP32 time since the first sample (never wraps)
        self.first_rx = None         # RPi clock when the first sample arrived
        self.received = 0            # arrived in order (the ones returned as Samples)
        self.late = 0
        self.duplicates = 0

    def process(self, seq, t_us, ax, ay, az):
        """Check one message. Return a Sample (with late=1 if it arrived out of
        order), or None if it produces no data (invalid or duplicate)."""
        now = time.monotonic()                   # arrival time, RPi clock

        # --- Sequence check ---
        if self.expected is not None and seq >= self.expected:
            print(f"WARNING: seq={seq} is outside this session "
                  f"(0..{self.expected - 1}), ignored")
            return None
        if seq < self.next_seq:                  # behind: late or duplicate
            if seq in self.pending:
                self.pending.remove(seq)
                self.late += 1
                print(f"WARNING: seq={seq} arrived late, not shown (counted as late, not lost)")
                # It was taken BEFORE the newest sample: place it that far back in time.
                # The tracker's timing state is not touched.
                behind_us = (self.last_t - t_us) & U32_MASK
                return self.build_sample(seq, self.elapsed_us - behind_us, now, None,
                                         ax, ay, az, late=1)
            self.duplicates += 1
            print(f"WARNING: duplicate seq={seq}, ignored")
            return None
        if seq > self.next_seq:                  # ahead: something was skipped
            self.pending.update(range(self.next_seq, seq))
            print(f"WARNING: gap of {seq - self.next_seq} before seq={seq} (lost, or late)")
        self.next_seq = seq + 1
        self.received += 1

        # --- Timing, ESP32 clock ---
        if self.last_t is None:
            dt_ms = None
        else:
            dt_us = (t_us - self.last_t) & U32_MASK
            self.elapsed_us += dt_us             # adding the differences never wraps
            dt_ms = dt_us / 1000
        self.last_t = t_us

        # --- Timing, RPi clock ---
        if self.first_rx is None:
            self.first_rx = now

        return self.build_sample(seq, self.elapsed_us, now, dt_ms, ax, ay, az, late=0)

    def build_sample(self, seq, elapsed_us, now, dt_ms, ax, ay, az, late):
        """Put one sample together, converting the raw values to m/s²."""
        s = self.scale
        return Sample(
            seq=seq,
            t_s=elapsed_us / 1_000_000,
            rx_s=now - self.first_rx,
            dt_ms=dt_ms,
            ax=ax * s, ay=ay * s, az=az * s,
            ax_raw=ax, ay_raw=ay, az_raw=az,
            late=late,
        )

    def set_end(self, result, total):
        """The ESP32's END: how the session ended and how many samples it took."""
        self.end = (result, total)

    def stats(self):
        # Expected = the samples the ESP32 really took: END's total. That is
        # N when it completed, fewer when it was stopped or failed (samples
        # never taken are not "lost": they never existed). Without END the
        # session was interrupted: count up to the last seq that arrived.
        if self.end is not None:
            result, self.expected = END_RESULT.get(self.end[0], 'failed'), self.end[1]
        else:
            result, self.expected = 'interrupted', self.next_seq
        lost = self.expected - self.received - self.late
        return {
            'expected': self.expected,
            'received': self.received,
            'late': self.late,
            'duplicates': self.duplicates,
            'missing': len(self.pending),
            'lost': lost,
            'loss_pct': 100 * lost / self.expected if self.expected else 0.0,
            'result': result,        # completed | stopped | failed | interrupted
        }


# ---------------------------------------------------------------------------
# Consumers: functions that receive each Sample and do something with it.
# Finishers: functions that receive the final stats when a session ends.
# ---------------------------------------------------------------------------
def print_summary(stats):
    """Terminal finisher: print the end-of-session summary from tracker.stats()."""
    print("--- Session summary ---")
    print(f"  expected:   {stats['expected']}")
    print(f"  received:   {stats['received']} (in order)")
    print(f"  late:       {stats['late']}")
    print(f"  duplicates: {stats['duplicates']}")
    print(f"  lost:       {stats['lost']} ({stats['loss_pct']:.1f} %)")
    print(f"  result:     {stats['result']}")


def handle_message(msg, tracker, consumers):
    """Unpack one 14-byte message, check it, and give the result to every consumer."""
    sample = tracker.process(*struct.unpack(MSG_FMT, msg))
    if sample is not None:
        for consumer in consumers:
            consumer(sample)


def finish_session(tracker, finishers):
    """The session is over: give its final counters to every finisher."""
    stats = tracker.stats()
    for finish in finishers:
        finish(stats)


# ---------------------------------------------------------------------------
# Receiving
# ---------------------------------------------------------------------------
def read_end(control):
    """Read END from the control channel. Returns (result, total)."""
    try:
        code, result, total = struct.unpack(END_FMT, recv_exact(control, END_SIZE))
    except ClientClosed:
        raise ConnectionError("control channel closed before END")
    if code != END_CODE:
        raise ConnectionError(f"unexpected control message 0x{code:02X}")
    return result, total


def receive_samples_tcp(sock, control, config, consumers, finishers):
    """Samples arrive on the TCP data connection until the ESP32 closes it;
    then END arrives on the control channel."""
    tracker = SampleTracker(config)
    try:
        try:
            while True:
                msg = recv_exact(sock, MSG_SIZE)
                handle_message(msg, tracker, consumers)
        except ClientClosed:
            pass                      # the data connection closed: no more samples
        tracker.set_end(*read_end(control))
    finally:
        finish_session(tracker, finishers)


def read_datagram(sock, esp_ip, tracker, consumers):
    """Read one datagram from esp_ip and handle every sample in it. A datagram
    carries one or more samples back to back (14 bytes each): sending them
    one per datagram is too slow for the ESP32 at high rates."""
    msg, (src_ip, _) = sock.recvfrom(UDP_BUFFER)
    if src_ip != esp_ip:
        print(f"Ignoring datagram from {src_ip}")
    elif len(msg) == 0 or len(msg) % MSG_SIZE != 0:
        print(f"Ignoring datagram of {len(msg)} bytes (not a whole number of "
              f"{MSG_SIZE}-byte samples)")
    else:
        for start in range(0, len(msg), MSG_SIZE):
            handle_message(msg[start:start + MSG_SIZE], tracker, consumers)


def receive_samples_udp(udp_sock, control, esp_ip, config, consumers, finishers):
    tracker = SampleTracker(config)
    timeout = udp_sock.gettimeout()
    try:
        while True:
            # Wait until at least one of the two sockets has something to read
            readable, _, _ = select.select([udp_sock, control], [], [], timeout)
            if not readable:
                raise TimeoutError("no samples and no END")

            # Samples first: END is only looked at when no datagram is waiting
            if udp_sock in readable:
                read_datagram(udp_sock, esp_ip, tracker, consumers)
                continue

            # Only the control channel has something: it should be END
            result, total = read_end(control)
            tracker.set_end(result, total)

            # END travels by TCP and can overtake the last datagrams: wait a
            # moment for any that are still on their way.
            while select.select([udp_sock], [], [], END_GRACE)[0]:
                read_datagram(udp_sock, esp_ip, tracker, consumers)
            return
    finally:
        finish_session(tracker, finishers)


def drain_udp(sock):
    """Discard datagrams left over from a previous session. Returns how many."""
    timeout = sock.gettimeout()
    sock.setblocking(False)          # recvfrom raises BlockingIOError when empty
    discarded = 0
    try:
        while True:
            sock.recvfrom(UDP_BUFFER)
            discarded += 1
    except BlockingIOError:
        pass
    finally:
        sock.settimeout(timeout)     # back to the normal timeout
    return discarded
