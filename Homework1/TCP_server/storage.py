"""Storage: one CSV file per session, plus a small JSON file with its config and summary.

    sensores/session_20261004_214530_udp.csv     the samples, one row each
    sensores/session_20261004_214530_udp.json    the config and the final counters
"""
import csv
import json
from datetime import datetime
from pathlib import Path

from protocol import describe_config
from data_channel import Sample

# The folder sits next to this file, wherever the program is started from
SESSIONS_DIR = Path(__file__).resolve().parent / "sensores"


class CsvWriter:
    def __init__(self, config):
        started = datetime.now()
        self.info = {
            'started': started.isoformat(timespec='seconds'),
            'config': describe_config(config),
        }

        # File name: date, time and transport
        SESSIONS_DIR.mkdir(exist_ok=True)
        name = f"session_{started:%Y%m%d_%H%M%S}_{self.info['config']['transport']}"
        path = SESSIONS_DIR / f"{name}.csv"
        n = 2
        while path.exists():                     # two sessions within the same second
            path = SESSIONS_DIR / f"{name}_{n}.csv"
            n += 1
        self.csv_path = path

        # Open the file and write the header row
        self.file = open(self.csv_path, 'w', newline='')
        self.writer = csv.writer(self.file)
        self.writer.writerow(Sample._fields)

    def write(self, sample):
        """Add one sample as a row. Decimals are rounded to 6 places (1 µs, 1 µm/s²)."""
        self.writer.writerow([round(v, 6) if isinstance(v, float) else v for v in sample])

    def close(self, stats):
        """Close the CSV and save the config and the final counters next to it."""
        self.file.close()

        self.info['csv_file'] = self.csv_path.name
        self.info['stats'] = stats
        json_path = self.csv_path.with_suffix('.json')
        with open(json_path, 'w') as f:
            json.dump(self.info, f, indent=2)

        print(f"Saved {SESSIONS_DIR.name}/{self.csv_path.name} (+ .json)")
