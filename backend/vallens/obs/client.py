"""OBS Studio WebSocket v5 client implementation using standard library sockets."""

import base64
import hashlib
import json
import logging
import os
from pathlib import Path
import socket
import struct
import threading
import time
from typing import Any, Callable, Optional

logger = logging.getLogger(__name__)


class WebSocketError(Exception):
    """Exception raised on WebSocket protocol errors."""
    pass


class RawWebSocket:
    """Minimal RFC 6455 WebSocket client over Python socket."""

    def __init__(self, host: str, port: int, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock: Optional[socket.socket] = None
        self._lock = threading.Lock()

    def connect(self) -> None:
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        # 16-byte random key for handshake
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        handshake = (
            f"GET / HTTP/1.1\r\n"
            f"Host: {self.host}:{self.port}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            f"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self.sock.sendall(handshake.encode("ascii"))
        response = b""
        while b"\r\n\r\n" not in response:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise WebSocketError("Connection closed during WebSocket handshake")
            response += chunk

        first_line = response.split(b"\r\n")[0].decode("latin1", errors="replace")
        if "101" not in first_line:
            raise WebSocketError(f"Handshake rejected: {first_line}")

    def send_text(self, text: str) -> None:
        data = text.encode("utf-8")
        length = len(data)
        mask_key = os.urandom(4)

        # FIN=1, Opcode=1 (text frame)
        header = bytearray([0x81])

        # Masked = 1
        if length <= 125:
            header.append(0x80 | length)
        elif length <= 65535:
            header.append(0x80 | 126)
            header.extend(struct.pack("!H", length))
        else:
            header.append(0x80 | 127)
            header.extend(struct.pack("!Q", length))

        header.extend(mask_key)

        masked_payload = bytearray(length)
        for i in range(length):
            masked_payload[i] = data[i] ^ mask_key[i % 4]

        with self._lock:
            if self.sock:
                self.sock.sendall(header + masked_payload)

    def recv_text(self) -> str:
        if not self.sock:
            raise WebSocketError("Socket is not connected")

        # Read 2-byte header
        head = self._recv_exact(2)
        opcode = head[0] & 0x0F
        is_masked = bool(head[1] & 0x80)
        payload_len = head[1] & 0x7F

        if opcode == 0x8:  # Close frame
            raise WebSocketError("Received WebSocket Close frame")

        if payload_len == 126:
            ext = self._recv_exact(2)
            payload_len = struct.unpack("!H", ext)[0]
        elif payload_len == 127:
            ext = self._recv_exact(8)
            payload_len = struct.unpack("!Q", ext)[0]

        mask = self._recv_exact(4) if is_masked else None
        raw_payload = self._recv_exact(payload_len)

        if is_masked and mask:
            unmasked = bytearray(payload_len)
            for i in range(payload_len):
                unmasked[i] = raw_payload[i] ^ mask[i % 4]
            return unmasked.decode("utf-8", errors="replace")

        return raw_payload.decode("utf-8", errors="replace")

    def _recv_exact(self, num_bytes: int) -> bytes:
        buf = bytearray()
        while len(buf) < num_bytes:
            chunk = self.sock.recv(num_bytes - len(buf))
            if not chunk:
                raise WebSocketError("Socket connection unexpectedly terminated")
            buf.extend(chunk)
        return bytes(buf)

    def close(self) -> None:
        if self.sock:
            try:
                # Send close frame
                self.sock.sendall(b"\x88\x80" + os.urandom(4))
                self.sock.close()
            except Exception:
                pass
            finally:
                self.sock = None


class ObsWebSocketClient:
    """Client for OBS Studio WebSocket v5 protocol."""

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 4455,
        password: Optional[str] = None,
        timeout: float = 5.0,
    ):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self.ws: Optional[RawWebSocket] = None
        self._request_counter = 0
        self._lock = threading.Lock()

    def connect(self) -> None:
        """Establish connection and perform OBS WebSocket v5 handshake & authentication."""
        self.ws = RawWebSocket(self.host, self.port, timeout=self.timeout)
        self.ws.connect()

        # Step 1: Wait for Hello (Op 0)
        hello_msg = json.loads(self.ws.recv_text())
        if hello_msg.get("op") != 0:
            raise RuntimeError(f"Expected Op 0 (Hello), got {hello_msg}")

        hello_data = hello_msg.get("d", {})
        auth_data = hello_data.get("authentication")

        # Step 2: Formulate Identify (Op 1)
        identify_d: dict[str, Any] = {"rpcVersion": 1}
        if auth_data:
            if not self.password:
                raise RuntimeError("OBS WebSocket requires authentication but no password was provided.")
            challenge = auth_data["challenge"]
            salt = auth_data["salt"]

            # OBS v5 auth hash calculation:
            # secret = base64(sha256(password + salt))
            # auth = base64(sha256(secret + challenge))
            secret_hash = hashlib.sha256((self.password + salt).encode("utf-8")).digest()
            secret_b64 = base64.b64encode(secret_hash).decode("ascii")

            auth_hash = hashlib.sha256((secret_b64 + challenge).encode("utf-8")).digest()
            identify_d["authentication"] = base64.b64encode(auth_hash).decode("ascii")

        self.ws.send_text(json.dumps({"op": 1, "d": identify_d}))

        # Step 3: Wait for Identified (Op 2)
        identified_msg = json.loads(self.ws.recv_text())
        if identified_msg.get("op") != 2:
            raise RuntimeError(f"Failed to identify with OBS: {identified_msg}")
        logger.info("Connected and authenticated with OBS Studio WebSocket v5.")

    def _call(self, request_type: str, request_data: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        """Send a Request (Op 6) and wait for RequestResponse (Op 7)."""
        if not self.ws:
            raise RuntimeError("OBS client is not connected.")

        with self._lock:
            self._request_counter += 1
            req_id = f"req_{self._request_counter}"
            payload = {
                "op": 6,
                "d": {
                    "requestType": request_type,
                    "requestId": req_id,
                    "requestData": request_data or {},
                },
            }
            self.ws.send_text(json.dumps(payload))

            # Read frames until matching response is received
            while True:
                msg = json.loads(self.ws.recv_text())
                op = msg.get("op")
                d = msg.get("d", {})
                if op == 7 and d.get("requestId") == req_id:
                    status = d.get("requestStatus", {})
                    if not status.get("result", False):
                        code = status.get("code")
                        comment = status.get("comment", "Unknown OBS error")
                        raise RuntimeError(f"OBS request {request_type} failed ({code}): {comment}")
                    return d.get("responseData", {})

    def start_recording(self) -> dict[str, Any]:
        """Trigger StartRecord in OBS."""
        logger.info("Sending StartRecord to OBS...")
        return self._call("StartRecord")

    def stop_recording(self) -> str:
        """Trigger StopRecord in OBS and return the saved output file path."""
        logger.info("Sending StopRecord to OBS...")
        resp = self._call("StopRecord")
        output_path = resp.get("outputPath", "")
        logger.info(f"OBS stopped recording. File saved at: {output_path}")
        return output_path

    def get_record_status(self) -> dict[str, Any]:
        """Query recording status (outputActive, outputDuration, outputPath)."""
        return self._call("GetRecordStatus")

    def close(self) -> None:
        """Close connection."""
        if self.ws:
            self.ws.close()
            self.ws = None


class MockObsClient:
    """Mock OBS client for offline development, CI/CD, and testing."""

    def __init__(
        self,
        default_output_path: Optional[str] = None,
        connected: bool = True,
    ):
        if not default_output_path:
            rec_dir = Path.cwd() / "data" / "recordings"
            rec_dir.mkdir(parents=True, exist_ok=True)
            default_output_path = str(rec_dir / "valorant_capture.mp4")
        self.default_output_path = default_output_path
        self.is_recording = False
        self.connected = connected
        self.start_time: Optional[float] = None

    def connect(self) -> None:
        self.connected = True

    def start_recording(self) -> dict[str, Any]:
        if not self.connected:
            raise RuntimeError("Mock OBS is not connected")
        self.is_recording = True
        self.start_time = time.time()
        return {}

    def stop_recording(self) -> str:
        if not self.connected:
            raise RuntimeError("Mock OBS is not connected")
        self.is_recording = False
        return self.default_output_path

    def get_record_status(self) -> dict[str, Any]:
        dur = int((time.time() - (self.start_time or time.time())) * 1000) if self.is_recording else 0
        return {
            "outputActive": self.is_recording,
            "outputDuration": dur,
            "outputPath": self.default_output_path if self.is_recording else "",
        }

    def close(self) -> None:
        self.connected = False
        self.is_recording = False
