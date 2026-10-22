from __future__ import annotations

import gc
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO

import numpy as np


@dataclass(frozen=True)
class ReceiverFile:
    receiver_id: int
    file: str


@dataclass(frozen=True)
class CTRecordingMeta:
    created_at: str
    sample_rate_hz: int
    bandwidth_hz: int
    center_frequency_hz: float | None
    n_receivers: int
    frame_shape: tuple[int, ...]
    samples_per_frame_per_receiver: int
    frames_recorded_per_receiver: int
    samples_recorded_per_receiver: int
    dtype: str
    receiver_files: tuple[ReceiverFile, ...]

    @property
    def np_dtype(self) -> np.dtype:
        return np.dtype(self.dtype)

    @property
    def frame_bytes(self) -> int:
        return (
            self.samples_per_frame_per_receiver
            * self.np_dtype.itemsize
        )

    @classmethod
    def from_template(
        cls,
        *,
        template_inputs: list[np.ndarray],
        total_frames: int,
        sample_rate_hz: int,
        bandwidth_hz: int,
        center_frequency_hz: float | None,
        receiver_files: list[ReceiverFile],
    ) -> CTRecordingMeta:
        if template_inputs is None:
            raise RuntimeError("Cannot create RT recording metadata without receiver buffers.")

        first = np.asarray(template_inputs[0])
        frame_shape = tuple(int(x) for x in first.shape)
        samples_per_frame = int(np.prod(frame_shape))
        dtype = np.dtype(first.dtype)

        for rx, arr in enumerate(template_inputs):
            arr = np.asarray(arr)
            if tuple(arr.shape) != frame_shape:
                raise RuntimeError(
                    f"Receiver {rx} frame shape mismatch: "
                    f"expected {frame_shape}, got {arr.shape}"
                )
            if np.dtype(arr.dtype) != dtype:
                raise RuntimeError(
                    f"Receiver {rx} dtype mismatch: "
                    f"expected {dtype}, got {arr.dtype}"
                )

        return cls(
            created_at=datetime.now().isoformat(),
            sample_rate_hz=int(sample_rate_hz),
            bandwidth_hz=int(bandwidth_hz),
            center_frequency_hz=None if center_frequency_hz is None else float(center_frequency_hz),
            n_receivers=len(template_inputs),
            frame_shape=frame_shape,
            samples_per_frame_per_receiver=samples_per_frame,
            frames_recorded_per_receiver=int(total_frames),
            samples_recorded_per_receiver=samples_per_frame * int(total_frames),
            dtype=dtype.str,
            receiver_files=tuple(receiver_files),
        )

    @classmethod
    def from_json_dict(cls, data: dict) -> CTRecordingMeta:
        receiver_files = tuple(
            ReceiverFile(
                receiver_id=int(item["receiver_id"]),
                file=str(item["file"]),
            )
            for item in data["receiver_files"]
        )

        return cls(
            created_at=str(data.get("created_at", "")),
            sample_rate_hz=int(data["sample_rate_hz"]),
            bandwidth_hz=int(data["bandwidth_hz"]),
            center_frequency_hz=data.get("center_frequency_hz", None),
            n_receivers=int(data["n_receivers"]),
            frame_shape=tuple(int(x) for x in data["frame_shape"]),
            samples_per_frame_per_receiver=int(data["samples_per_frame_per_receiver"]),
            frames_recorded_per_receiver=int(data["frames_recorded_per_receiver"]),
            samples_recorded_per_receiver=int(data["samples_recorded_per_receiver"]),
            dtype=str(data["dtype"]),
            receiver_files=receiver_files,
        )

    def to_json_dict(self) -> dict:
        return {
            "created_at": self.created_at,
            "sample_rate_hz": self.sample_rate_hz,
            "bandwidth_hz": self.bandwidth_hz,
            "center_frequency_hz": self.center_frequency_hz,
            "n_receivers": self.n_receivers,
            "frame_shape": list(self.frame_shape),
            "samples_per_frame_per_receiver": self.samples_per_frame_per_receiver,
            "frames_recorded_per_receiver": self.frames_recorded_per_receiver,
            "samples_recorded_per_receiver": self.samples_recorded_per_receiver,
            "dtype": self.dtype,
            "receiver_files": [
                {
                    "receiver_id": item.receiver_id,
                    "file": item.file,
                }
                for item in self.receiver_files
            ],
        }

    def validate(self) -> None:
        if self.n_receivers <= 0:
            raise RuntimeError("RT recording metadata has no receivers.")

        if len(self.receiver_files) != self.n_receivers:
            raise RuntimeError(
                f"RT recording metadata says n_receivers={self.n_receivers}, "
                f"but lists {len(self.receiver_files)} receiver files."
            )

        if self.frames_recorded_per_receiver <= 0:
            raise RuntimeError("RT recording metadata has no frames.")

        if not self.frame_shape:
            raise RuntimeError("RT recording metadata has empty frame_shape.")

        expected_samples = int(np.prod(self.frame_shape))
        if expected_samples != self.samples_per_frame_per_receiver:
            raise RuntimeError(
                "RT recording metadata sample count mismatch: "
                f"frame_shape implies {expected_samples}, "
                f"metadata says {self.samples_per_frame_per_receiver}."
            )


def make_rt_output_dir(parent_dir: Path, measurement_name: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Path(parent_dir) / f"{measurement_name}_{stamp}_RT"


def make_rt_file_prefix() -> str:
    now = datetime.now()
    return now.strftime("%y%m%d_%H%M%S.") + f"{now.microsecond // 1000:03d}"


def find_rt_recording_json(folder: Path) -> Path:
    folder = Path(folder)

    candidates = sorted(folder.glob("*_recording.json"))

    if not candidates:
        candidates = sorted(folder.glob("*.json"))

    if not candidates:
        raise RuntimeError(f"No RT recording JSON found in {folder}")

    if len(candidates) > 1:
        names = ", ".join(path.name for path in candidates)
        raise RuntimeError(
            f"Multiple JSON metadata files found in {folder}: {names}"
        )

    return candidates[0]


def load_rt_recording_meta(folder: Path) -> tuple[CTRecordingMeta, Path]:
    print(f"load rt meta {folder}")
    meta_path = find_rt_recording_json(folder)
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    meta = CTRecordingMeta.from_json_dict(data)
    meta.validate()
    return meta, meta_path


class CTRecordingWriter:
    """
    Sequential frame writer.

    This writes one frame per receiver at a time and does not keep the full
    recording in memory.
    """

    def __init__(
        self,
        *,
        output_dir: Path,
        meta_path: Path,
        meta: CTRecordingMeta,
        data_paths: list[Path],
        handles: list[BinaryIO],
    ):
        self.output_dir = output_dir
        self.meta_path = meta_path
        self.meta = meta
        self.data_paths = data_paths
        self._handles = handles
        self.frames_written = 0
        self._closed = False

    @classmethod
    def create(
        cls,
        *,
        output_dir: Path,
        template_inputs: list[np.ndarray],
        total_frames: int,
        sample_rate_hz: int,
        bandwidth_hz: int,
        center_frequency_hz: float | None,
    ) -> CTRecordingWriter:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        prefix = make_rt_file_prefix()

        receiver_files: list[ReceiverFile] = []
        data_paths: list[Path] = []

        for rx in range(len(template_inputs)):
            file_name = f"{prefix}_RECEIVER{rx}_data.dat"
            receiver_files.append(
                ReceiverFile(
                    receiver_id=rx,
                    file=file_name,
                )
            )
            data_paths.append(output_dir / file_name)

        meta = CTRecordingMeta.from_template(
            template_inputs=template_inputs,
            total_frames=total_frames,
            sample_rate_hz=sample_rate_hz,
            bandwidth_hz=bandwidth_hz,
            center_frequency_hz=center_frequency_hz,
            receiver_files=receiver_files,
        )

        meta_path = output_dir / f"{prefix}_recording.json"
        meta_path.write_text(
            json.dumps(meta.to_json_dict(), indent=2),
            encoding="utf-8",
        )

        handles = [path.open("wb") for path in data_paths]

        return cls(
            output_dir=output_dir,
            meta_path=meta_path,
            meta=meta,
            data_paths=data_paths,
            handles=handles,
        )

    @property
    def total_frames(self) -> int:
        return self.meta.frames_recorded_per_receiver

    def write_frame(self, per_receiver_frames: list[np.ndarray]) -> int:
        if self._closed:
            raise RuntimeError("Cannot write to closed RT recording writer.")

        if self.frames_written >= self.total_frames:
            raise RuntimeError("RT recording writer already received all expected frames.")

        if len(per_receiver_frames) != self.meta.n_receivers:
            raise RuntimeError(
                f"Expected {self.meta.n_receivers} receiver frames, "
                f"got {len(per_receiver_frames)}."
            )

        dtype = self.meta.np_dtype
        expected_shape = self.meta.frame_shape

        for rx, frame in enumerate(per_receiver_frames):
            arr = np.asarray(frame)

            if tuple(arr.shape) != expected_shape:
                raise RuntimeError(
                    f"Receiver {rx} frame shape mismatch: "
                    f"expected {expected_shape}, got {arr.shape}."
                )

            if np.dtype(arr.dtype) != dtype:
                arr = arr.astype(dtype, copy=False)

            arr = np.ascontiguousarray(arr)
            arr.tofile(self._handles[rx])

        self.frames_written += 1
        self.flush()

        return self.frames_written

    def flush(self) -> None:
        for handle in self._handles:
            handle.flush()

    def close(self) -> None:
        if self._closed:
            return

        for handle in self._handles:
            try:
                handle.flush()
            except Exception:
                pass

            try:
                handle.close()
            except Exception:
                pass

        self._closed = True

    def cleanup(self) -> None:
        self.close()
        gc.collect()

        for path in self.data_paths:
            try:
                path.unlink(missing_ok=True)
            except Exception:
                pass

        try:
            self.meta_path.unlink(missing_ok=True)
        except Exception:
            pass


class CTRecordingFrameReader:
    """
    Random-access frame reader.

    This keeps file handles open, but reads only one requested frame per
    receiver into RAM.
    """

    def __init__(
        self,
        *,
        input_dir: Path,
        meta_path: Path,
        meta: CTRecordingMeta,
        data_paths: list[Path],
        handles: list[BinaryIO],
    ):
        self.input_dir = input_dir
        self.meta_path = meta_path
        self.meta = meta
        self.data_paths = data_paths
        self._handles = handles
        self._closed = False

    @classmethod
    def open(cls, folder: Path) -> CTRecordingFrameReader:
        input_dir = Path(folder).expanduser().resolve()

        if not input_dir.exists() or not input_dir.is_dir():
            raise RuntimeError(f"RT recording folder does not exist: {input_dir}")

        meta, meta_path = load_rt_recording_meta(input_dir)

        ordered_files = sorted(
            meta.receiver_files,
            key=lambda item: item.receiver_id,
        )

        data_paths = [input_dir / item.file for item in ordered_files]

        expected_size = (
            meta.frames_recorded_per_receiver
            * meta.samples_per_frame_per_receiver
            * meta.np_dtype.itemsize
        )

        for path in data_paths:
            if not path.exists():
                raise RuntimeError(f"Missing RT recording data file: {path}")

            actual_size = path.stat().st_size
            if actual_size < expected_size:
                raise RuntimeError(
                    f"RT recording file is too small: {path}. "
                    f"Expected at least {expected_size} bytes, got {actual_size}."
                )

        handles = [path.open("rb") for path in data_paths]

        return cls(
            input_dir=input_dir,
            meta_path=meta_path,
            meta=meta,
            data_paths=data_paths,
            handles=handles,
        )



    def read_frame(self, frame_index: int) -> list[np.ndarray]:
        if self._closed:
            raise RuntimeError("Cannot read from closed RT recording reader.")

        frame_index = int(frame_index)

        if frame_index < 0 or frame_index >= self.total_frames:
            raise IndexError(
                f"RT frame index out of range: {frame_index}. "
                f"Valid range is 0..{self.total_frames - 1}."
            )

        offset = frame_index * self.meta.frame_bytes
        count = self.meta.samples_per_frame_per_receiver
        dtype = self.meta.np_dtype
        shape = self.meta.frame_shape

        frames: list[np.ndarray] = []

        for rx, handle in enumerate(self._handles):
            handle.seek(offset)

            arr = np.fromfile(
                handle,
                dtype=dtype,
                count=count,
            )

            if arr.size != count:
                raise RuntimeError(
                    f"Could not read full RT frame {frame_index} "
                    f"for receiver {rx}. Expected {count} samples, got {arr.size}."
                )

            frames.append(arr.reshape(shape))

        return frames

    def read_frame_into(self,buf:np.ndarray, frame_index: int) -> list[np.ndarray]:
        if self._closed:
            raise RuntimeError("Cannot read from closed RT recording reader.")

        frame_index = int(frame_index)

        if frame_index < 0 or frame_index >= self.meta.frames_recorded_per_receiver:
            raise IndexError(
                f"RT frame index out of range: {frame_index}. "
                f"Valid range is 0..{self.total_frames - 1}."
            )

        offset = frame_index * self.meta.frame_bytes
        count = self.meta.samples_per_frame_per_receiver
        dtype = self.meta.np_dtype

        for rx, handle in enumerate(self._handles):
            handle.seek(offset)

            buf[rx,:] = np.fromfile(
                handle,
                dtype=dtype,
                count=count,
            )



    def close(self) -> None:
        if self._closed:
            return

        for handle in self._handles:
            try:
                handle.close()
            except Exception:
                pass

        self._closed = True