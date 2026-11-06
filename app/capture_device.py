"""App-side fix for IQ blocks with interleaved 72-byte receiver headers.

The installed iz245 package is unchanged. Keep the Device API and its header
object, but consume each block header before decoding that block's IQ payload.
On this protocol sample_count counts 16-bit words: payload bytes = count * 2,
including FORMAT32 (4 words, or 8 bytes, per complex IQ sample).
"""
import numpy as np
from iz245.device import Device
from iz245.protocol import HeaderV41, MAGIC


def _receive_exact(sock, target):
    view = memoryview(target).cast('B')
    while len(view):
        count = sock.recv_into(view)
        if count == 0:
            raise ConnectionError('Socket closed during capture')
        view = view[count:]


def read_capture_perpartes(sock_capture, clb, write_buffer, header,
                          sample_bytes=8, n=2048, cnt=16, overlap=.5,
                          debug=False):
    """Same callback/window contract as Device.read_capture_perpartes.

    Strip headers only at declared block boundaries; never scan sample values
    for MAGIC. Thus legitimate IQ values equal to header bytes remain data.
    TCP fragments and a block boundary inside an FFT window are both supported.
    """
    n, cnt = int(n), int(cnt)
    hop = n-int(n*overlap)
    total_samples = n+(cnt-1)*hop
    if n < 1 or cnt < 1 or not 0 <= overlap < 1 or sample_bytes not in (4,8):
        raise ValueError('Invalid capture window, count, overlap or IQ format.')
    if write_buffer.dtype != np.complex64 or not write_buffer.flags.c_contiguous or write_buffer.size < total_samples:
        raise ValueError('Capture needs a contiguous complex64 buffer for all windows.')
    output = write_buffer.reshape(-1).view(np.float32).reshape(-1,2)
    raw = bytearray(n*sample_bytes)
    raw_view = memoryview(raw)
    header_buffer = bytearray(HeaderV41.SIZE)
    block_remaining = 0
    block_index = 0
    payload_read = 0

    def read_payload(target):
        nonlocal block_remaining, block_index, payload_read
        offset = 0
        while offset < len(target):
            if block_remaining == 0:
                _receive_exact(sock_capture,header_buffer)
                header.update_from_buffer(header_buffer)
                if header.magic != MAGIC:
                    raise ValueError(f'Invalid capture block header after {payload_read} payload bytes: '
                                     f'magic={header.magic:#x}')
                block_remaining = int(header.sample_count)*2
                if block_remaining <= 0 or block_remaining % sample_bytes:
                    raise ValueError(f'Invalid block payload size {block_remaining} bytes.')
                expected_bytes = {1:4,2:8}.get(header.data_subtype)
                if expected_bytes != sample_bytes:
                    raise ValueError(f'IQ format mismatch: header subtype {header.data_subtype}, '
                                     f'app expects {sample_bytes} bytes per IQ sample.')
                if debug:
                    print(f'[IQ blocks] header={block_index} payload_offset_bytes={payload_read} '
                          f'sample_count={header.sample_count} payload_bytes={block_remaining} '
                          f'data_subtype={header.data_subtype} packet={header.packet_counter} '
                          f'timestamp={header.time_stamp}',flush=True)
                block_index += 1
            length = min(len(target)-offset,block_remaining)
            _receive_exact(sock_capture,target[offset:offset+length])
            offset += length
            block_remaining -= length
            payload_read += length

    def read_samples(destination, count):
        read_payload(raw_view[:count*sample_bytes])
        words = np.frombuffer(raw,dtype='<i2' if sample_bytes == 4 else '<i4',count=2*count)
        # Wire order Q,I; complex output real=I, imag=Q.
        np.copyto(destination[:,0],words[1::2],casting='unsafe')
        np.copyto(destination[:,1],words[0::2],casting='unsafe')

    read_samples(output[:n],n)
    clb(write_buffer.reshape(-1)[:n])
    start, new_start = hop,n
    for _ in range(1,cnt):
        end = new_start+hop
        read_samples(output[new_start:end],hop)
        clb(write_buffer.reshape(-1)[start:end])
        start += hop
        new_start = end


class CaptureDevice(Device):
    """Single Device with block-aware captures; all other driver methods inherited."""
    capture_debug = True

    def read_capture_perpartes(self,clb,write_buffer,n=2048,cnt=16,overlap=.5):
        return read_capture_perpartes(self.capture_socket,clb,write_buffer,self.header,
            sample_bytes=self.sample_bytes,n=n,cnt=cnt,overlap=overlap,
            debug=self.capture_debug)
