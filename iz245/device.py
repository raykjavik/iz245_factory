from dataclasses import dataclass
from typing import List, Dict, Optional
from socket import socket
import numpy as np
from threading import Event, Thread, RLock
import time
from queue import Queue, Empty
from threading import Event, Thread, RLock
from pathlib import Path
import traceback
from datetime import datetime
from collections import namedtuple
import pickle

from iz245.geo import LocalTangentPlane
from iz245.protocol import HeaderV41, CAPTURE_SAMPLE_BYTES, capture_iq_data
from iz245.connection_utils import connect_main_scpi, connect_main_capture, connect_gps_scpi, connect_tcp_ip, TIMEOUT_SCPI
from iz245.scpi_utils import scpi_query, scpi_queries, scpi_command, scpi_commands
from iz245.models import Receiver, Measurement

LIGHT_SPEED = 299_792_458
OUTPUT_ROOT_DIR = Path(__file__).absolute().parent / "capture_data"
CAPTURE_TIMEOUT = 5
MEASUREMENT_PICKLE = "measurement.pickle"
MEASUREMENT_DAT = "measurement.dat"

SUFFIX_HEADER = ".hb"
SUFFIX_NPY = ".npy"


DEFAULT_IPs = [
    '10.0.22.200',
    #'10.0.22.201',
    #'10.0.22.202',
    #'10.0.22.203'
    ]

@dataclass
class CaptureJob:
    write_buffer: np.ndarray
    done_event: Event
    error: Optional[BaseException] = None


class SMA1000B:
    def __init__(self, ip="10.0.1.54",port=5025) -> None:
        self.main_scpi: socket = None
        self.ip: str = ip
        self.port = port
        self.scpi_lock = RLock()
        self.connected = False

    def open(self, tdoa_setting):
        with self.scpi_lock:
            if self.connected:
                self.close()

            try:
                self.main_scpi = connect_main_scpi(self.ip)
                self.connected = True
                return True

            except Exception as e:
                print(f"could not connect to {self.ip}, {e}")
                self.close()
                return False

    def close(self):
        with self.scpi_lock:
            if self.main_scpi is not None:
                try:
                    self.main_scpi.close()
                except Exception:
                    pass
                self.main_scpi = None
            self.connected = False

    def tune(self,frq_hz):
        with self.scpi_lock:
            opc = scpi_query(
                self.main_scpi,
                f"FREQ {frq_hz:.2f}Hz;*OPC?"
            )
            if opc.strip() != "1":
                raise RuntimeError(f"Unexpected *OPC? response: {opc!r}")

    def cmd(self,cmd):
        scpi_command(self.main_scpi, cmd)
        


class Device:
    def __init__(self, ip) -> None:
        self.raw_rx: bytearray = bytearray()
        self.main_scpi: socket = None
        self.capture_socket: socket = None
        self.ip: str = ip
        self.header = HeaderV41()
        self.connected = False
        self.scpi_lock = RLock()

    def _main_scpi_command(self, command: str) -> None:
        with self.scpi_lock:
            scpi_command(self.main_scpi, command)

    def _main_scpi_commands(self, commands) -> None:
        with self.scpi_lock:
            scpi_commands(self.main_scpi, commands)

    def _main_scpi_query(self, query: str) -> str:
        with self.scpi_lock:
            return scpi_query(self.main_scpi, query)

    def open(self, tdoa_setting):
        with self.scpi_lock:
            if self.connected:
                self.close()

            try:
                self.main_scpi = connect_main_scpi(self.ip)
                self.capture_socket = connect_main_capture(self.ip)

                self.connected = True

                if tdoa_setting:
                    self.on_tdoa_connect()
                    self.set_gps_static_mode()

                return True

            except Exception as e:
                print(f"could not connect to {self.ip}, {e}")
                self.close()
                return False




    def close(self):
        with self.scpi_lock:
            if self.main_scpi is not None:
                try:
                    self.main_scpi.close()
                except Exception:
                    pass
                self.main_scpi = None

            if self.capture_socket is not None:
                try:
                    self.capture_socket.close()
                except Exception:
                    pass
                self.capture_socket = None

            self.connected = False

    def info(sock):
        return scpi_queries(
            sock,
            query_list=[
                "SYST:ADCSR?",
                "BAND?",
                "FREQ?",
                "BAND:SAMP:IQ:FREQ?",
                "FILT?",
            ],
        )

    def aux_info(sock):
        return scpi_queries(
            sock,
            query_list=[
                "BAND?",
                "FREQ?",
                "TRACE:TYPE:IQTIME?",
            ],
        )

    def set_linear_mode(self):
        self._main_scpi_command("TRACE:TYPE:MEM:MODE LINEAR")

    def set_cyclic_mode(self):
        self._main_scpi_command("TRACE:TYPE:MEM:MODE LINEAR")
        self._main_scpi_command("TRACE:TYPE:MEM:MODE CYCLICRAM")

    def set_bw(self, bw_hz):
        self._main_scpi_command(f"BAND {bw_hz:.2f}Hz")

    def set_calibration(self, on):
        if on:
            self._main_scpi_command("sys:cal:on")
        else:
            self._main_scpi_command("sys:cal:off")


    def on_tdoa_connect(self):
        if not self.connected:
            raise RuntimeError("Connect the device first.")
        self._main_scpi_command("*RST")
        time.sleep(0.05)
        self._main_scpi_commands(
            [
                "TRACe:TYPe:MEMory:FORMAT32:BANDwidth:UPPer 1",
                "SYST:BOOT:MOD READY",
                "INP:PRES OFF",
                "INP:GAIN 0",
                "INP:ATT 0",
                "AUX:SYNC OFF",
            ]
        )

    def tune_to_hz(self, frq):
        self._main_scpi_command(f"FREQ {frq:.2f}Hz")
      

    def measure_point_rms(self, frq, dwell_sec):
        with self.scpi_lock:
            opc = scpi_query(
                self.main_scpi,
                f"FREQ {frq:.2f}Hz;*OPC?"
            )
            if opc.strip() != "1":
                raise RuntimeError(f"Unexpected *OPC? response: {opc!r}")

            scpi_command(self.main_scpi, "DETector:CLEar")
            time.sleep(dwell_sec)

            response = scpi_query(self.main_scpi, "sense:data?")
            return float(response.split(",")[3])

    def set_preselector(self, enable: bool):
        with self.scpi_lock:
            if enable:
                self._main_scpi_command("INP:PRES AUTO")
            else:
                self._main_scpi_command("INP:PRES OFF")

            self._main_scpi_query("INP:PRES?")

    def get_preselector(self):
        return self._main_scpi_query("INP:PRES?") == "AUTO"

    def set_input_gain(self, enabled):
        if enabled:
            self._main_scpi_command("INP:GAIN ON")
        else:
            self._main_scpi_command("INP:GAIN OFF")

    def get_input_gain(self):
        return self._main_scpi_query("INP:GAIN?") == "ON"

    def device_info(self):
        response = self._main_scpi_query("*IDN?").split(",")

        info = {"sn": response[2]}

        response = response[-1].split(" ")
        info[response[0]] = response[1]
        info[response[2]] = response[3]
        info[response[4]] = response[5]

        return info

    def ensure_rx_buffer(self, n):
        needed = HeaderV41.SIZE + n * CAPTURE_SAMPLE_BYTES
        if len(self.raw_rx) != needed:
            self.raw_rx = bytearray(needed)

    def capture_from_ts(self, ts_master, n):
        self._main_scpi_commands(
            [
                f"TRACe:TYPe:MEMory:RAM:TIME {ts_master}",
                f"TRACE:TYPE:MEM:SEND {n * 2}",
            ]
        )

    def get_receiver(self):
        with self.scpi_lock:
            info = self.device_info()

            lat, lon, ele = self._main_scpi_query("GNSS:COOR?").split(",")

            return Receiver(
                sn=info["sn"],
                HW=info["HW"],
                FPGA=info["FPGA"],
                FW=info["FW"],
                elevation=float(ele),
                lon=float(lon),
                lat=float(lat),
                ip=self.ip,
            )

    def set_gps_static_mode(self):
        sock = connect_gps_scpi(self.ip)

        try:
            resp = scpi_query(sock, "GNSS:MODE?")

            if resp != "SS":
                scpi_command(sock, "GNSS:MODE SS")

            resp = scpi_query(sock, "GNSS:MODE?")

            if resp != "SS":
                print(
                    f"Couldn't set static mode "
                    f"on device {self.ip}"
                )
        finally:
            sock.close()

    def get_sampling_rate_hz(self) -> int:
        return float(
            self._main_scpi_query("BAND:SAMP:IQ:FREQ?")
        )

    def get_trace_mem_time_ns(self) -> int:
        ts_s = float(
            self._main_scpi_query("TRACE:TYPE:MEM:TIM?")
        )
        return int(ts_s * 1e9)

    def lin_sweep(
        self,
        start_hz,
        stop_hz,
        dwell_sec,
        band_hz=40e6,
        n=396,
    ):
        step_hz = (stop_hz - start_hz) / (n - 1)

        with self.scpi_lock:
            if self.main_scpi is None:
                raise RuntimeError(
                    f"Device {self.ip} is not connected"
                )

            scpi_commands(
                self.main_scpi,
                [
                    f"SWEEP:BAND {band_hz}",
                    f"SWEEP:DWELL {dwell_sec}",
                    f"SWEEP:LIN {start_hz}Hz,{step_hz}Hz,{n}",
                    "SWEEP:RUN SINGLE",
                ],
            )

            LIST_EMPTY = b"LIST EMPTY"
            waited = 0

            try:
                while waited < 20:
                    self.main_scpi.sendall(
                        b"SWEEP:DATA:ALL?\n"
                    )
                    resp_bytes = (
                        self.main_scpi.recv(2056).strip()
                    )

                    if resp_bytes == LIST_EMPTY:
                        time.sleep(dwell_sec)
                        waited += 1
                        continue

                    waited = 0

                    arr = np.array(
                        [
                            float(x)
                            for x in resp_bytes.decode(
                                "ascii"
                            ).split(",")
                        ],
                        dtype=float,
                    ).reshape(-1, 9)

                    for row in arr:
                        yield row

            except (TimeoutError, socket.timeout):
                print(
                    f"SCPI {self.ip}: "
                    f"SWEEP:DATA:ALL? timeout"
                )
                return


class DeviceManager:
    def __init__(
        self,
        ips=DEFAULT_IPs,
        output_root_dir: Path = OUTPUT_ROOT_DIR,
        output_dir_name="MEA",
    ):
        self.ips = ips
        self.capture_queues: List[
            Queue[Optional[CaptureJob]]
        ] = [
            Queue(maxsize=1)
            for _ in range(len(ips))
        ]
        self.pending_jobs: List[CaptureJob] | None = None
        self.processing_clb = None
        self.threads: List[Thread] = None
        self.stop_event = Event()
        self.output_root_dir = output_root_dir
        self.output_dir_name = output_dir_name
        self.all_connected = False
        self.devices: List[Device] = [
            Device(ip)
            for ip in self.ips
        ]
        self.measurement: Measurement = None
        self.capture_ready: bool = False
        self.iq_buffer: List[np.array] = np.zeros((0, 0))

    def print_status(self):
        print("Device Manger Status:")
        print(f"IPs:{self.ips}")
        print(f"Output root dir: {self.output_root_dir}")
        print(f"Output dir name: {self.output_dir_name}")
        print(f"ALL CoNNECTED: {self.all_connected}")
        print(f"ALL CoNNECTED: {self.all_connected}")

    def get_measurement(self, fps=0.0):
        time_stamp = int(time.time() * 1e9)

        receivers = [
            d.get_receiver()
            for d in self.devices
        ]

        sampling_rate_Hz = 0

        for d in self.devices:
            sampling_rate_Hz_next = (
                d.get_sampling_rate_hz()
            )

            if sampling_rate_Hz == 0:
                sampling_rate_Hz = (
                    sampling_rate_Hz_next
                )
            else:
                assert (
                    sampling_rate_Hz
                    == sampling_rate_Hz_next
                )

        return Measurement(
            time_stamp=time_stamp,
            sampling_rate_Hz=sampling_rate_Hz,
            receivers=receivers,
            fps=fps,
        )

    def update_measurement(self, fps):
        self.measurement = self.get_measurement(fps)

    def get_connected_ips(self):
        connected = []
        for d in self.devices:
            if d.connected:
                connected.append(d.ip)
        return connected

    def open(self, tdoa_setting: bool):
        self.stop_event.clear()

        all_connected = True
        connected = []

        for d in self.devices:
            ok = d.open(tdoa_setting)
            all_connected = all_connected and ok

            if not ok:
                Warning(f"Couldn't connect {d.ip}")

            connected.append(ok)

        self.all_connected = all_connected
        return connected

    def _clear_capture_queues(self):
        for q in self.capture_queues:
            try:
                while True:
                    q.get_nowait()
            except Empty:
                pass

    def stop_capturing(self):
        if self.capture_ready:
            self.stop_event.set()

            for q in self.capture_queues:
                try:
                    q.put_nowait(None)
                except Exception:
                    pass

            if self.threads is not None:
                for t in self.threads:
                    t.join()

        self.threads = None
        self.pending_jobs = None
        self.capture_ready = False

        self._clear_capture_queues()

    def close(self):
        self.stop_capturing()
        self.all_connected = False

        for d in self.devices:
            d.close()

        self._clear_capture_queues()

    def capture_init(self, fps=0.0):
        if not self.all_connected:
            raise RuntimeError(
                "first connect all devices"
            )

        if self.capture_ready:
            raise RuntimeError(
                "capture already initialized"
            )

        self._clear_capture_queues()
        self.pending_jobs = None
        self.stop_event.clear()

        try:
            for d in self.devices:
                d.set_cyclic_mode()

            self.threads = [
                Thread(
                    target=self.capture_worker,
                    args=(i,),
                    daemon=True,
                )
                for i in range(len(self.devices))
            ]

            for t in self.threads:
                t.start()

            self.measurement = self.get_measurement(fps)
            self.capture_ready = True

        except Exception:
            self.stop_event.set()

            for q in self.capture_queues:
                try:
                    q.put_nowait(None)
                except Exception:
                    pass

            if self.threads is not None:
                for t in self.threads:
                    t.join()

            self.threads = None
            self.pending_jobs = None
            self.capture_ready = False
            self._clear_capture_queues()

            raise

    def config_capturing(
        self,
        bw_hz,
        fps=0.0,
    ):
        if self.all_connected:
            print("Reseting cyclick mode")

            for d in self.devices:
                d.set_bw(bw_hz)

            print(
                "all connected - "
                "geting measurment info"
            )

            self.measurement = (
                self.get_measurement(fps)
            )

            print(
                f"measurement {self.measurement}"
            )
        else:
            raise RuntimeError(
                "not all devices connected"
            )

    def capture_worker(self, i: int):
        device = self.devices[i]
        q = self.capture_queues[i]

        try:
            while not self.stop_event.is_set():
                try:
                    job: CaptureJob = q.get(
                        timeout=1.0
                    )
                except Empty:
                    continue

                if job is None:
                    break

                try:
                    n = len(job.write_buffer)

                    capture_iq_data(
                        device.capture_socket,
                        device.raw_rx,
                        job.write_buffer,
                        n,
                        device.header,
                    )

                    if not np.any(
                        job.write_buffer
                    ):
                        print(
                            f"Sensor {i}: "
                            f"capture buffer is all zeros!"
                        )

                except Exception as e:
                    print("n", n)
                    job.error = e
                    self.stop_event.set()

                finally:
                    job.done_event.set()
                    q.task_done()

        except Exception as e:
            print(
                f"Worker {i} crashed: {e!r}"
            )
            self.stop_event.set()

    def ensure_iq_buffer(
        self,
        ndevice,
        nsamples,
    ):
        nd, ns = np.shape(self.iq_buffer)

        if (
            nd != ndevice
            or ns != nsamples
        ):
            self.iq_buffer = np.empty(
                (ndevice, nsamples),
                dtype=np.complex64,
            )

    def capture(
        self,
        ts: int,
        nsamples: int,
    ):
        self.ensure_iq_buffer(
            len(self.devices),
            nsamples,
        )

        self.captures_into(
            ts,
            self.iq_buffer,
        )

    def captures_into(
        self,
        ts: int,
        iq_buffer: np.ndarray = None,
    ):
        if not self.capture_ready:
            raise RuntimeError(
                "call capture init befor "
                "start capturing"
            )

        nd, ns = iq_buffer.shape

        if nd != len(self.devices):
            raise ValueError(
                f"Expected {len(self.devices)} "
                f"write buffers, got {nd}"
            )

        jobs: List[CaptureJob] = []

        for i, d in enumerate(
            self.devices
        ):
            d.ensure_rx_buffer(n=ns)

            job = CaptureJob(
                write_buffer=iq_buffer[i, ...],
                done_event=Event(),
            )
            jobs.append(job)

            d.capture_from_ts(
                ts,
                ns,
            )

        for i, job in enumerate(jobs):
            self.capture_queues[
                i
            ].put_nowait(job)

        self.pending_jobs = jobs

    def await_captures(self):
        if self.pending_jobs is None:
            raise RuntimeError(
                "No captures are pending. "
                "Call start_captures() first."
            )

        jobs = self.pending_jobs
        self.pending_jobs = None

        for job in jobs:
            if not job.done_event.wait(
                CAPTURE_TIMEOUT
            ):
                raise TimeoutError(
                    "capture takes too long"
                )

        for i, job in enumerate(jobs):
            if job.error is not None:
                traceback.print_exception(
                    type(job.error),
                    job.error,
                    job.error.__traceback__,
                )
                raise RuntimeError(
                    f"Capture worker {i} failed: "
                    f"{job.error!r}"
                )

        d_master = self.devices[0]

        # for d in self.devices:
        #      print(d.header)
        for d_slave in self.devices[1:]:
            if  int(d_slave.header.time_stamp) != int(d_master.header.time_stamp):
                for d in self.devices:
                    print(d.header)
                assert False

        return (
            jobs[0]
            .write_buffer
            .base
            .reshape(
                (
                    len(self.devices),
                    -1,
                )
            )
        )

    def start_recording(self):
        self.dir = (
            self.output_root_dir
            / (
                self.output_dir_name
                + "_"
                + datetime.now().strftime(
                    "%Y%m%d_%H%M%S"
                )
            )
        )

        self.dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        with open(self.dir / MEASUREMENT_DAT, "wb") as f:
            f.write(self.measurement.to_bytes())

    def t0_ns(self):
        return max(
            [
                d.get_trace_mem_time_ns()
                for d in self.devices
            ]
        )

    def save_captures(
        self,
        read_buffers: List[np.ndarray],
    ):
        ts = (
            self.devices[0]
            .header
            .time_stamp
        )

        for i, (
            d,
            buf,
        ) in enumerate(
            zip(
                self.devices,
                read_buffers,
            )
        ):
            p = (
                self.dir
                / (
                    str(ts)
                    + "_"
                    + str(i)
                    + SUFFIX_HEADER
                )
            )

            with open(p, "wb") as f:
                f.write(
                    d.header.to_bytes()
                )

            p = (
                self.dir
                / (
                    str(ts)
                    + "_"
                    + str(i)
                )
            )

            np.save(
                p,
                buf,
                allow_pickle=False,
            )

    def tune_to_hz(
        self,
        frq_hz,
    ):
        if self.all_connected:
            for d in self.devices:
                d.tune_to_hz(
                    frq_hz
                )
        else:
            raise RuntimeError(
                "not all devices connected"
            )


SUFFIX_HEADER = ".hb"
SUFFIX_NPY = ".npy"

class FrameReader:
    @staticmethod
    def get_default_capture_dir() -> Path:
        return OUTPUT_ROOT_DIR

    @staticmethod
    def get_data_dirs():
        return [p for p in OUTPUT_ROOT_DIR.iterdir() if p.is_dir()]
    
    @staticmethod
    def get_latest_data_dir() -> Optional[Path]:
        dirs = [p for p in OUTPUT_ROOT_DIR.iterdir() if p.is_dir()]
        if not dirs:
            return None
        return max(dirs, key=lambda p: p.stat().st_mtime)
    
    def __init__(self):
        self.iq_buffer:List[np.array] = np.zeros((0,0))
        self.headers: List[HeaderV41] = []
        self.data_tree:List[List[Dict[str,Path]]] = None
        self.last_frame: int = 0
        self.last_loaded: int = 0
        self.measurement: Measurement = None

    def updatet_data_tree(self):
        last_ts = None
        dic = {}
        capture = []
        self.data_tree =[]

        for entry in sorted(self.dir.iterdir()):
            if entry.suffix not in [SUFFIX_NPY,SUFFIX_HEADER]:
                continue
            try:
                ts,id = entry.name.split("_")
                id = id.replace(entry.suffix,"")
            except:
                continue

            #assert len(ts)==19, f"the timestamp {ts} string has weird lenght. It should be 19 and it is {len(ts)}"

            if entry.suffix in dic.keys():
                capture.append(dic)
                dic = {}
            
            dic[entry.suffix]=entry

            if last_ts is not None:
                if ts != last_ts:
                    self.data_tree.append(capture)
                    capture = []

            last_ts = ts
        capture.append(dic)
        self.data_tree.append(capture)
        self.last_frame = len(self.data_tree)-1
    
    @staticmethod
    def unpickle(dir:Path):
        pickle_path = dir / MEASUREMENT_PICKLE
        if not pickle_path.is_file():
            raise FileExistsError(f"no measurement pickle in the {dir}")
        with open(dir / MEASUREMENT_PICKLE, "rb") as f:
            m:Measurement = pickle.load(f)
        p = dir / MEASUREMENT_DAT
        with open(p, "wb") as f:
            data= m.to_bytes()
            print(len(data))
            f.write(data)
        return m

    def select_dir(self, dir:Path=None):
        self.dir = dir
        m_dat_path= dir / MEASUREMENT_DAT
        if m_dat_path.is_file():
            with open(m_dat_path, "rb") as f: 
                self.measurement = Measurement.from_bytes(f.read())
        else:
            self.measurement = self.unpickle(dir)
        self.updatet_data_tree()
        self.data_cursor = 0
            
    def ensure_iq_buffer(self,ndevice,nsamples):
        nd,ns = np.shape(self.iq_buffer)
        if (nd != ndevice) or (ns != nsamples):
            self.iq_buffer = np.empty((ndevice, nsamples),dtype=np.complex64)

    def load_frame(
        self,
        fid: int,
        iq_buffer: np.ndarray = None,
    ):
        if self.data_tree is None:
            raise RuntimeError("the folder is not selected")

        if fid < 0 or fid >= len(self.data_tree):
            raise IndexError(
                f"Frame {fid} out of range. "
                f"Valid range is 0..{len(self.data_tree) - 1}"
            )

        n_captures = len(self.data_tree[fid])

        if n_captures == 0:
            raise RuntimeError(
                f"Frame {fid} contains no captures"
            )

        n_headers = len(self.headers)

        if n_headers < n_captures:
            for _ in range(n_captures - n_headers):
                self.headers.append(HeaderV41())

        # Load master header.
        with open(
            self.data_tree[fid][0][SUFFIX_HEADER],
            "rb",
        ) as f:
            self.headers[0].update_from_buffer(
                f.read(HeaderV41.SIZE)
            )

        for i in range(1, n_captures):
            with open(
                self.data_tree[fid][i][SUFFIX_HEADER],
                "rb",
            ) as f:
                self.headers[i].update_from_buffer(
                    f.read(HeaderV41.SIZE)
                )

            if (
                self.headers[i].sample_count
                != self.headers[0].sample_count
            ):
                raise ValueError(
                    "Captures in the same frame must have "
                    "the same sample count. "
                    f"Receiver 0: {self.headers[0].sample_count}, "
                    f"receiver {i}: {self.headers[i].sample_count}"
                )

        expected_nsamples = (
            self.headers[0].sample_count // 2
        )

        if iq_buffer is None:
            self.ensure_iq_buffer(
                n_captures,
                expected_nsamples,
            )
        else:
            nd, ns = np.shape(iq_buffer)

            if nd != n_captures:
                raise ValueError(
                    f"IQ buffer receiver count mismatch: "
                    f"expected {n_captures}, got {nd}"
                )

            if ns != expected_nsamples:
                raise ValueError(
                    f"IQ buffer sample count mismatch: "
                    f"expected {expected_nsamples}, got {ns}"
                )

            self.iq_buffer = iq_buffer

        for i in range(n_captures):
            path_data = self.data_tree[fid][i][SUFFIX_NPY]
            arr = np.load(
                path_data,
                allow_pickle=False,
            )

            self.iq_buffer[i, ...] = arr

        return self.headers


        







