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
CAPTURE_SAMPLE_BYTES_I16 = 4
CAPTURE_SAMPLE_BYTES_I32 = 8
CAPTURE_STREAM_PACKET_SAMPLES = TCP_DATA_SIZE // CAPTURE_SAMPLE_BYTES_I32

SWEEP_COL_FREQ = 8
SWEEP_COL_MIN = 0
SWEEP_COL_MAX = 1
SWEEP_COL_RMS = 3
SWEEP_COL_OVER = 7

MAGIC=3437079227
_IQ_I16 = np.dtype("<i2")
_IQ_I32 = np.dtype("<i4")



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
    
    def get_gain_dBuV(self):
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
    


def _receive_into(recv_into, view):
    remaining = len(view)

    while remaining:
        received = recv_into(view)
        if received == 0:
            raise ConnectionError("Socket closed during capture")

        remaining -= received
        if remaining:
            view = view[received:]


def _copy_iq(out_f32, source_i, source_q):
    np.copyto(out_f32[:, 0], source_i, casting="unsafe")
    np.copyto(out_f32[:, 1], source_q, casting="unsafe")


def read_capture_v47(
    sock_capture,
    raw_rx,
    write_buffer,
    samples,
    sample_bytes,
    header,
):
    dtype = _IQ_I16 if sample_bytes == 4 else _IQ_I32
    needed = HeaderV41.SIZE + samples * sample_bytes
    view = memoryview(raw_rx)[:needed]

    payload = np.frombuffer(
        view,
        dtype=dtype,
        count=2 * samples,
        offset=HeaderV41.SIZE,
    )
    out_f32 = write_buffer[:samples].view(np.float32).reshape(samples, 2)

    _receive_into(sock_capture.recv_into, view)
    header.update_from_buffer(view, 0)
    assert header.magic == MAGIC

    # Wire order: Q, I. Output: real=I, imag=Q.
    _copy_iq(out_f32, payload[1::2], payload[0::2])


def read_capture_perpartes_v47(
    sock_capture,
    clb,
    write_buffer,
    header,
    sample_bytes=8,
    n=2048,
    cnt=128,
    overlap=0.5,
):
    dtype = _IQ_I16 if sample_bytes == 4 else _IQ_I32
    hop = n - int(n * overlap)

    raw = bytearray(max(n * sample_bytes, HeaderV41.SIZE))
    raw_view = memoryview(raw)

    header_view = raw_view[:HeaderV41.SIZE]
    first_view = raw_view[:n * sample_bytes]
    next_view = raw_view[:hop * sample_bytes]

    payload = np.frombuffer(raw, dtype=dtype, count=2 * n)
    first_i = payload[1::2]
    first_q = payload[0::2]
    next_i = first_i[:hop]
    next_q = first_q[:hop]

    output = write_buffer.view(np.float32).reshape(-1, 2)

    recv_into = sock_capture.recv_into
    receive = _receive_into
    copy_iq = _copy_iq

    receive(recv_into, header_view)
    header.update_from_buffer(header_view, 0)
    assert header.magic == MAGIC

    receive(recv_into, first_view)
    copy_iq(output[:n], first_i, first_q)
    clb(write_buffer[:n])

    start = hop
    new_start = n

    for _ in range(1, cnt):
        receive(recv_into, next_view)

        end = new_start + hop
        copy_iq(output[new_start:end], next_i, next_q)
        clb(write_buffer[start:end])

        start += hop
        new_start = end