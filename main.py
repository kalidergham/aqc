"""Interactive Hand-Tracking → Arduino LED Controller.

A fully object-oriented application that tracks a hand with MediaPipe,
computes rotation-invariant finger curl using joint angles smoothed by a
vectorized Kalman filter, recognizes hand gestures, and drives 5 PWM LEDs
on an Arduino Uno over a robust auto-reconnecting serial link.

Run with a single command:

    python main.py

Protocol sent to the Arduino (newline-terminated ASCII):
    D,a0,a1,a2,a3,a4   -> per-finger angles 0..180 (Arduino maps to PWM)
    G,n                -> play gesture animation n (1..6)
    I                  -> enter idle breathing-wave mode

The Arduino wiring diagram is documented at the bottom of this file.
"""
from __future__ import annotations

import subprocess
import sys
import logging
import asyncio
import concurrent.futures
import time
import math
import threading
import platform
from dataclasses import dataclass, field
from collections import deque
from typing import Deque, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Logging
# --------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("HandArduinoApp")


# ---------------------------------------------------------------------------
# Dependency Manager
# ---------------------------------------------------------------------------
class DependencyManager:
    """Checks for and installs required third-party packages."""

    _IMPORT_MAP: Dict[str, str] = {
        "opencv-python": "cv2",
        "mediapipe": "mediapipe",
        "numpy": "numpy",
        "pyserial": "serial",
    }

    def __init__(self, packages: List[str]) -> None:
        self.packages = packages

    def _pip_name(self, package_string: str) -> str:
        """Extract the bare package name from a requirement specifier."""
        for op in ("==", ">=", "<=", "~=", ">", "<"):
            if op in package_string:
                return package_string.split(op)[0].strip()
        return package_string.strip()

    def _import_name(self, pip_name: str) -> str:
        """Map a pip package name to its importable module name."""
        return self._IMPORT_MAP.get(pip_name, pip_name.replace("-", "_"))

    def check_and_install(self) -> None:
        """Import each package; install it via pip only if missing."""
        for package in self.packages:
            pip_name = self._pip_name(package)
            import_name = self._import_name(pip_name)
            try:
                __import__(import_name)
                logger.info("Package '%s' already satisfied.", pip_name)
            except ImportError:
                logger.warning("'%s' not found - installing...", package)
                self._install(package)

    def _install(self, package: str) -> None:
        """Install a single package, exiting on hard failure."""
        try:
            subprocess.check_call(
                [sys.executable, "-m", "pip", "install", package]
            )
            logger.info("Successfully installed '%s'.", package)
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to install '%s': %s", package, exc)
            sys.exit(1)


# Flexible constraints avoid the exact-pin conflicts found in the original
# (mediapipe==0.10.21 may not exist; numpy must stay < 2.0 for mediapipe).
REQUIRED_PACKAGES = [
    "opencv-python>=4.8,<5",
    "mediapipe>=0.10,<0.11",
    "numpy>=1.24,<2.0",
    "pyserial>=3.5",
]

DependencyManager(REQUIRED_PACKAGES).check_and_install()

import cv2  # noqa: E402
import mediapipe as mp  # noqa: E402
import numpy as np  # noqa: E402
import serial  # noqa: E402


# ---------------------------------------------------------------------------
# Configuration (dataclasses)
# ---------------------------------------------------------------------------
@dataclass
class SerialConfig:
    """Serial-link configuration."""

    port: str = "COM3"
    baudrate: int = 115200
    timeout: float = 1.0
    reconnect_interval: float = 2.0
    send_rate_hz: int = 40
    gesture_cooldown: float = 1.2


@dataclass
class CameraConfig:
    """Camera capture configuration."""

    index: int = 0
    width: int = 960
    height: int = 540
    fps: int = 30
    watchdog_timeout: float = 3.0


@dataclass
class VisionConfig:
    """MediaPipe / vision-processing configuration."""

    max_num_hands: int = 1
    model_complexity: int = 0
    min_detection_confidence: float = 0.6
    min_tracking_confidence: float = 0.5
    enable_face_pose: bool = False  # heavy; off by default for low CPU
    face_pose_every_n: int = 4


@dataclass
class FilterConfig:
    """Kalman-filter tuning."""

    process_noise: float = 0.01
    measurement_noise: float = 0.10


@dataclass
class RenderConfig:
    """On-screen rendering / overlay configuration."""

    overlay_size: Tuple[int, int] = (160, 160)  # (height, width)
    overlay_margin: int = 10
    trail_length: int = 24
    glow: bool = True
    trail: bool = True


@dataclass
class AppConfig:
    """Top-level application configuration container."""

    serial: SerialConfig = field(default_factory=SerialConfig)
    camera: CameraConfig = field(default_factory=CameraConfig)
    vision: VisionConfig = field(default_factory=VisionConfig)
    filt: FilterConfig = field(default_factory=FilterConfig)
    render: RenderConfig = field(default_factory=RenderConfig)
    window_name: str = "Interactive Hand & Arduino"
    idle_after: float = 5.0


# ---------------------------------------------------------------------------
# Serial Protocol
# ---------------------------------------------------------------------------
class SerialProtocol:
    """Builds the newline-terminated ASCII messages the Arduino expects."""

    @staticmethod
    def data(angles: List[int]) -> str:
        """Build a 'D' frame of 5 finger angles (0..180)."""
        vals = ",".join(str(int(max(0, min(180, a)))) for a in angles)
        return f"D,{vals}\n"

    @staticmethod
    def gesture(gesture_id: int) -> str:
        """Build a 'G' frame requesting a gesture animation."""
        return f"G,{int(gesture_id)}\n"

    @staticmethod
    def idle() -> str:
        """Build the 'I' frame requesting idle breathing mode."""
        return "I\n"

    @staticmethod
    def off() -> str:
        """Build a 'D' frame turning all LEDs off."""
        return "D,0,0,0,0,0\n"


# ---------------------------------------------------------------------------
# Arduino Client (async, auto-reconnecting)
# ---------------------------------------------------------------------------
class ArduinoClient:
    """Thread-safe async serial client with automatic reconnection."""

    def __init__(
        self,
        cfg: SerialConfig,
        executor: Optional[concurrent.futures.Executor] = None,
    ) -> None:
        self.cfg = cfg
        self._serial: Optional[serial.Serial] = None
        self._executor = executor or concurrent.futures.ThreadPoolExecutor(
            max_workers=2
        )
        self._io_lock = threading.Lock()
        self._last_reconnect_attempt = 0.0
        self.connected: bool = False

    def open(self) -> bool:
        """Attempt to open the serial port; never raises."""
        with self._io_lock:
            return self._open_locked()

    def _open_locked(self) -> bool:
        try:
            if self._serial and self._serial.is_open:
                return True
            logger.info(
                "Opening serial %s @ %d baud.", self.cfg.port, self.cfg.baudrate
            )
            self._serial = serial.Serial(
                self.cfg.port, self.cfg.baudrate, timeout=self.cfg.timeout
            )
            time.sleep(2.0)  # allow Arduino auto-reset to complete
            self.connected = True
            logger.info("Serial connected.")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Serial open failed: %s", exc)
            self._serial = None
            self.connected = False
            return False

    def _blocking_write(self, msg: str) -> None:
        """Write bytes to the port in the executor thread (blocking)."""
        with self._io_lock:
            try:
                if self._serial is None or not self._serial.is_open:
                    self._maybe_reconnect_locked()
                    return
                self._serial.write(msg.encode("ascii", errors="ignore"))
                self._serial.flush()
            except Exception as exc:  # noqa: BLE001
                logger.error("Serial write error: %s - dropping link.", exc)
                self._safe_close_locked()
                self.connected = False

    def _maybe_reconnect_locked(self) -> None:
        """Throttled reconnection attempt (called while holding the lock)."""
        now = time.time()
        if now - self._last_reconnect_attempt < self.cfg.reconnect_interval:
            return
        self._last_reconnect_attempt = now
        self._open_locked()

    def _safe_close_locked(self) -> None:
        try:
            if self._serial and self._serial.is_open:
                self._serial.close()
        except Exception:  # noqa: BLE001
            pass
        self._serial = None

    async def write(self, msg: str) -> None:
        """Schedule a blocking write on the executor without blocking the loop."""
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(self._executor, self._blocking_write, msg)

    def close(self) -> None:
        """Close the serial port cleanly."""
        with self._io_lock:
            try:
                if self._serial and self._serial.is_open:
                    self._serial.close()
                    logger.info("Serial port closed.")
            except Exception as exc:  # noqa: BLE001
                logger.error("Error closing serial: %s", exc)
            finally:
                self._serial = None
                self.connected = False


# ---------------------------------------------------------------------------
# Vectorized Kalman Filter for landmark smoothing
# ---------------------------------------------------------------------------
class LandmarkKalman:
    """Constant-velocity Kalman filter applied to N 2D points at once.

    State per point is [x, y, vx, vy]; measurements are [x, y]. All points
    are updated with vectorized NumPy operations for low CPU cost.
    """

    def __init__(self, num_points: int, cfg: FilterConfig) -> None:
        self.n = num_points
        self._F = np.array(
            [[1, 0, 1, 0], [0, 1, 0, 1], [0, 0, 1, 0], [0, 0, 0, 1]],
            dtype=np.float32,
        )
        self._H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=np.float32)
        self._Q = np.eye(4, dtype=np.float32) * cfg.process_noise
        self._R = np.eye(2, dtype=np.float32) * cfg.measurement_noise
        self._X: Optional[np.ndarray] = None       # (n, 4)
        self._P: Optional[np.ndarray] = None        # (n, 4, 4)
        self._initialized = False

    def reset(self) -> None:
        """Forget all state (called when the hand is lost)."""
        self._initialized = False
        self._X = None
        self._P = None

    def update(self, measurements: np.ndarray) -> np.ndarray:
        """Predict + correct with new (n, 2) measurements; return smoothed xy."""
        z = measurements.astype(np.float32)
        if not self._initialized or self._X is None:
            self._X = np.zeros((self.n, 4), dtype=np.float32)
            self._X[:, :2] = z
            self._P = np.tile(np.eye(4, dtype=np.float32), (self.n, 1, 1))
            self._initialized = True
            return z

        # Predict
        self._X = self._X @ self._F.T
        self._P = np.einsum("ij,njk,lk->nil", self._F, self._P, self._F) + self._Q

        # Update
        y = z - self._X @ self._H.T                                  # (n, 2)
        s = np.einsum("ij,njk,lk->nil", self._H, self._P, self._H) + self._R
        s_inv = np.linalg.inv(s)                                     # (n, 2, 2)
        k = np.einsum("nij,kj,nkl->nil", self._P, self._H, s_inv)    # (n, 4, 2)
        self._X = self._X + np.einsum("nij,nj->ni", k, y)
        eye4 = np.eye(4, dtype=np.float32)
        kh = np.einsum("nij,jk->nik", k, self._H)                    # (n, 4, 4)
        self._P = np.einsum("nij,njk->nik", (eye4 - kh), self._P)
        return self._X[:, :2].copy()


# ---------------------------------------------------------------------------
# Hand Detector
# ---------------------------------------------------------------------------
class HandDetector:
    """Wraps MediaPipe Hands and returns normalized + pixel landmark data."""

    def __init__(self, cfg: VisionConfig) -> None:
        self._mp_hands = mp.solutions.hands
        self._mp_drawing = mp.solutions.drawing_utils
        self.hands = self._mp_hands.Hands(
            static_image_mode=False,
            max_num_hands=cfg.max_num_hands,
            model_complexity=cfg.model_complexity,
            min_detection_confidence=cfg.min_detection_confidence,
            min_tracking_confidence=cfg.min_tracking_confidence,
        )
        self.connections = self._mp_hands.HAND_CONNECTIONS

    def process(
        self, image: np.ndarray, already_flipped: bool
    ) -> Tuple[Optional[np.ndarray], Optional[str]]:
        """Detect the primary hand.

        Returns (landmarks_px, hand_label). landmarks_px is an (21, 3) array of
        pixel x, pixel y, relative z. The label is corrected for the fact that
        the frame is mirrored before processing.
        """
        if image is None:
            return None, None
        try:
            image_rgb = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
            image_rgb.flags.writeable = False
            results = self.hands.process(image_rgb)
            if not results.multi_hand_landmarks:
                return None, None

            h, w = image.shape[:2]
            main = results.multi_hand_landmarks[0]
            lm = np.array(
                [[p.x * w, p.y * h, p.z * w] for p in main.landmark],
                dtype=np.float32,
            )

            label = "Unknown"
            if results.multi_handedness:
                raw = results.multi_handedness[0].classification[0].label
                # The frame was mirrored before processing, so invert the label
                # to reflect the user's real hand.
                if already_flipped:
                    label = "Left" if raw == "Right" else "Right"
                else:
                    label = raw
            return lm, label
        except Exception as exc:  # noqa: BLE001
            logger.error("Hand detection error: %s", exc)
            return None, None

    def draw(self, image: np.ndarray, lm_px: np.ndarray, label: str) -> None:
        """Draw MediaPipe connections from a smoothed (21, >=2) array."""
        try:
            color = (0, 255, 0) if label == "Right" else (0, 200, 255)
            for a, b in self.connections:
                pa = (int(lm_px[a][0]), int(lm_px[a][1]))
                pb = (int(lm_px[b][0]), int(lm_px[b][1]))
                cv2.line(image, pa, pb, color, 2, cv2.LINE_AA)
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        """Release MediaPipe resources."""
        try:
            self.hands.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Finger Analyzer (rotation-invariant joint angles)
# ---------------------------------------------------------------------------
class FingerAnalyzer:
    """Computes joint angles, curl, extension flags and finger count.

    All math is based on angles between bone vectors, which makes results
    invariant to hand rotation (including a full 180 flip).
    """

    # Landmark triplets used to measure the main joint of each finger.
    JOINTS: Dict[str, Tuple[int, int, int]] = {
        "thumb": (2, 3, 4),
        "index": (5, 6, 8),
        "middle": (9, 10, 12),
        "ring": (13, 14, 16),
        "pinky": (17, 18, 20),
    }
    ORDER: List[str] = ["thumb", "index", "middle", "ring", "pinky"]
    TIP_IDS: List[int] = [4, 8, 12, 16, 20]

    @staticmethod
    def _angle(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
        """Return the angle ABC in degrees (vertex at b)."""
        v1 = a - b
        v2 = c - b
        n1 = float(np.linalg.norm(v1))
        n2 = float(np.linalg.norm(v2))
        if n1 < 1e-6 or n2 < 1e-6:
            return 180.0
        cosang = float(np.dot(v1, v2) / (n1 * n2))
        cosang = max(-1.0, min(1.0, cosang))
        return math.degrees(math.acos(cosang))

    def analyze(self, lm: np.ndarray) -> Dict[str, object]:
        """Return per-finger angle, curl%, extension flags and finger count."""
        xy = lm[:, :2]
        angles: List[float] = []
        for name in self.ORDER:
            a, b, c = self.JOINTS[name]
            angles.append(self._angle(xy[a], xy[b], xy[c]))

        # Map joint angle -> curl percent (180 deg straight = 0% curl).
        curls: List[float] = []
        for ang in angles:
            curl = (180.0 - ang) / 120.0 * 100.0
            curls.append(float(max(0.0, min(100.0, curl))))

        extended = [c < 45.0 for c in curls]
        fingers_up = sum(1 for e in extended if e)
        return {
            "angles": angles,
            "curls": curls,
            "extended": extended,
            "fingers_up": fingers_up,
        }


# ---------------------------------------------------------------------------
# Velocity Tracker
# ---------------------------------------------------------------------------
class VelocityTracker:
    """Tracks hand-centroid velocity in pixels/second using timestamps."""

    def __init__(self) -> None:
        self._prev_pos: Optional[np.ndarray] = None
        self._prev_t: Optional[float] = None
        self.speed: float = 0.0

    def update(self, centroid: np.ndarray, now: float) -> float:
        """Update and return the current smoothed speed (px/s)."""
        if self._prev_pos is not None and self._prev_t is not None:
            dt = now - self._prev_t
            if dt > 1e-3:
                inst = float(np.linalg.norm(centroid - self._prev_pos) / dt)
                self.speed = self.speed * 0.7 + inst * 0.3
        self._prev_pos = centroid
        self._prev_t = now
        return self.speed

    def reset(self) -> None:
        """Clear velocity history when the hand is lost."""
        self._prev_pos = None
        self._prev_t = None
        self.speed = 0.0


# ---------------------------------------------------------------------------
# Gesture Recognizer
# ---------------------------------------------------------------------------
class GestureRecognizer:
    """Classifies discrete gestures and enforces a re-trigger cooldown."""

    # Gesture name -> protocol id understood by the Arduino.
    IDS: Dict[str, int] = {
        "Fist": 1,
        "Open Hand": 2,
        "Thumbs Up": 3,
        "Thumbs Down": 4,
        "One Finger": 5,
        "Hang Loose": 6,
    }

    def __init__(self, cooldown: float = 1.2) -> None:
        self.cooldown = cooldown
        self._last_name: Optional[str] = None
        self._last_fire_t = 0.0
        self.counts: Dict[str, int] = {k: 0 for k in self.IDS}
        self.current: str = "-"

    def classify(self, lm: np.ndarray, extended: List[bool]) -> str:
        """Return the gesture name for the current frame (or '-')."""
        thumb, index, middle, ring, pinky = extended
        xy = lm[:, :2]
        wrist_y = xy[0][1]
        thumb_tip_y = xy[4][1]

        if not any(extended):
            name = "Fist"
        elif all(extended):
            name = "Open Hand"
        elif thumb and not index and not middle and not ring and not pinky:
            # Thumb only: up vs down by tip position relative to wrist.
            name = "Thumbs Up" if thumb_tip_y < wrist_y else "Thumbs Down"
        elif index and not thumb and not middle and not ring and not pinky:
            name = "One Finger"
        elif thumb and pinky and not index and not middle and not ring:
            name = "Hang Loose"
        else:
            name = "-"
        self.current = name
        return name

    def maybe_fire(self, name: str, now: float) -> Optional[int]:
        """Return the protocol id to send if a new gesture should trigger."""
        if name == "-" or name not in self.IDS:
            self._last_name = name
            return None
        if name == self._last_name and (now - self._last_fire_t) < self.cooldown:
            return None
        if (now - self._last_fire_t) < self.cooldown:
            return None
        self._last_name = name
        self._last_fire_t = now
        self.counts[name] += 1
        return self.IDS[name]


# ---------------------------------------------------------------------------
# Hand Overlay Drawer (kept from original, lightly hardened)
# ---------------------------------------------------------------------------
class HandOverlayDrawer:
    """Renders a small schematic 3D-style hand overlay in the corner.

    The original drawing logic is preserved; only bounds checking and the
    array interface were hardened.
    """

    PALM_INDICES: List[int] = [0, 1, 5, 9, 13, 17]
    FINGER_CHAIN: List[List[int]] = [
        [0, 1, 2, 3, 4],
        [5, 6, 7, 8],
        [9, 10, 11, 12],
        [13, 14, 15, 16],
        [17, 18, 19, 20],
    ]
    FINGER_COLORS: List[Tuple[int, int, int]] = [
        (255, 0, 0),
        (0, 255, 0),
        (0, 0, 255),
        (255, 255, 0),
        (0, 255, 255),
    ]

    def draw(
        self,
        image: np.ndarray,
        lm_px: np.ndarray,
        overlay_size: Tuple[int, int] = (160, 160),
        margin: int = 10,
    ) -> np.ndarray:
        """Blend the schematic hand overlay into the bottom-right corner."""
        if lm_px is None or len(lm_px) < 21:
            return image

        h_ov, w_ov = overlay_size
        img_h, img_w = image.shape[:2]
        if img_h < h_ov + margin or img_w < w_ov + margin:
            return image

        canvas = np.zeros((h_ov, w_ov, 3), dtype=np.uint8)

        def to_ov(idx: int) -> Tuple[int, int]:
            return (
                int(lm_px[idx][0] / img_w * w_ov),
                int(lm_px[idx][1] / img_h * h_ov),
            )

        try:
            palm_pts = np.array([to_ov(i) for i in self.PALM_INDICES], np.int32)
            cv2.fillPoly(canvas, [palm_pts], (50, 50, 50))
            cv2.polylines(canvas, [palm_pts], True, (0, 255, 255), 2)
        except Exception:  # noqa: BLE001
            pass

        for f_idx, chain in enumerate(self.FINGER_CHAIN):
            color = self.FINGER_COLORS[f_idx]
            for i in range(len(chain) - 1):
                cv2.line(
                    canvas, to_ov(chain[i]), to_ov(chain[i + 1]),
                    color, max(1, 4 - i), cv2.LINE_AA,
                )

        for idx in range(len(lm_px)):
            cv2.circle(canvas, to_ov(idx), 3, (255, 255, 255), -1)

        roi = image[-h_ov - margin:-margin, -w_ov - margin:-margin]
        gray = cv2.cvtColor(canvas, cv2.COLOR_BGR2GRAY)
        _, mask = cv2.threshold(gray, 10, 255, cv2.THRESH_BINARY)
        mask_inv = cv2.bitwise_not(mask)
        blended = cv2.add(
            cv2.bitwise_and(roi, roi, mask=mask_inv),
            cv2.bitwise_and(canvas, canvas, mask=mask),
        )
        image[-h_ov - margin:-margin, -w_ov - margin:-margin] = blended
        return image


# ---------------------------------------------------------------------------
# Glow & Trail Renderer (new visual effects)
# ---------------------------------------------------------------------------
class GlowTrailRenderer:
    """Adds a soft glow around joints and a fading motion trail."""

    FINGER_COLORS: List[Tuple[int, int, int]] = [
        (80, 80, 255),
        (80, 255, 80),
        (255, 180, 60),
        (255, 80, 220),
        (60, 220, 255),
    ]
    CHAINS: List[List[int]] = HandOverlayDrawer.FINGER_CHAIN

    def __init__(self, cfg: RenderConfig) -> None:
        self.cfg = cfg
        self._trail: Deque[Tuple[int, int]] = deque(maxlen=cfg.trail_length)

    def reset(self) -> None:
        """Clear the trail when the hand disappears."""
        self._trail.clear()

    def add_point(self, point: Tuple[int, int]) -> None:
        """Append a centroid sample to the motion trail."""
        self._trail.append(point)

    def draw_trail(self, image: np.ndarray) -> None:
        """Render the fading motion trail behind the hand."""
        if not self.cfg.trail or len(self._trail) < 2:
            return
        n = len(self._trail)
        for i in range(1, n):
            alpha = i / n
            color = (int(60 * alpha), int(200 * alpha), int(255 * alpha))
            cv2.line(
                image, self._trail[i - 1], self._trail[i],
                color, max(1, int(6 * alpha)), cv2.LINE_AA,
            )

    def draw_hand(self, image: np.ndarray, lm_px: np.ndarray) -> None:
        """Render gradient fingers with dynamic thickness and joint glow."""
        for f_idx, chain in enumerate(self.CHAINS):
            base = self.FINGER_COLORS[f_idx]
            for i in range(len(chain) - 1):
                p1 = (int(lm_px[chain[i]][0]), int(lm_px[chain[i]][1]))
                p2 = (int(lm_px[chain[i + 1]][0]), int(lm_px[chain[i + 1]][1]))
                thickness = max(1, 5 - i)
                cv2.line(image, p1, p2, base, thickness, cv2.LINE_AA)

        if self.cfg.glow:
            for idx in range(len(lm_px)):
                center = (int(lm_px[idx][0]), int(lm_px[idx][1]))
                cv2.circle(image, center, 8, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.circle(image, center, 4, (255, 255, 255), -1, cv2.LINE_AA)


# ---------------------------------------------------------------------------
# HUD Renderer
# ---------------------------------------------------------------------------
class HUDRenderer:
    """Draws the professional heads-up display and per-finger bars."""

    FINGER_NAMES: List[str] = ["Thumb", "Index", "Middle", "Ring", "Pinky"]

    def draw(
        self,
        frame: np.ndarray,
        fps: float,
        label: str,
        fingers_up: int,
        gesture: str,
        curls: Optional[List[float]],
        speed: float,
        arduino_connected: bool,
        gesture_total: int,
        mode: str,
    ) -> None:
        """Render the full HUD onto the frame in-place."""
        h, w = frame.shape[:2]

        # Top info panel
        cv2.rectangle(frame, (0, 0), (w, 70), (20, 20, 20), -1)
        cv2.putText(frame, f"FPS: {int(fps)}", (10, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
        cv2.putText(frame, f"Hand: {label}", (130, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.putText(frame, f"Fingers: {fingers_up}", (300, 28),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
        cv2.putText(frame, f"Gesture: {gesture}", (10, 56),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 200, 0), 2)
        cv2.putText(frame, f"Speed: {int(speed)} px/s", (300, 56),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (200, 200, 255), 2)

        # Arduino status light
        color = (0, 200, 0) if arduino_connected else (0, 0, 220)
        status = "ARDUINO OK" if arduino_connected else "ARDUINO OFF"
        cv2.circle(frame, (w - 180, 20), 9, color, -1)
        cv2.putText(frame, status, (w - 160, 26),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2)
        cv2.putText(frame, f"Gestures: {gesture_total}", (w - 180, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(frame, f"Mode: {mode}", (w - 320, 52),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 255, 180), 1)

        # Per-finger curl bars (bottom-left)
        if curls:
            bar_x, bar_y = 10, h - 130
            for i, curl in enumerate(curls):
                y = bar_y + i * 22
                cv2.putText(frame, self.FINGER_NAMES[i][:3], (bar_x, y + 12),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)
                x0 = bar_x + 45
                cv2.rectangle(frame, (x0, y), (x0 + 160, y + 14), (60, 60, 60), -1)
                fill = int(160 * curl / 100.0)
                bar_col = (0, 255, 0) if curl < 50 else (0, 165, 255)
                cv2.rectangle(frame, (x0, y), (x0 + fill, y + 14), bar_col, -1)


# ---------------------------------------------------------------------------
# Face & Pose Tracker (optional, lightweight)
# ---------------------------------------------------------------------------
class FacePoseTracker:
    """Optional face-mesh tracker. Disabled by default to save CPU."""

    def __init__(self, max_faces: int = 2) -> None:
        self._mp_face = mp.solutions.face_mesh
        self.face_mesh = self._mp_face.FaceMesh(
            max_num_faces=max_faces, refine_landmarks=False
        )

    def process(self, img: np.ndarray):
        """Return the list of detected face landmark sets."""
        try:
            rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            res = self.face_mesh.process(rgb)
            return res.multi_face_landmarks or []
        except Exception:  # noqa: BLE001
            return []

    def draw_face(self, frame: np.ndarray, face, color) -> None:
        """Draw a sparse subset of face landmarks for low CPU cost."""
        try:
            h, w = frame.shape[:2]
            for lm in face.landmark[::8]:  # every 8th point keeps it light
                cv2.circle(frame, (int(lm.x * w), int(lm.y * h)), 1, color, -1)
        except Exception:  # noqa: BLE001
            pass

    def close(self) -> None:
        """Release the face-mesh model."""
        try:
            self.face_mesh.close()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Video Stream (threaded, with watchdog)
# ---------------------------------------------------------------------------
class VideoStream:
    """Threaded camera reader with a watchdog that reopens a dead device."""

    def __init__(self, cfg: CameraConfig) -> None:
        self.cfg = cfg
        self._frame: Optional[np.ndarray] = None
        self._stopped = False
        self._lock = threading.Lock()
        self._last_frame_t = time.time()
        self._cap = self._open_capture()

    def _open_capture(self) -> cv2.VideoCapture:
        """Open the capture device with a Windows-friendly backend."""
        backend = cv2.CAP_DSHOW if platform.system() == "Windows" else cv2.CAP_ANY
        cap = cv2.VideoCapture(self.cfg.index, backend)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.cfg.width)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.cfg.height)
        cap.set(cv2.CAP_PROP_FPS, self.cfg.fps)
        if not cap.isOpened():
            logger.error("CRITICAL: camera index %s unreachable.", self.cfg.index)
        return cap

    def start(self) -> "VideoStream":
        """Start the background capture thread."""
        if self._cap.isOpened():
            threading.Thread(target=self._update, daemon=True).start()
            logger.info("VideoStream thread started.")
        return self

    def _update(self) -> None:
        """Continuously grab frames; reopen the device if it stalls."""
        while not self._stopped:
            if not self._cap.isOpened():
                self._reopen()
                continue
            ret, frame = self._cap.read()
            if not ret:
                if time.time() - self._last_frame_t > self.cfg.watchdog_timeout:
                    logger.warning("Watchdog: camera stalled - reopening.")
                    self._reopen()
                time.sleep(0.005)
                continue
            with self._lock:
                self._frame = frame
                self._last_frame_t = time.time()

    def _reopen(self) -> None:
        """Release and reopen the camera (watchdog recovery)."""
        try:
            self._cap.release()
        except Exception:  # noqa: BLE001
            pass
        time.sleep(0.5)
        self._cap = self._open_capture()
        self._last_frame_t = time.time()

    def read(self) -> Optional[np.ndarray]:
        """Return a copy of the most recent frame, or None."""
        with self._lock:
            return self._frame.copy() if self._frame is not None else None

    def stop(self) -> None:
        """Stop the thread and release the device."""
        self._stopped = True
        time.sleep(0.05)
        with self._lock:
            try:
                if self._cap.isOpened():
                    self._cap.release()
            except Exception:  # noqa: BLE001
                pass
        logger.info("VideoStream resources released.")


# ---------------------------------------------------------------------------
# Keyboard Controller (manual override + demo mode)
# ---------------------------------------------------------------------------
class KeyboardController:
    """Maps key presses to manual LED overrides and demo mode toggling."""

    def __init__(self) -> None:
        self.manual: bool = False
        self.demo: bool = False
        self.manual_values: List[int] = [0, 0, 0, 0, 0]
        self._demo_phase = 0.0

    def handle(self, key: int) -> bool:
        """Process a key; return False if the app should quit."""
        if key in (27, ord("q")):  # ESC or q
            return False
        if key == ord("m"):
            self.manual = not self.manual
            self.demo = False
            logger.info("Manual override: %s", self.manual)
        elif key == ord("d"):
            self.demo = not self.demo
            self.manual = False
            logger.info("Demo mode: %s", self.demo)
        elif key in (ord("1"), ord("2"), ord("3"), ord("4"), ord("5")):
            idx = key - ord("1")
            self.manual = True
            self.demo = False
            self.manual_values[idx] = 0 if self.manual_values[idx] else 180
            logger.info("Manual LED%d -> %d", idx + 1, self.manual_values[idx])
        elif key == ord("0"):
            self.manual_values = [0, 0, 0, 0, 0]
        return True

    def demo_frame(self, dt: float) -> List[int]:
        """Generate an automatic sweeping demo pattern (angles 0..180)."""
        self._demo_phase += dt * 2.0
        vals: List[int] = []
        for i in range(5):
            v = (math.sin(self._demo_phase + i * 0.9) + 1.0) * 0.5 * 180.0
            vals.append(int(v))
        return vals

    @property
    def mode(self) -> str:
        """Human-readable current control mode for the HUD."""
        if self.demo:
            return "DEMO"
        if self.manual:
            return "MANUAL"
        return "AUTO"


# ---------------------------------------------------------------------------
# Main Application
# ---------------------------------------------------------------------------
class HandArduinoApp:
    """Orchestrates capture, vision, gesture logic, rendering and serial I/O."""

    def __init__(self, config: AppConfig) -> None:
        self.cfg = config
        self._executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

        self.detector = HandDetector(config.vision)
        self.analyzer = FingerAnalyzer()
        self.velocity = VelocityTracker()
        self.gestures = GestureRecognizer(config.serial.gesture_cooldown)
        self.kalman = LandmarkKalman(21, config.filt)
        self.overlay = HandOverlayDrawer()
        self.fx = GlowTrailRenderer(config.render)
        self.hud = HUDRenderer()
        self.keyboard = KeyboardController()
        self.arduino = ArduinoClient(config.serial, executor=self._executor)

        self.face_pose: Optional[FacePoseTracker] = (
            FacePoseTracker() if config.vision.enable_face_pose else None
        )

        self._running = False
        self._stream: Optional[VideoStream] = None
        self._frame_counter = 0
        self._cached_faces: list = []

        self._fps = 0.0
        self._prev_frame_t = 0.0

        # Serial scheduling state
        self._pending_data: Optional[str] = None
        self._gesture_queue: "asyncio.Queue[str]" = asyncio.Queue(maxsize=8)
        self._gesture_until = 0.0
        self._idle_sent = False

    # -- serial scheduling ---------------------------------------------------
    def _queue_gesture(self, gid: int) -> None:
        """Enqueue a gesture command (drop if the queue is saturated)."""
        try:
            self._gesture_queue.put_nowait(SerialProtocol.gesture(gid))
        except asyncio.QueueFull:
            pass

    async def _serial_worker(self) -> None:
        """Send gesture commands immediately and data frames at a fixed rate."""
        interval = 1.0 / max(1, self.cfg.serial.send_rate_hz)
        while self._running:
            now = time.time()
            # Gestures have priority.
            try:
                cmd = self._gesture_queue.get_nowait()
            except asyncio.QueueEmpty:
                cmd = None
            if cmd is not None:
                await self.arduino.write(cmd)
                self._gesture_until = now + self.cfg.serial.gesture_cooldown
                await asyncio.sleep(interval)
                continue
            # Pause data while a gesture animation plays on the Arduino.
            if now < self._gesture_until:
                await asyncio.sleep(interval)
                continue
            if self._pending_data is not None:
                await self.arduino.write(self._pending_data)
                self._pending_data = None
            await asyncio.sleep(interval)

    # -- lifecycle -----------------------------------------------------------
    async def start(self) -> None:
        """Open devices and run the main processing loop until quit."""
        self.arduino.open()
        logger.info("Starting video stream...")
        self._stream = VideoStream(self.cfg.camera).start()
        await asyncio.sleep(1.0)

        self._running = True
        serial_task = asyncio.create_task(self._serial_worker())
        last_hand_t = time.time()
        fps_interval = 1.0 / max(1, self.cfg.camera.fps)

        try:
            cv2.namedWindow(self.cfg.window_name, cv2.WINDOW_NORMAL)
            cv2.resizeWindow(
                self.cfg.window_name, self.cfg.camera.width, self.cfg.camera.height
            )

            while self._running:
                loop_start = time.time()
                frame = self._stream.read()
                if frame is None:
                    await asyncio.sleep(0.01)
                    continue

                # FPS estimate
                if self._prev_frame_t:
                    dt = loop_start - self._prev_frame_t
                    if dt > 0:
                        self._fps = self._fps * 0.9 + (1.0 / dt) * 0.1
                self._prev_frame_t = loop_start

                frame = cv2.flip(frame, 1)
                self._frame_counter += 1

                lm_raw, label = self.detector.process(frame, already_flipped=True)
                curls: Optional[List[float]] = None
                fingers_up = 0

                if lm_raw is not None:
                    last_hand_t = loop_start
                    self._idle_sent = False

                    # Kalman-smooth the x,y pixel coordinates.
                    smoothed_xy = self.kalman.update(lm_raw[:, :2])
                    lm = lm_raw.copy()
                    lm[:, :2] = smoothed_xy

                    info = self.analyzer.analyze(lm)
                    curls = info["curls"]                       # type: ignore
                    extended = info["extended"]                 # type: ignore
                    fingers_up = info["fingers_up"]             # type: ignore

                    centroid = lm[:, :2].mean(axis=0)
                    self.velocity.update(centroid, loop_start)
                    self.fx.add_point((int(centroid[0]), int(centroid[1])))

                    # Gesture detection + firing
                    name = self.gestures.classify(lm, extended)
                    gid = self.gestures.maybe_fire(name, loop_start)
                    if gid is not None:
                        self._queue_gesture(gid)

                    # Decide LED data based on control mode.
                    if self.keyboard.demo:
                        angles = self.keyboard.demo_frame(fps_interval)
                    elif self.keyboard.manual:
                        angles = list(self.keyboard.manual_values)
                    else:
                        # Curl% (0..100) -> angle (0..180) for PWM brightness.
                        angles = [int(c / 100.0 * 180.0) for c in curls]
                    self._pending_data = SerialProtocol.data(angles)

                    # Visuals
                    self.fx.draw_trail(frame)
                    self.detector.draw(frame, lm, label or "Unknown")
                    self.fx.draw_hand(frame, lm)
                    frame = self.overlay.draw(
                        frame, lm,
                        overlay_size=self.cfg.render.overlay_size,
                        margin=self.cfg.render.overlay_margin,
                    )
                else:
                    # No hand: reset transient state.
                    self.kalman.reset()
                    self.velocity.reset()
                    self.fx.reset()
                    self.gestures.current = "-"
                    if self.keyboard.demo:
                        self._pending_data = SerialProtocol.data(
                            self.keyboard.demo_frame(fps_interval)
                        )
                    elif self.keyboard.manual:
                        self._pending_data = SerialProtocol.data(
                            self.keyboard.manual_values
                        )
                    elif self._idle_sent:
                        # Idle breathing already running on the Arduino: send
                        # nothing so we do not overwrite the animation.
                        self._pending_data = None
                    elif loop_start - last_hand_t >= self.cfg.idle_after:
                        # Trigger idle breathing once after the timeout.
                        await self._gesture_queue.put(SerialProtocol.idle())
                        self._idle_sent = True
                        self._pending_data = None
                    else:
                        # Hand recently lost: keep LEDs off until idle kicks in.
                        self._pending_data = SerialProtocol.off()

                # Optional, throttled face overlay.
                if self.face_pose is not None:
                    if self._frame_counter % self.cfg.vision.face_pose_every_n == 0:
                        self._cached_faces = self.face_pose.process(frame)
                    for face in self._cached_faces:
                        self.face_pose.draw_face(frame, face, (180, 180, 180))

                # HUD
                self.hud.draw(
                    frame,
                    fps=self._fps,
                    label=label or "-",
                    fingers_up=fingers_up,
                    gesture=self.gestures.current,
                    curls=curls,
                    speed=self.velocity.speed,
                    arduino_connected=self.arduino.connected,
                    gesture_total=sum(self.gestures.counts.values()),
                    mode=self.keyboard.mode,
                )

                cv2.imshow(self.cfg.window_name, frame)
                key = cv2.waitKey(1) & 0xFF
                if not self.keyboard.handle(key):
                    break

                await asyncio.sleep(
                    max(0.0, fps_interval - (time.time() - loop_start))
                )
        finally:
            serial_task.cancel()
            try:
                await serial_task
            except asyncio.CancelledError:
                pass
            await self._shutdown()

    # -- shutdown ------------------------------------------------------------
    async def _shutdown(self) -> None:
        """Release every resource gracefully."""
        self._running = False
        try:
            await self.arduino.write(SerialProtocol.off())
        except Exception:  # noqa: BLE001
            pass
        if self._stream:
            self._stream.stop()
        self.arduino.close()
        self.detector.close()
        if self.face_pose is not None:
            self.face_pose.close()
        try:
            cv2.destroyAllWindows()
        except Exception:  # noqa: BLE001
            pass
        self._executor.shutdown(wait=False)
        logger.info("System shutdown complete.")


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------
def main() -> None:
    """Application entry point."""
    cfg = AppConfig()
    app = HandArduinoApp(cfg)
    try:
        asyncio.run(app.start())
    except KeyboardInterrupt:
        logger.info("User interrupt - exiting.")


if __name__ == "__main__":
    main()


# ===========================================================================
# ARDUINO UNO WIRING DIAGRAM  (5 LEDs, 5 x 220 ohm resistors, 6 wires)
# ===========================================================================
#
#   LED #   Color (suggested)   Arduino PWM Pin   Finger
#   -----   -----------------   ---------------   ------
#   LED1    Red                 D3  (~)           Thumb
#   LED2    Green               D5  (~)           Index
#   LED3    Blue                D6  (~)           Middle
#   LED4    Yellow              D9  (~)           Ring
#   LED5    White               D10 (~)           Pinky
#
#   Each LED:  Arduino PWM pin --> [220 ohm resistor] --> LED anode (+)
#              LED cathode (-) --> common GND rail --> Arduino GND
#
#   Wiring (6 wires total): 5 signal wires (D3, D5, D6, D9, D10) + 1 GND wire
#   from the breadboard ground rail back to an Arduino GND pin.
#
#       D3  ---[220R]---|>|---+
#       D5  ---[220R]---|>|---+
#       D6  ---[220R]---|>|---+---> GND rail ---> Arduino GND
#       D9  ---[220R]---|>|---+
#       D10 ---[220R]---|>|---+
#
#   All pins D3, D5, D6, D9, D10 are hardware-PWM (~) capable on the Uno,
#   so each LED brightness is controlled independently via analogWrite().
# ===========================================================================
