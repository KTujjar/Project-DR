"""Frame source fed over the network: the /phone page sends JPEGs, the camera worker reads them."""

import threading

import cv2
import numpy as np

NO_FRAME_WAIT_S = 1.0


class PushSource:
    """Implements the worker's FrameSource interface for frames pushed by a client.

    read() returns (True, None) when no new frame arrived in time, meaning "still connected,
    nothing yet", so the worker keeps waiting instead of treating it as a lost feed.
    """

    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._frame: np.ndarray | None = None
        self._seq = 0
        self._read_seq = 0

    def push_jpeg(self, data: bytes) -> bool:
        """Decodes and stores a frame. Returns False for data that isn't an image."""
        frame = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return False
        with self._cond:
            self._frame = frame
            self._seq += 1
            self._cond.notify_all()
        return True

    # --- FrameSource ---

    def isOpened(self) -> bool:
        return True

    def read(self) -> tuple[bool, np.ndarray | None]:
        with self._cond:
            self._cond.wait_for(lambda: self._seq > self._read_seq, timeout=NO_FRAME_WAIT_S)
            if self._seq == self._read_seq:
                return True, None
            self._read_seq = self._seq
            return True, self._frame

    def get(self, prop: int) -> float:
        return 0.0

    def release(self) -> None:
        pass  # stays open for the life of the service; the phone may reconnect at any time
