from dataclasses import dataclass
from typing import ClassVar, Tuple
import struct
import numpy as np
import socket
TCP_HEADER_FORMAT = "< I H B B I I d f f f f f I Q 4I"
TCP_HEADER_SIZE = struct.calcsize(TCP_HEADER_FORMAT)
TCP_DATA_SIZE = 1400
TCP_PACKET_SIZE = TCP_HEADER_SIZE + TCP_DATA_SIZE

CAPTURE_SOURCE_DTYPE = np.int16
CAPTURE_SAMPLE_BYTES = 4
CAPTURE_STREAM_PACKET_SAMPLES = TCP_DATA_SIZE // CAPTURE_SAMPLE_BYTES

SWEEP_COL_FREQ = 8
SWEEP_COL_MIN = 0
SWEEP_COL_MAX = 1
SWEEP_COL_RMS = 3
SWEEP_COL_OVER = 7

MAGIC=3437079227


@dataclass(slots=True)
class HeaderV41:
    FORMAT: ClassVar[str] = TCP_HEADER_FORMAT
    SIZE: ClassVar[int] = struct.calcsize(FORMAT)
    _STRUCT: ClassVar[struct.Struct] = struct.Struct(FORMAT)
    magic: int = 0
    version: int = 0
    data_type: int = 0
    data_subtype: int = 0
    packet_counter: int = 0
    sample_count: int = 0
    center_freq: float = 0.0
    sample_rate: float = 0.0
    filter_BW: float = 0.0
    full_scale_definition_constant: float = 0.0
    fractional_amplitude_resolution: float = 0.0
    full_range_peak_dBm: float = 0.0
    receiver_status: int = 0
    time_stamp: int = 0
    extension: Tuple[int, int, int, int] = (0, 0, 0, 0)

    @classmethod
    def from_buffer(cls, buf, offset=0):
        unpacked = struct.unpack_from(cls.FORMAT, buf, offset)
        return cls(*unpacked[:-4], tuple(unpacked[-4:]))
    
    def update_from_buffer(self, buf, offset=0):
        unpacked = self._STRUCT.unpack_from(buf, offset)
        self.magic = unpacked[0]
        self.version = unpacked[1]
        self.data_type = unpacked[2]
        self.data_subtype = unpacked[3]
        self.packet_counter = unpacked[4]
        self.sample_count = unpacked[5]
        self.center_freq = unpacked[6]
        self.sample_rate = unpacked[7]
        self.filter_BW = unpacked[8]
        self.full_scale_definition_constant = unpacked[9]
        self.fractional_amplitude_resolution = unpacked[10]
        self.full_range_peak_dBm = unpacked[11]
        self.receiver_status = unpacked[12]
        self.time_stamp = unpacked[13]
        self.extension = (unpacked[14], unpacked[15], unpacked[16], unpacked[17])
        return self
    
    def to_bytes(self) -> bytes:
        return self._STRUCT.pack(
            self.magic,
            self.version,
            self.data_type,
            self.data_subtype,
            self.packet_counter,
            self.sample_count,
            self.center_freq,
            self.sample_rate,
            self.filter_BW,
            self.full_scale_definition_constant,
            self.fractional_amplitude_resolution,
            self.full_range_peak_dBm,
            self.receiver_status,
            self.time_stamp,
            *self.extension,
        )
    
    def get_gain_dBu(self):
        full_range_dBm = self.full_range_peak_dBm
        full_range = self.full_scale_definition_constant

        fullScale_dBuV = 106.98970 - 3.0102 + full_range_dBm
        fullScale_dBV = fullScale_dBuV - 120
        receiver_gain_dB = -fullScale_dBV
        if self.full_scale_definition_constant > 0:
            header_gain_dB = 20 * np.log10(full_range)
        else:
            header_gain_dB = 0

        total_gain_dB = receiver_gain_dB + header_gain_dB
        if self.data_subtype == 1:
            f_sampleBit = 16
        else:
            f_sampleBit = 32
        # print(f"capture bit precison:{f_sampleBit}")
        f_number_format_gain = 20 * (f_sampleBit - 1) * np.log10(2)
        return 120 - f_number_format_gain - total_gain_dB
    

def capture_iq_data(sock_capture:socket, raw_rx, buffer, samples, header: HeaderV41):

    needed = HeaderV41.SIZE + samples * CAPTURE_SAMPLE_BYTES
    view = memoryview(raw_rx)[:needed]

    received = 0
    while received < needed:
    #    print(f"received:{received}")
        n = sock_capture.recv_into(view[received:], needed - received)
        if n == 0:
            raise ConnectionError("Socket closed during capture")
        received += n
    

    header.update_from_buffer(view, 0)

    payload_i16 = np.frombuffer(view, dtype=np.int16, count=2 * samples, offset=HeaderV41.SIZE)
    out_f32 = buffer.view(np.float32).reshape(samples, 2)
    np.copyto(out_f32[:, 0], payload_i16[1::2], casting="unsafe")  # I -> real
    np.copyto(out_f32[:, 1], payload_i16[0::2], casting="unsafe")  # Q -> imag
    
    assert header.magic == MAGIC, f"magic does not match {header.magic},{MAGIC}"
