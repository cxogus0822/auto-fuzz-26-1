"""Shared helpers for the standalone Raspberry Pi CAN lab tools."""

from __future__ import annotations

import json
import math
import socket
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple


class ConfigurationError(ValueError):
    """Raised when a command or YAML configuration is not usable."""


def require_module(name: str, install_name: Optional[str] = None) -> Any:
    try:
        return __import__(name)
    except ImportError as exc:
        package = install_name or name
        raise RuntimeError(
            f"필수 패키지 '{package}'가 없습니다. "
            "먼저 'python3 -m pip install -r requirements.txt'를 실행하세요."
        ) from exc


def load_yaml_config(path_value: Optional[str]) -> Tuple[Dict[str, Any], Optional[Path]]:
    if not path_value:
        return {}, None

    yaml = require_module("yaml", "PyYAML")
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise ConfigurationError(f"설정 파일을 찾을 수 없습니다: {path}")

    with path.open("r", encoding="utf-8") as handle:
        loaded = yaml.safe_load(handle) or {}
    if not isinstance(loaded, dict):
        raise ConfigurationError("YAML 최상위 값은 mapping이어야 합니다.")
    return loaded, path


def resolve_path(value: Optional[str], config_path: Optional[Path]) -> Optional[Path]:
    if not value:
        return None
    path = Path(value).expanduser()
    if not path.is_absolute() and config_path is not None:
        path = config_path.parent / path
    return path.resolve()


def parse_int(value: Any, field_name: str = "값") -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip().replace("_", "")
        try:
            return int(text, 0)
        except ValueError:
            if text and all(ch in "0123456789abcdefABCDEF" for ch in text):
                return int(text, 16)
    raise ConfigurationError(f"{field_name}을(를) 정수로 해석할 수 없습니다: {value!r}")


def parse_can_data(value: Any) -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, Sequence) and not isinstance(value, str):
        try:
            result = bytes(parse_int(item, "payload byte") for item in value)
        except ValueError as exc:
            raise ConfigurationError(f"잘못된 payload byte가 있습니다: {value!r}") from exc
        return result
    if not isinstance(value, str):
        raise ConfigurationError(f"CAN payload 형식이 잘못됐습니다: {value!r}")

    text = value.strip()
    for separator in (" ", ":", "-", ",", "_"):
        text = text.replace(separator, "")
    text = text.replace("0x", "").replace("0X", "")
    if len(text) % 2:
        raise ConfigurationError("CAN payload의 16진수 자릿수는 짝수여야 합니다.")
    try:
        return bytes.fromhex(text)
    except ValueError as exc:
        raise ConfigurationError(f"CAN payload가 올바른 16진수가 아닙니다: {value!r}") from exc


def parse_scalar(value: Any) -> Any:
    if not isinstance(value, str):
        return value
    text = value.strip()
    lowered = text.lower()
    if lowered in {"true", "on", "yes"}:
        return True
    if lowered in {"false", "off", "no"}:
        return False
    try:
        return int(text, 0)
    except ValueError:
        try:
            return float(text)
        except ValueError:
            return text


def parse_assignment(value: str) -> Tuple[str, Any]:
    if "=" not in value:
        raise ConfigurationError(f"신호 설정은 SIGNAL=VALUE 형식이어야 합니다: {value!r}")
    name, raw_value = value.split("=", 1)
    name = name.strip()
    if not name:
        raise ConfigurationError("신호 이름이 비어 있습니다.")
    return name, parse_scalar(raw_value)


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, bytes):
        return value.hex().upper()
    if isinstance(value, Mapping):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, Iterable):
        return [json_safe(item) for item in value]
    return str(value)


def write_jsonl(handle: Any, record: Mapping[str, Any]) -> None:
    handle.write(json.dumps(json_safe(record), ensure_ascii=False, separators=(",", ":")) + "\n")


def now_fields() -> Dict[str, Any]:
    wall_ns = time.time_ns()
    return {
        "wall_time": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(wall_ns / 1e9))
        + f".{wall_ns % 1_000_000_000:09d}",
        "wall_time_ns": wall_ns,
        "monotonic_ns": time.monotonic_ns(),
    }


def load_dbc(path: Path) -> Any:
    cantools = require_module("cantools")
    if not path.is_file():
        raise ConfigurationError(f"DBC 파일을 찾을 수 없습니다: {path}")
    try:
        return cantools.database.load_file(str(path), encoding="cp1252")
    except UnicodeDecodeError:
        return cantools.database.load_file(str(path), encoding="utf-8")


def resolve_message(database: Any, frame_id: Optional[int], message_name: Optional[str]) -> Any:
    by_id = None
    by_name = None
    if frame_id is not None:
        try:
            by_id = database.get_message_by_frame_id(frame_id)
        except KeyError as exc:
            raise ConfigurationError(f"DBC에 CAN ID 0x{frame_id:X}가 없습니다.") from exc
    if message_name:
        try:
            by_name = database.get_message_by_name(message_name)
        except KeyError as exc:
            raise ConfigurationError(f"DBC에 메시지 '{message_name}'가 없습니다.") from exc
    if by_id is not None and by_name is not None and by_id.frame_id != by_name.frame_id:
        raise ConfigurationError(
            f"지정한 ID 0x{frame_id:X}와 메시지 '{message_name}'가 서로 다릅니다."
        )
    message = by_id or by_name
    if message is None:
        raise ConfigurationError("DBC 송신에는 message 또는 id 중 하나가 필요합니다.")
    return message


def find_signal_messages(database: Any, signal_names: Iterable[str]) -> Dict[str, List[Any]]:
    wanted = set(signal_names)
    found: Dict[str, List[Any]] = {name: [] for name in wanted}
    for message in database.messages:
        for signal in message.signals:
            if signal.name in wanted:
                found[signal.name].append(message)
    return found


def open_can_bus(
    interface: str,
    channel: str,
    receive_own_messages: bool = False,
    bitrate: Optional[int] = None,
) -> Any:
    can = require_module("can", "python-can")
    kwargs: Dict[str, Any] = {
        "interface": interface,
        "channel": channel,
        "receive_own_messages": receive_own_messages,
    }
    # SocketCAN bitrate is configured by `ip link`, not by python-can.
    if bitrate is not None and interface not in {"socketcan", "virtual"}:
        kwargs["bitrate"] = bitrate
    try:
        return can.Bus(**kwargs)
    except TypeError:
        kwargs.pop("receive_own_messages", None)
        return can.Bus(**kwargs)


def shutdown_bus(bus: Any) -> None:
    shutdown = getattr(bus, "shutdown", None)
    if callable(shutdown):
        shutdown()


def signal_defaults(message: Any) -> Dict[str, Any]:
    values: Dict[str, Any] = {}
    for signal in message.signals:
        value = signal.initial
        if value is None:
            if signal.minimum is not None and signal.minimum > 0:
                value = signal.minimum
            elif signal.maximum is not None and signal.maximum < 0:
                value = signal.maximum
            else:
                value = 0
        values[signal.name] = value
    return values


def protected_signal_names(message: Any) -> List[str]:
    markers = ("crc", "checksum", "_bz", "counter", "alive", "zaehler", "zähler")
    return [signal.name for signal in message.signals if any(m in signal.name.lower() for m in markers)]


def validate_frame_id(frame_id: int, is_extended: bool) -> None:
    maximum = 0x1FFFFFFF if is_extended else 0x7FF
    if frame_id < 0 or frame_id > maximum:
        kind = "29-bit extended" if is_extended else "11-bit standard"
        raise ConfigurationError(f"0x{frame_id:X}는 {kind} CAN ID 범위를 벗어납니다.")


def hostname() -> str:
    return socket.gethostname()
