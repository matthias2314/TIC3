"""Jitter of a session, from the CSV files saved by storage.py.

Every row has two times for the same sample:
    t_s    when the ESP32 took it (ESP32 clock, estimated, see stamp_batch)
    rx_s   when it arrived at the RPi (RPi clock, measured)

The samples arrive in bursts (one burst per FIFO read), so the time between
two rows says nothing about the network. Instead, for the first sample of each
burst k we look at its delay

    d_k = rx_k - t_k

The two clocks are not synchronised, so d_k has an unknown constant offset,
and they drift a little (a few tens of ppm). Neither matters: jitter is how
much the delay VARIES. We report:

    std     standard deviation of d_k after removing a straight-line fit (drift)
    range   max - min of those residuals
    J       RFC 3550 (RTP) jitter: D = (rx_k - rx_k-1) - (t_k - t_k-1),
            J += (|D| - J) / 16

This is end-to-end jitter: it includes the wait on the ESP32 until the next
FIFO read, the sending, Wi-Fi, and when Python gets the CPU on the RPi.

usage: python jitter.py [file.csv ...]     (default: every CSV in sensores/)
"""
import csv
import statistics
import sys
from pathlib import Path

BURST_GAP_S = 0.0005     # arrivals closer than this belong to the same burst
MIN_SAMPLES = 500        # shorter sessions give meaningless numbers


def burst_starts(rx):
    """Indexes of the first sample of each burst."""
    return [0] + [i for i in range(1, len(rx)) if rx[i] - rx[i - 1] > BURST_GAP_S]


def jitter(rows):
    """Jitter numbers for one session (rows from the CSV). None if too short."""
    rows = [r for r in rows if r['late'] == '0']      # late samples have no own arrival order
    if len(rows) < MIN_SAMPLES:
        return None
    t = [float(r['t_s']) for r in rows]
    rx = [float(r['rx_s']) for r in rows]
    firsts = burst_starts(rx)
    x = [t[i] for i in firsts]
    d = [rx[i] - t[i] for i in firsts]

    # Remove the offset and the drift: least-squares line d = a + b*x
    mx, md = statistics.fmean(x), statistics.fmean(d)
    b = sum((xi - mx) * (di - md) for xi, di in zip(x, d)) / sum((xi - mx) ** 2 for xi in x)
    residuals = [di - (md + b * (xi - mx)) for xi, di in zip(x, d)]

    # RFC 3550 jitter, one step per burst
    j = 0.0
    for k in range(1, len(firsts)):
        i, h = firsts[k], firsts[k - 1]
        delta = (rx[i] - rx[h]) - (t[i] - t[h])
        j += (abs(delta) - j) / 16

    return {
        'samples': len(rows),
        'bursts': len(firsts),
        'per_burst': len(rows) / len(firsts),
        'std_ms': 1000 * statistics.pstdev(residuals),
        'range_ms': 1000 * (max(residuals) - min(residuals)),
        'rfc3550_ms': 1000 * j,
        'drift_ppm': 1e6 * b,
    }


def main():
    if len(sys.argv) > 1:
        files = [Path(f) for f in sys.argv[1:]]
    else:
        files = sorted((Path(__file__).resolve().parent / 'sensores').glob('*.csv'))

    print(f"{'session':36s} {'rate':>6s} {'mode':10s} {'tx':3s} {'samples':>7s} "
          f"{'bursts':>6s} {'/burst':>6s} {'std':>7s} {'range':>7s} {'J':>7s}")
    for path in files:
        with open(path, newline='') as f:
            rows = list(csv.DictReader(f))
        result = jitter(rows)
        if result is None:
            continue
        r0 = rows[0]
        print(f"{path.stem:36s} {float(r0['rate_hz']):6.0f} {r0['mode']:10s} {r0['transport']:3s} "
              f"{result['samples']:7d} {result['bursts']:6d} {result['per_burst']:6.1f} "
              f"{result['std_ms']:5.2f}ms {result['range_ms']:5.1f}ms {result['rfc3550_ms']:5.2f}ms")


if __name__ == '__main__':
    main()
