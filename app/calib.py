from dataclasses import dataclass, field
from datetime import datetime as DateTime
from pathlib import Path
import numpy as np

ENCODING = "cp1252"

@dataclass
class CalibrationMeasurement:
    name: str = ""
    freq_hz: np.ndarray = field(default_factory=lambda: np.array([]))
    limit_dB: np.ndarray | None = None
    available: bool = False
    datetime: str = ""
    operator: str = ""
    unit: str = "dBµV"
    temperature: str = ""




    @classmethod
    def from_file(cls, file_path):
        path = Path(file_path)
        measurement = cls(name=path.stem, available=path.is_file())

        if not measurement.available:
            return measurement

        comments = {}
        frequencies = []
        limits = []

        with path.open(encoding=ENCODING) as file:
            for line in file:
                if line.startswith("#!"):
                    key, value = line[2:].split(":", 1)
                    comments[key.strip()] = value.strip()
                elif line.strip() and not line.startswith("freq[Hz]"):
                    frequency, limit, *_ = line.strip().split(";")
                    frequencies.append(float(frequency))
                    limits.append(float(limit) if limit else np.nan)

        comment_attributes = {
            "NAME": "name",
            "UNIT": "unit",
            "TEMP": "temperature",
            "OPERATOR": "operator",
        }

        for comment, attribute in comment_attributes.items():
            if comment in comments:
                setattr(measurement, attribute, comments[comment])

        if comments.get("DATE") and comments.get("TIME_UTC"):
            measurement.datetime = DateTime.strptime(
                f"{comments['DATE']} {comments['TIME_UTC']}",
                "%d/%m/%Y %H:%M:%S",
            ).isoformat()

        measurement.freq_hz = np.array(frequencies)
        measurement.limit_dB = (
            np.array(limits)
            if any(not np.isnan(value) for value in limits)
            else None
        )

        return measurement

    def save_to_file(self, file_path):
        timestamp = (
            DateTime.fromisoformat(self.datetime)
            if self.datetime
            else None
        )
        date = timestamp.strftime("%d/%m/%Y") if timestamp else ""
        time_utc = timestamp.strftime("%H:%M:%S") if timestamp else ""

        with Path(file_path).open("w", encoding=ENCODING) as file:
            file.write(f"#!NAME: {self.name}\n")
            file.write(f"#!UNIT: {self.unit}\n")
            file.write(f"#!DATE: {date}\n")
            file.write(f"#!TIME_UTC: {time_utc}\n")
            file.write(f"#!TEMP: {self.temperature}\n")
            file.write(f"#!OPERATOR: {self.operator}\n")
            file.write("freq[Hz];Limit[dB];\n")

            for index, frequency in enumerate(self.freq_hz):
                limit = (
                    self.limit_dB[index]
                    if self.limit_dB is not None
                    else ""
                )
                file.write(f"{frequency};{limit};\n")

        self.available = True


