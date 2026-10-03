import struct
from collections import namedtuple

#Data channel (TCP or UDP)
MSG_FMT = '<IIhhh'
MSG_SIZE = struct.calcsize(MSG_FMT)        # 14 bytes

G = 9.80665                                # standard gravity, m/s²
U32_MASK = 0xFFFFFFFF                      # t_us is a uint32: it wraps around at 2**32


def scale_for(range_g):
    """m/s² per raw unit, for an accelerometer full scale of ±range_g."""
    return range_g * G / 32768


# Control channel: RPi <-> ESP32 (always TCP)
CONFIG_FMT = '<BBBBI'
CONFIG_SIZE = struct.calcsize(CONFIG_FMT)  # 8 bytes
Config = namedtuple('Config', 'range_g odr_code transport read_mode num_samples')

VALID_RANGES_G = (2, 4, 8, 16)

# The rate travels as the sensor's register code, not as a number in Hz:
# it is exact (12.5 Hz has no rounding problem), takes 1 byte, and is the
# value the firmware writes to the sensor anyway.
# BMI270 register ACC_CONF, field acc_odr: code -> Hz. Check against the datasheet.
ODR_HZ = {
    0x01: 0.78125, 0x02: 1.5625, 0x03: 3.125, 0x04: 6.25,
    0x05: 12.5,    0x06: 25.0,   0x07: 50.0,  0x08: 100.0,
    0x09: 200.0,   0x0A: 400.0,  0x0B: 800.0, 0x0C: 1600.0,
}


def odr_code_for(rate_hz):
    for code, hz in ODR_HZ.items():
        if hz == rate_hz:
            return code
    raise ValueError(f"{rate_hz} Hz is not a BMI270 rate; valid: {sorted(ODR_HZ.values())}")


TRANSPORT_TCP = 0
TRANSPORT_UDP = 1

MODE_SEQUENTIAL = 0
MODE_PARALLEL = 1

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

# END (ESP32 -> RPi): "I have sent every sample of this session".
# Used only when the data goes over UDP. With TCP data, closing the data
# connection (FIN) already is a reliable end signal. UDP has no close, so the
# end is announced on the control channel, which is TCP and cannot lose it.
END_FMT = '<B'
END_SIZE = struct.calcsize(END_FMT)        # 1 byte
END_CODE = 0xFF
