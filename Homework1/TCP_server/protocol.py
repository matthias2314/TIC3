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


CONFIG_FMT = '<BBBBI'
CONFIG_SIZE = struct.calcsize(CONFIG_FMT)  # 8 bytes
Config = namedtuple('Config', 'range_g odr_code transport read_mode num_samples')

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


def describe_config(config):
    """The config as a dictionary with readable values (for files and for the web page)."""
    return {
        'range_g': config.range_g,
        'rate_hz': ODR_HZ.get(config.odr_code),
        'transport': 'udp' if config.transport == TRANSPORT_UDP else 'tcp',
        'mode': 'parallel' if config.read_mode == MODE_PARALLEL else 'sequential',
        'num_samples': config.num_samples,
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
STATUS_TEXT = {
    ACK_OK: "OK",
    ERR_RANGE: "invalid range",
    ERR_RATE: "invalid rate",
    ERR_TRANSPORT: "invalid transport",
    ERR_MODE: "invalid read mode",
    ERR_SAMPLES: "invalid number of samples",
}

END_FMT = '<B'
END_SIZE = struct.calcsize(END_FMT)        # 1 byte
END_CODE = 0xFF
