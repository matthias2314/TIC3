"""Shared definitions for both channels (used by the RPi and by the ESP32 side)."""
import struct
from collections import namedtuple

MSG_FMT = '<IIhhh'
MSG_SIZE = struct.calcsize(MSG_FMT)        # 14 bytes

G = 9.80665                                # standard gravity, m/s²
U32_MASK = 0xFFFFFFFF                      # t_us is a uint32: it wraps around at 2**32


def scale_for(range_g):
    """m/s² per raw unit, for an accelerometer full scale of ±range_g."""
    return range_g * G / 32768


CONFIG_FMT = '<BBBBBI'
CONFIG_SIZE = struct.calcsize(CONFIG_FMT)  # 9 bytes
Config = namedtuple('Config', 'range_g odr_code transport read_mode stop_mode limit')
# stop_mode says what `limit` means, i.e. when the ESP32 ends the session:
#   STOP_BY_COUNT: after `limit` samples
#   STOP_BY_TIME:  after `limit` milliseconds, measured by the ESP32's own clock

VALID_RANGES_G = (2, 4, 8, 16)

ODR_HZ = {
    0x05: 12.5,    0x06: 25.0,   0x07: 50.0,  0x08: 100.0,
    0x09: 200.0,   0x0A: 400.0,  0x0B: 800.0, 0x0C: 1600.0,
}


def odr_code_for(rate_hz):
    """Return the BMI270 code for rate_hz, or raise ValueError if it isn't a valid rate."""
    for code, hz in ODR_HZ.items():
        if hz == rate_hz:
            return code
    raise ValueError(f"{rate_hz} Hz is not a BMI270 rate; valid: {sorted(ODR_HZ.values())}")


TRANSPORT_TCP = 0
TRANSPORT_UDP = 1

MODE_SEQUENTIAL = 0
MODE_PARALLEL = 1

STOP_BY_COUNT = 0
STOP_BY_TIME = 1
MAX_DURATION_MS = 3_600_000                # 1 hour: the longest session the ESP32 accepts


def describe_config(config):
    """The config as a dictionary with readable values (for files and for the web page)."""
    return {
        'range_g': config.range_g,
        'rate_hz': ODR_HZ.get(config.odr_code),
        'transport': 'udp' if config.transport == TRANSPORT_UDP else 'tcp',
        'mode': 'parallel' if config.read_mode == MODE_PARALLEL else 'sequential',
        'stop': 'time' if config.stop_mode == STOP_BY_TIME else 'samples',
        'num_samples': config.limit if config.stop_mode == STOP_BY_COUNT else None,
        'duration_s': config.limit / 1000 if config.stop_mode == STOP_BY_TIME else None,
    }


# ACK (ESP32 -> RPi): one status byte answering the CONFIG
ACK_FMT = '<B'
ACK_SIZE = struct.calcsize(ACK_FMT)        # 1 byte
ACK_OK = 0
ERR_RANGE = 1
ERR_RATE = 2
ERR_TRANSPORT = 3
ERR_MODE = 4
ERR_SAMPLES = 5
ERR_STOP = 6
ERR_DURATION = 7
STATUS_TEXT = {
    ACK_OK: "OK",
    ERR_RANGE: "invalid range",
    ERR_RATE: "invalid rate",
    ERR_TRANSPORT: "invalid transport",
    ERR_MODE: "invalid read mode",
    ERR_SAMPLES: "invalid number of samples",
    ERR_STOP: "invalid stop mode",
    ERR_DURATION: "invalid duration",
}

# END (ESP32 -> RPi, control channel, UDP sessions only): 0xFF and how many
# samples the ESP32 took (seq 0 .. total-1). In time mode it is the only way
# the server learns how many samples to expect, and so how many were lost.
END_FMT = '<BI'
END_SIZE = struct.calcsize(END_FMT)        # 5 bytes
END_CODE = 0xFF

# STOP (RPi -> ESP32, control channel, during a session): end the session now.
# The ESP32 then finishes exactly as if it had reached its limit (END for UDP,
# closing the data connection for TCP).
STOP_FMT = '<B'
STOP_CODE = 0xFE
