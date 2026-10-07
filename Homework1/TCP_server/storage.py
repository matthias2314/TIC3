"""Storage: one CSV file per session, plus a small JSON file with its config and summary.

    sensores/session_20261004_214530_udp.csv     the samples, one row each
    sensores/session_20261004_214530_udp.json    the config and the final counters

"""
import csv
import json
from datetime import datetime, timedelta
from pathlib import Path

from protocol import describe_config
from data_channel import Sample

# The folders sit next to this file, wherever the program is started from
BASE_DIR = Path(__file__).resolve().parent
REAL_DIR = BASE_DIR / "sensores"          # sessions from the real ESP32 (the deliverable)
TEST_DIR = BASE_DIR / "sensores_test"     # sessions from esp_test.py (ignored by git)

# The settings repeated in every row, in this order
CONFIG_COLUMNS = ('range_g', 'rate_hz', 'mode', 'transport')
HEADER = ('timestamp',) + Sample._fields + CONFIG_COLUMNS


class CsvWriter:
    def __init__(self, config, folder):
        started = datetime.now()
        settings = describe_config(config)
        self.info = {
            'started': started.isoformat(timespec='seconds'),
            'config': settings,
        }
        self.config_values = [settings[name] for name in CONFIG_COLUMNS]
        self.clock_start = None                  # date and time of the first arrival

        # File name: date, time and transport
        folder.mkdir(exist_ok=True)
        name = f"session_{started:%Y%m%d_%H%M%S}_{settings['transport']}"
        path = folder / f"{name}.csv"
        n = 2
        while path.exists():                     # two sessions within the same second
            path = folder / f"{name}_{n}.csv"
            n += 1
        self.csv_path = path

        # Open the file and write the header row
        self.file = open(self.csv_path, 'w', newline='')
        self.writer = csv.writer(self.file)
        self.writer.writerow(HEADER)

    def write(self, sample):
        """Add one sample as a row: timestamp, the sample, the session's settings."""
        # Real date and time of arrival: the RPi's date at the first arrival,
        # plus rx_s. This way the timestamp and rx_s come from one clock reading.
        if self.clock_start is None:
            self.clock_start = datetime.now() - timedelta(seconds=sample.rx_s)
        arrived = self.clock_start + timedelta(seconds=sample.rx_s)
        timestamp = arrived.isoformat(timespec='microseconds')

        # Decimals are rounded to 6 places (1 µs, 1 µm/s²)
        values = [round(v, 6) if isinstance(v, float) else v for v in sample]
        self.writer.writerow([timestamp] + values + self.config_values)

    def close(self, stats):
        """Close the CSV and save the config and the final counters next to it."""
        self.file.close()

        self.info['csv_file'] = self.csv_path.name
        self.info['stats'] = stats
        json_path = self.csv_path.with_suffix('.json')
        with open(json_path, 'w') as f:
            json.dump(self.info, f, indent=2)

        print(f"Saved {self.csv_path.parent.name}/{self.csv_path.name} (+ .json)")
