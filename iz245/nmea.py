from __future__ import annotations

import argparse
import csv
import ctypes
import json
import logging
from logging.handlers import RotatingFileHandler
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import IntEnum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import zmq

PPSYNC_SCPI_PORT = 5020
LOGSERVER_PORT = 5010

logger = logging.getLogger(__name__)


class RequestType(IntEnum):
    CONNECT_AND_START = 1
    DISCONNECT = 2
    SHUT_DOWN = 3
    PING = 4
    GET_STATUS = 5


class StatusCode(IntEnum):
    OK = 0
    ERR = -1


def encode_request(req_type: RequestType, payload: Optional[Dict[str, Any]] = None) -> bytes:
    payload = payload or {}
    body = json.dumps(payload).encode("utf-8")
    return struct.pack(">BI", int(req_type), len(body)) + body


def decode_request(data: bytes) -> Tuple[RequestType, Dict[str, Any]]:
    if len(data) < 5:
        raise ValueError("Request too short")
    req_type_raw, body_len = struct.unpack(">BI", data[:5])
    body = data[5:]
    if len(body) != body_len:
        raise ValueError(f"Invalid payload length: expected {body_len}, got {len(body)}")
    return RequestType(req_type_raw), (json.loads(body.decode("utf-8")) if body else {})


def encode_response(status: int, payload: Optional[Dict[str, Any]] = None) -> bytes:
    payload = payload or {}
    body = json.dumps(payload).encode("utf-8")
    return struct.pack(">iI", int(status), len(body)) + body


def decode_response(data: bytes) -> Tuple[int, Dict[str, Any]]:
    if len(data) < 8:
        raise ValueError("Response too short")
    status, body_len = struct.unpack(">iI", data[:8])
    body = data[8:]
    if len(body) != body_len:
        raise ValueError(f"Invalid response length: expected {body_len}, got {len(body)}")
    return status, (json.loads(body.decode("utf-8")) if body else {})


def show_error_popup_best_effort(message: str, title: str = "Logging Service Error") -> None:
    try:
        if sys.platform != "win32":
            return

        ver = sys.getwindowsversion()
        if not (ver.major >= 10 and ver.build >= 22000):
            return

        MB_OK = 0x00000000
        MB_ICONERROR = 0x00000010
        MB_TOPMOST = 0x00040000
        MB_SETFOREGROUND = 0x00010000

        ctypes.windll.user32.MessageBoxW(
            0,
            str(message),
            str(title),
            MB_OK | MB_ICONERROR | MB_TOPMOST | MB_SETFOREGROUND,
        )
    except Exception:
        pass


@dataclass
class ConnectionState:
    ip: str
    log_socket: socket.socket
    thread: Optional[threading.Thread] = None
    stop_event: threading.Event = field(default_factory=threading.Event)
    csv_file_handle: Optional[Any] = None
    csv_writer: Optional[csv.writer] = None
    csv_path: Optional[Path] = None
    connection_status: str = "connected"
    last_error: Optional[str] = None
    reconnect_attempts: int = 0
    last_received_at: Optional[str] = None
    scpi_port: int = PPSYNC_SCPI_PORT
    log_port: int = LOGSERVER_PORT


class NMEALogService:
    def __init__(
        self,
        bind_addr: str,
        sync_log_dir: Optional[Path] = None,
        scpi_port: int = PPSYNC_SCPI_PORT,
        log_port: int = LOGSERVER_PORT,
        scpi_timeout_s: float = 3.0,
        log_timeout_s: float = 2.0,
        idle_timeout_s: Optional[float] = 30.0,
        reconnect_initial_s: float = 1.0,
        reconnect_max_s: float = 30.0,
    ) -> None:
        self.bind_addr = bind_addr
        self.scpi_port = scpi_port
        self.log_port = log_port
        self.scpi_timeout_s = scpi_timeout_s
        self.log_timeout_s = log_timeout_s
        if log_timeout_s <= 0 or scpi_timeout_s <= 0:
            raise ValueError("Socket timeouts must be positive")
        if idle_timeout_s is not None and idle_timeout_s <= 0:
            raise ValueError("idle_timeout_s must be positive or None")
        if not 0 < reconnect_initial_s <= reconnect_max_s:
            raise ValueError("Invalid reconnect delay range")
        self.idle_timeout_s = idle_timeout_s
        self.reconnect_initial_s = reconnect_initial_s
        self.reconnect_max_s = reconnect_max_s

        if sync_log_dir is None:
            sync_log_dir = Path(__file__).parent / "sync_logs"
        self.sync_log_dir = sync_log_dir
        self.sync_log_dir.mkdir(parents=True, exist_ok=True)

        self._ctx: Optional[zmq.Context] = None
        self._rep_socket: Optional[zmq.Socket] = None
        self._server_stop = threading.Event()

        self._connections: Dict[str, ConnectionState] = {}
        self._lock = threading.RLock()

        self._last_error: Optional[str] = None
        self._thread_failure = threading.Event()

    def run(self, ready_event: Optional[Any] = None) -> None:
        self._ctx = zmq.Context()
        self._rep_socket = self._ctx.socket(zmq.REP)
        self._rep_socket.setsockopt(zmq.LINGER, 0)
        self._rep_socket.bind(self.bind_addr)

        if ready_event is not None:
            ready_event.set()

        try:
            while not self._server_stop.is_set():
                try:
                    msg = self._rep_socket.recv()
                except zmq.ZMQError:
                    if self._server_stop.is_set():
                        break
                    raise

                req_type = None
                request_started = time.monotonic()
                try:
                    req_type, payload = decode_request(msg)
                    status, resp_payload = self._handle_request(req_type, payload)
                except Exception as exc:
                    logger.exception("Request handler failed: %s", req_type)
                    status, resp_payload = StatusCode.ERR, {"error": str(exc)}
                elapsed = time.monotonic() - request_started
                if elapsed >= 1.0:
                    logger.warning("Slow request %s: %.3f seconds", req_type, elapsed)

                try:
                    self._rep_socket.send(encode_response(status, resp_payload))
                except zmq.ZMQError:
                    break

                if req_type == RequestType.SHUT_DOWN and status == StatusCode.OK:
                    break
        finally:
            try:
                self._disconnect_impl()
            except Exception:
                pass

            if self._rep_socket is not None:
                try:
                    self._rep_socket.close(0)
                except Exception:
                    pass

            if self._ctx is not None:
                try:
                    self._ctx.term()
                except Exception:
                    pass

    def _handle_request(self, req_type: RequestType, payload: Dict[str, Any]) -> Tuple[int, Dict[str, Any]]:
        if req_type == RequestType.PING:
            return StatusCode.OK, {"message": "pong", "pid": os.getpid()}

        if req_type == RequestType.GET_STATUS:
            return StatusCode.OK, self._get_status_impl()



        if req_type == RequestType.CONNECT_AND_START:
            ips = payload.get("ips", [])
            scpi_port = int(payload.get("scpi_port", self.scpi_port))
            log_port = int(payload.get("log_port", self.log_port))
            return self._connect_and_start_impl(ips=ips, scpi_port=scpi_port, log_port=log_port)

        if req_type == RequestType.DISCONNECT:
            return self._disconnect_impl()

        if req_type == RequestType.SHUT_DOWN:
            status, resp = self._disconnect_impl()
            if status == StatusCode.OK:
                self._server_stop.set()
            return status, resp

        return StatusCode.ERR, {"error": f"Unsupported request type: {int(req_type)}"}

    def _get_status_impl(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "connected_ips": list(self._connections.keys()),
                "logging_threads": {
                    ip: bool(st.thread and st.thread.is_alive())
                    for ip, st in self._connections.items()
                },
                # connected_ips is the configured group, retained for API compatibility.
                "active_ips": [ip for ip, st in self._connections.items()
                               if st.connection_status == "connected"],
                "nodes": {ip: {
                    "status": st.connection_status,
                    "last_error": st.last_error,
                    "reconnect_attempts": st.reconnect_attempts,
                    "last_received_at": st.last_received_at,
                } for ip, st in self._connections.items()},
                "thread_failure": any(st.connection_status in ("failed", "reconnecting")
                                      for st in self._connections.values()),
                "last_error": self._last_error,
                "log_files": {
                    ip: str(st.csv_path) if st.csv_path else None
                    for ip, st in self._connections.items()
                },
            }



    def _connect_and_start_impl(self, ips: List[str], scpi_port: int, log_port: int) -> Tuple[int, Dict[str, Any]]:
        ips = list(dict.fromkeys(ips))
        if not ips:
            return StatusCode.ERR, {"error": "No IPs provided"}

        with self._lock:
            if self._connections:
                return StatusCode.ERR, {"error": "Already running. Disconnect first."}

            opened_states: List[ConnectionState] = []
            started_states: List[ConnectionState] = []

            try:
                for ip in ips:
                    state = self._radio_init_pps_gen(ip, scpi_port, log_port)
                    opened_states.append(state)

                self._connections = {st.ip: st for st in opened_states}
                self._last_error = None
                self._thread_failure.clear()

                for st in opened_states:
                    st.stop_event.clear()
                    t = threading.Thread(
                        target=self._logging_worker_wrapper,
                        name=f"log-{st.ip}",
                        args=(st,),
                        daemon=True,
                    )
                    st.thread = t
                    t.start()
                    started_states.append(st)

                for st in started_states:
                    if st.thread is None or not st.thread.is_alive():
                        raise RuntimeError(f"Failed to start logging thread for {st.ip}")

                return StatusCode.OK, {
                    "message": "Connected and logging started",
                    "ips": list(self._connections.keys()),
                }

            except Exception as exc:
                for st in opened_states:
                    st.stop_event.set()
                for st in opened_states:
                    self._stop_remote_logging_best_effort(st)
                    self._close_connection_state(st)
                deadline = time.monotonic() + 12.0
                for st in started_states:
                    st.thread.join(timeout=max(0.0, deadline - time.monotonic()))
                # Keep any surviving workers tracked so a new group cannot
                # start while old workers still own files or node connections.
                self._connections = {st.ip: st for st in started_states
                                     if st.thread.is_alive()}
                msg = f"Connect and start failed, rolled back all connections: {exc}"
                self._set_error(msg, popup=True)
                return StatusCode.ERR, {"error": msg}

    def _radio_init_pps_gen(self, ip: str, scpi_port: int, log_port: int) -> ConnectionState:
        sock_ppsync_scpi = None
        sock_logserver = None

        try:
            sock_ppsync_scpi = socket.create_connection((ip, scpi_port), timeout=5.0)
            sock_ppsync_scpi.settimeout(self.scpi_timeout_s)

            sock_logserver = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock_logserver.settimeout(5.0)
            sock_logserver.connect((ip, log_port))
            sock_logserver.settimeout(self.log_timeout_s)
            sock_logserver.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)

            sock_ppsync_scpi.sendall(b"LOG:STR0:MASK 0x0202\n")
            time.sleep(0.1)
            sock_ppsync_scpi.close()
            sock_ppsync_scpi = None

            return ConnectionState(
                ip=ip,
                log_socket=sock_logserver,
                scpi_port=scpi_port,
                log_port=log_port,
            )

        except Exception:
            if sock_ppsync_scpi is not None:
                try:
                    sock_ppsync_scpi.close()
                except Exception:
                    pass
            if sock_logserver is not None:
                try:
                    sock_logserver.close()
                except Exception:
                    pass
            raise

    def _stop_remote_logging_best_effort(self, st: ConnectionState) -> None:
        scpi_sock = None
        try:
            scpi_sock = socket.create_connection((st.ip, st.scpi_port), timeout=3.0)
            scpi_sock.settimeout(self.scpi_timeout_s)
            scpi_sock.sendall(b"LOG:STR0:MASK 0x0\n")
            time.sleep(0.05)
        except Exception:
            pass
        finally:
            if scpi_sock is not None:
                try:
                    scpi_sock.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass
                try:
                    scpi_sock.close()
                except Exception:
                    pass

    def _disconnect_impl(self) -> Tuple[int, Dict[str, Any]]:
        with self._lock:
            states = list(self._connections.values())

            if not states:
                return StatusCode.OK, {"message": "Already disconnected"}

            for st in states:
                st.stop_event.set()

            for st in states:
                self._stop_remote_logging_best_effort(st)

            for st in states:
                try:
                    st.log_socket.shutdown(socket.SHUT_RDWR)
                except Exception:
                    pass

                try:
                    st.log_socket.close()
                except Exception:
                    pass

            deadline = time.monotonic() + 12.0
            for st in states:
                if st.thread and st.thread.is_alive():
                    remaining = max(0.0, deadline - time.monotonic())
                    st.thread.join(timeout=remaining)

            alive = [st.ip for st in states if st.thread and st.thread.is_alive()]

            for st in states:
                self._close_connection_state(st)

            self._connections = {st.ip: st for st in states if st.ip in alive}

            if alive:
                msg = f"Failed to stop all threads within timeout. Still alive: {alive}"
                self._set_error(msg, popup=True)
                return StatusCode.ERR, {"error": msg}

            return StatusCode.OK, {"message": "Disconnected cleanly"}

    def _close_connection_state(self, st: ConnectionState) -> None:
        try:
            st.log_socket.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass

        try:
            st.log_socket.close()
        except Exception:
            pass

        if st.thread and st.thread.is_alive() and st.thread is not threading.current_thread():
            return

        try:
            if st.csv_file_handle is not None:
                st.csv_file_handle.flush()
                st.csv_file_handle.close()
        except Exception:
            pass
        finally:
            st.csv_file_handle = None
            st.csv_writer = None

    def _logging_worker_wrapper(self, st: ConnectionState) -> None:
        try:
            self._logging_worker(st)
        except Exception as exc:
            if st.stop_event.is_set():
                return
            st.connection_status = "failed"
            st.last_error = str(exc)
            msg = f"Logging thread failed for {st.ip}: {exc}"
            self._set_error(msg, popup=True)
            st.stop_event.set()
        finally:
            self._close_connection_state(st)
            if st.stop_event.is_set() and st.connection_status != "failed":
                st.connection_status = "stopped"

    def _reconnect_node(self, st: ConnectionState, reason: str) -> bool:
        """Recover only this node; all waits are interruptible between attempts."""
        st.connection_status = "reconnecting"
        st.last_error = reason
        self._set_error(f"Node {st.ip}: {reason}")
        try:
            st.log_socket.close()
        except OSError:
            pass
        delay = self.reconnect_initial_s
        while not st.stop_event.wait(delay):
            st.reconnect_attempts += 1
            try:
                replacement = self._radio_init_pps_gen(st.ip, st.scpi_port, st.log_port)
            except OSError as exc:
                st.last_error = str(exc)
                logger.warning("Reconnect %s attempt %s failed: %s",
                               st.ip, st.reconnect_attempts, exc)
                delay = min(delay * 2, self.reconnect_max_s)
                continue
            st.log_socket = replacement.log_socket
            if st.stop_event.is_set():
                # A reconnect may have enabled remote logging during disconnect.
                self._stop_remote_logging_best_effort(st)
                st.log_socket.close()
                return False
            st.connection_status = "connected"
            st.last_error = None
            logger.info("Reconnected node %s", st.ip)
            return True
        return False

    def _logging_worker(self, st: ConnectionState) -> None:
        self.sync_log_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}_{st.ip}.csv"
        csv_path = self.sync_log_dir / filename

        csv_fh = open(csv_path, "w", newline="", encoding="utf-8")
        # Publish the handle before the first write so wrapper cleanup also
        # covers a header/flush failure (for example a full disk).
        st.csv_file_handle = csv_fh
        writer = csv.writer(csv_fh)
        writer.writerow(["timestamp", "pps_err", "voltage", "offset"])
        csv_fh.flush()

        st.csv_file_handle = csv_fh
        st.csv_writer = writer
        st.csv_path = csv_path

        pps_err_ready = False
        voltage_ready = False
        offset_ready = False

        pps_err: Optional[int] = None
        voltage: Optional[float] = None
        offset: Optional[int] = None

        buf = b""
        last_data = time.monotonic()

        try:
            while not st.stop_event.is_set():
                failure = None
                try:
                    chunk = st.log_socket.recv(4096)
                    if not chunk:
                        failure = "Connection closed by peer"
                except socket.timeout:
                    if self.idle_timeout_s is None or time.monotonic() - last_data < self.idle_timeout_s:
                        continue
                    failure = f"No data for {self.idle_timeout_s:g} seconds"
                except OSError as exc:
                    failure = f"Log recv failed: {exc}"
                if st.stop_event.is_set():
                    break
                if failure is not None:
                    if not self._reconnect_node(st, failure):
                        break
                    # Do not combine partial records across a connection gap.
                    buf = b""
                    pps_err_ready = voltage_ready = offset_ready = False
                    last_data = time.monotonic()
                    continue
                last_data = time.monotonic()
                st.last_received_at = datetime.now().isoformat(timespec="seconds")
                buf += chunk
                lines = buf.split(b"\n")
                buf = lines[-1]
                if len(buf) > 65536:
                    raise ValueError(f"Unterminated NMEA line exceeds 64 KiB for {st.ip}")

                for raw in lines[:-1]:
                    if st.stop_event.is_set():
                        break

                    line = raw.rstrip(b"\r").decode("utf-8", errors="replace").strip()
                    if not line:
                        continue

                    if line.startswith("$PERDCRX"):
                        parts = line.split(",")

                        if len(parts) <= 9:
                            continue
                        try:
                            pps_err = int(parts[9])
                            pps_err_ready = True

                        except ValueError:
                            continue

                    elif line.startswith("OCXO"):
                        parts = line.split()
                        if len(parts) < 2:
                            continue
                        try:
                            voltage = float(parts[-2])
                            voltage_ready = True

                        except ValueError:
                            continue

                    elif line.startswith("DPLL"):
                        parts = line.split(",")
                        if len(parts) <= 2:
                            continue
                        field = parts[2]
                        if "=" not in field:
                            continue
                        try:
                            offset = float(field.split("=")[1])
                            offset_ready = True

                        except ValueError:
                            continue

                    else:
                        continue

                    if pps_err_ready and voltage_ready and offset_ready:
                        writer.writerow([
                            datetime.now().isoformat(timespec="seconds"),
                            pps_err,
                            voltage,
                            offset,
                        ])
                        csv_fh.flush()

                        pps_err_ready = False
                        voltage_ready = False
                        offset_ready = False

        finally:
            try:
                csv_fh.flush()
            except Exception:
                pass
            try:
                csv_fh.close()
            except Exception:
                pass
            st.csv_file_handle = None
            st.csv_writer = None

    def _set_error(self, message: str, popup: bool = False) -> None:
        self._last_error = message
        self._thread_failure.set()
        # Never show a modal dialog from the service or its worker threads.
        # The controller reports errors to the UI; the service keeps diagnostics.
        logger.error(message)


class NMEALoggerClient:
    def __init__(
        self,
        server_addr: str = "tcp://127.0.0.1:5557",
        request_timeout_ms: int = 15000,
        status_timeout_ms: int = 1500,
    ) -> None:
        self.server_addr = server_addr
        if request_timeout_ms <= 0 or status_timeout_ms <= 0:
            raise ValueError("Request timeouts must be positive")
        self.request_timeout_ms = request_timeout_ms
        self.status_timeout_ms = min(status_timeout_ms, request_timeout_ms)

        self._ctx: Optional[zmq.Context] = None
        self._req_socket: Optional[zmq.Socket] = None
        self._server_process: Optional[subprocess.Popen] = None
        self._server_pid: Optional[int] = None

    def _ensure_socket(self) -> None:
        if self._ctx is None:
            self._ctx = zmq.Context()

        if self._req_socket is None:
            sock = self._ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.LINGER, 0)
            sock.setsockopt(zmq.RCVTIMEO, self.request_timeout_ms)
            sock.setsockopt(zmq.SNDTIMEO, self.request_timeout_ms)
            sock.connect(self.server_addr)
            self._req_socket = sock

    def _reset_req_socket(self) -> None:
        if self._req_socket is not None:
            try:
                self._req_socket.close(0)
            except Exception:
                pass
            self._req_socket = None
        self._ensure_socket()

    def close(self) -> None:
        if self._req_socket is not None:
            try:
                self._req_socket.close(0)
            except Exception:
                pass
            self._req_socket = None

        if self._ctx is not None:
            try:
                self._ctx.term()
            except Exception:
                pass
            self._ctx = None

    def _server_command(self) -> List[str]:
        """Command used by the new interpreter to run only the server."""
        return [
            sys.executable,
            str(Path(__file__).resolve()),
            "--server",
            "--bind-addr",
            self.server_addr,
        ]

    def _spawn_server_process(self) -> subprocess.Popen:
        """
        Start a new Python interpreter in its own visible console/terminal.

        Windows:
            Uses CREATE_NEW_CONSOLE.

        Linux:
            Starts a supported terminal emulator and runs the server inside it.
            This requires a graphical desktop/session and an installed terminal
            emulator.
        """
        command = self._server_command()

        if sys.platform == "win32":
            return subprocess.Popen(
                command,
            )

        if sys.platform.startswith("linux"):
            terminal_commands = []

            terminal = shutil.which("x-terminal-emulator")
            if terminal:
                terminal_commands.append([terminal, "-e", *command])

            terminal = shutil.which("xterm")
            if terminal:
                terminal_commands.append([terminal, "-e", *command])

            terminal = shutil.which("konsole")
            if terminal:
                # --nofork makes the launched process easier to track.
                terminal_commands.append([terminal, "--nofork", "-e", *command])

            terminal = shutil.which("gnome-terminal")
            if terminal:
                # --wait keeps the launcher alive until the server command exits.
                terminal_commands.append([terminal, "--wait", "--", *command])

            if not terminal_commands:
                raise RuntimeError(
                    "No supported Linux terminal emulator found. Install one of: "
                    "x-terminal-emulator, xterm, konsole, or gnome-terminal."
                )

            last_error: Optional[Exception] = None
            for terminal_command in terminal_commands:
                try:
                    return subprocess.Popen(
                        terminal_command,
                        start_new_session=True,
                    )
                except OSError as exc:
                    last_error = exc

            raise RuntimeError(
                f"Failed to start a Linux terminal emulator: {last_error}"
            )

        raise NotImplementedError(
            f"Opening a dedicated console is not implemented for {sys.platform!r}"
        )

    def _probe_server(self, timeout_ms: int = 250) -> Optional[Dict[str, Any]]:
        """
        Ping the server with a short-lived ZMQ socket.

        This deliberately does not use self._req_socket because the normal client
        timeout may be many seconds, which would make startup probing too slow.
        """
        ctx = zmq.Context()
        sock: Optional[zmq.Socket] = None
        try:
            sock = ctx.socket(zmq.REQ)
            sock.setsockopt(zmq.LINGER, 0)
            sock.setsockopt(zmq.RCVTIMEO, timeout_ms)
            sock.setsockopt(zmq.SNDTIMEO, timeout_ms)
            sock.connect(self.server_addr)

            sock.send(encode_request(RequestType.PING, {}))
            response = sock.recv()
            status, payload = decode_response(response)
            if status == StatusCode.OK:
                return payload
            return None
        except Exception:
            return None
        finally:
            if sock is not None:
                try:
                    sock.close(0)
                except Exception:
                    pass
            try:
                ctx.term()
            except Exception:
                pass

    def _wait_for_server_ready(self, timeout_s: float = 10.0) -> Dict[str, Any]:
        deadline = time.monotonic() + timeout_s

        while time.monotonic() < deadline:
            payload = self._probe_server(timeout_ms=250)
            if payload is not None:
                return payload
            time.sleep(0.1)

        raise TimeoutError(f"Server did not become ready within {timeout_s:g} seconds")

    def _wait_for_server_exit(self, timeout_s: float = 10.0) -> bool:
        deadline = time.monotonic() + timeout_s

        while time.monotonic() < deadline:
            if self._probe_server(timeout_ms=150) is None:
                return True
            time.sleep(0.1)

        return self._probe_server(timeout_ms=150) is None

    def start_server(self) -> None:
        # If a server is already listening at this address, reuse it instead of
        # opening another console and failing to bind the same ZMQ endpoint.
        existing = self._probe_server(timeout_ms=250)
        if existing is not None:
            pid = existing.get("pid")
            self._server_pid = int(pid) if pid is not None else None
            self._reset_req_socket()
            return

        proc = self._spawn_server_process()
        self._server_process = proc

        try:
            payload = self._wait_for_server_ready(timeout_s=10.0)
        except Exception:
            self._hard_kill_server()
            raise

        pid = payload.get("pid")
        self._server_pid = int(pid) if pid is not None else None

        # Create a fresh normal-timeout REQ socket only after the server is ready.
        self._reset_req_socket()

        status, payload = self.ping()
        if status != StatusCode.OK:
            self._hard_kill_server()
            raise RuntimeError(f"Server started but ping failed: {payload}")

    def is_connected(self) -> bool:
        try:
            status, payload = self.get_status()
            if status != StatusCode.OK:
                return False
            connected_ips = payload.get("connected_ips", [])
            return len(connected_ips) > 0
        except Exception:
            return False

    def shut_down_server(self) -> Tuple[int, Dict[str, Any]]:
        try:
            status, payload = self._request(RequestType.SHUT_DOWN, {})
        except Exception as exc:
            status, payload = (
                StatusCode.ERR,
                {"error": f"Graceful shutdown request failed: {exc}"},
            )

        # Do not keep a REQ socket/context alive while waiting for the server to
        # disappear. Probing below uses short-lived independent sockets.
        self.close()

        if status == StatusCode.OK:
            if self._wait_for_server_exit(timeout_s=10.0):
                self._wait_for_launcher_exit(timeout_s=2.0)
                self._server_pid = None
                self._server_process = None
                return status, payload

            self._hard_kill_server()
            return StatusCode.ERR, {
                "error": "Server did not exit after graceful shutdown; killed hard"
            }

        self._hard_kill_server()
        return StatusCode.ERR, payload

    def _wait_for_launcher_exit(self, timeout_s: float) -> None:
        proc = self._server_process
        if proc is None or proc.poll() is not None:
            return

        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            # The actual server is already down. Some terminal emulators may
            # linger briefly; do not turn that into a shutdown failure.
            pass
        except Exception:
            pass

    def _hard_kill_server(self) -> None:
        # Kill the actual Python server by PID when known. This matters on Linux,
        # where Popen may represent the terminal emulator rather than Python.
        pid = self._server_pid
        if pid is not None and pid != os.getpid():
            try:
                if sys.platform == "win32":
                    os.kill(pid, signal.SIGTERM)
                else:
                    os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            except Exception:
                pass

        proc = self._server_process
        if proc is not None and proc.poll() is None:
            try:
                if sys.platform.startswith("linux"):
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except Exception:
                        proc.terminate()
                else:
                    proc.kill()
            except Exception:
                pass

            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                try:
                    if sys.platform.startswith("linux"):
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                except Exception:
                    pass
            except Exception:
                pass

        self._server_pid = None
        self._server_process = None

    def ping(self) -> Tuple[int, Dict[str, Any]]:
        return self._request(RequestType.PING, {})

    def get_status(self) -> Tuple[int, Dict[str, Any]]:
        return self._request(RequestType.GET_STATUS, {})

    def connect_and_start(
        self,
        ips: List[str],
        scpi_port: int = PPSYNC_SCPI_PORT,
        log_port: int = LOGSERVER_PORT,
    ) -> Tuple[int, Dict[str, Any]]:
        return self._request(
            RequestType.CONNECT_AND_START,
            {
                "ips": ips,
                "scpi_port": scpi_port,
                "log_port": log_port,
            },
        )

    def disconnect(self) -> Tuple[int, Dict[str, Any]]:
        return self._request(RequestType.DISCONNECT, {})

    def _request(
        self,
        req_type: RequestType,
        payload: Optional[Dict[str, Any]],
    ) -> Tuple[int, Dict[str, Any]]:
        self._ensure_socket()
        assert self._req_socket is not None

        timeout_ms = (self.status_timeout_ms if req_type in
                      (RequestType.GET_STATUS, RequestType.PING) else self.request_timeout_ms)
        self._req_socket.setsockopt(zmq.RCVTIMEO, timeout_ms)
        self._req_socket.setsockopt(zmq.SNDTIMEO, timeout_ms)
        data = encode_request(req_type, payload)

        try:
            self._req_socket.send(data)
            resp = self._req_socket.recv()
        except zmq.Again as exc:
            self._reset_req_socket()
            raise TimeoutError(
                f"Request timeout for {req_type.name} at {self.server_addr} "
                f"(send/receive timeout {timeout_ms} ms); server may be busy or unavailable"
            ) from exc
        except Exception:
            self._reset_req_socket()
            raise

        return decode_response(resp)


def _server_process_entry(
    bind_addr: str,
    ready_event: Optional[Any] = None,
) -> None:
    def _signal_handler(signum: int, frame: Any) -> None:
        raise KeyboardInterrupt()

    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except Exception:
        pass

    log_dir = Path(__file__).parent / "sync_logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "nmea_service.log", maxBytes=2_000_000,
                                  backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(threadName)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    server = NMEALogService(bind_addr=bind_addr)
    try:
        server.run(ready_event=ready_event)
    except KeyboardInterrupt:
        pass


def _run_demo() -> None:
    """Original standalone smoke-test/demo behavior."""
    client = NMEALoggerClient("tcp://127.0.0.1:5557")

    try:
        client.start_server()

        #print("is_connected before:", client.is_connected())

        input_ips = ["192.168.1.10", "192.168.1.11"]

        status, payload = client.connect_and_start(
            ips=input_ips,
            scpi_port=PPSYNC_SCPI_PORT,
            log_port=LOGSERVER_PORT,
        )
       # print("CONNECT_AND_START:", status, payload)

       # print("is_connected after:", client.is_connected())

        time.sleep(5)

        status, payload = client.get_status()
        print("STATUS:", status, payload)

        status, payload = client.disconnect()
        print("DISCONNECT:", status, payload)

        print("is_connected final:", client.is_connected())

    finally:
        status, payload = client.shut_down_server()
        print("SHUT_DOWN:", status, payload)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--server",
        action="store_true",
        help="Run only the NMEA log server in this interpreter.",
    )
    parser.add_argument(
        "--bind-addr",
        default="tcp://127.0.0.1:5557",
        help="ZeroMQ REP bind address for --server mode.",
    )
    args = parser.parse_args()

    if args.server:
        print(
            f"NMEA log server starting on {args.bind_addr} "
            f"(PID {os.getpid()})",
            flush=True,
        )
        try:
            _server_process_entry(
                bind_addr=args.bind_addr,
                ready_event=None,
            )
        finally:
            print("NMEA log server stopped.", flush=True)
        return

    _run_demo()


if __name__ == "__main__":
    main()