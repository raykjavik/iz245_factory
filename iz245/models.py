import struct
from dataclasses import dataclass
import socket

@dataclass(frozen=False)
class Receiver:
    sn: int
    HW: int
    FPGA: float
    FW: float
    elevation: float
    lon: float
    lat: float
    ip: str


    def __str__(self) -> str:
        return (
            f"SN:{self.sn}  "
            f"IP:{self.ip}  "
            f"ver:{self.HW}|{float(self.FPGA):g}|{float(self.FW):g}  "
            f"ele:{float(self.elevation):g}  "
            f"lon:{float(self.lon):.6f}  "
            f"lat:{float(self.lat):.6f}"
        )

@dataclass(frozen=False)
class Measurement:
    time_stamp: int  # shared time_stamp for all receivers
    sampling_rate_Hz: int
    receivers: list[Receiver]
    fps: float = 0.0

    def to_bytes(self) -> bytes:
        # Start with time_stamp and sampling_rate_Hz
        data = struct.pack("<QId", self.time_stamp, int(self.sampling_rate_Hz), self.fps)
        for r in self.receivers:
            # Convert IP to 4 bytes
            ip_bytes = socket.inet_aton(r.ip)  # throws exception if not valid IPv4

            # Pack receiver data (excluding r.time_stamp)
            receiver_data = struct.pack(
                "<Hhddddd",  # int16, 3x uint8, 3x float64
                int(r.sn),
                int(r.HW),
                float(r.FPGA),
                float(r.FW),
                float(r.elevation),
                float(r.lon),
                float(r.lat),
            )

            data += receiver_data + ip_bytes
        print(f"data len {len(data)}")
        return data
    

    def __str__(self) -> str:
        lines = [
            f"Measurement object:",
            f"time_stamp: {self.time_stamp}, "
            f"sampling_rate_Hz: {self.sampling_rate_Hz}, "
            f"fps: {self.fps}",
            f"receivers: {len(self.receivers)}",
        ]

        for i, r in enumerate(self.receivers):
            lines.append(f"[{i}] {r}")

        return "\n".join(lines)

    @classmethod
    def from_bytes(cls, data: bytes) -> "Measurement":
        # Unpack Measurement header
        header_size = struct.calcsize("<QId")
        time_stamp, sampling_rate_Hz, fps = struct.unpack("<QId", data[:header_size])

        # Receiver format
        receiver_fmt = "<Hhddddd"
        receiver_size = struct.calcsize(receiver_fmt) + 4  # +4 for IP
        receivers = []

        offset = header_size
     
        data_len = len(data)

        while offset + receiver_size <= data_len:
            receiver_data = data[offset : offset + receiver_size]
            offset += receiver_size

            # Unpack fixed fields and IP
            fields = struct.unpack(
                receiver_fmt, receiver_data[: struct.calcsize(receiver_fmt)]
            )
            ip_bytes = receiver_data[-4:]
            ip_str = socket.inet_ntoa(ip_bytes)

            receiver = Receiver(
                sn=fields[0],
                HW=fields[1],
                FPGA=fields[2],
                FW=fields[3],
                elevation=fields[4],
                lon=fields[5],
                lat=fields[6],
                ip=ip_str,
            )
            receivers.append(receiver)

        return cls(
            time_stamp=time_stamp,
            sampling_rate_Hz=sampling_rate_Hz,
            fps = fps,
            receivers=receivers,
        )