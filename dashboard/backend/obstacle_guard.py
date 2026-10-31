"""Conservative 2D scan veto for dashboard commands; not a collision guarantee.

Distances are relative to base_scan. A conservative circular envelope covers the
Burger footprint and scanner offset; it must be physically validated before use.
Invalid/missing rays are unknown, never assumed to be free space.
"""
import math
import os
import threading
import time


class ObstacleGuard:
    def __init__(self, clock=time.monotonic, bypass=None):
        self.clock = clock
        self.bypassed = os.environ.get('TURTBOT_BYPASS_OBSTACLES') == '1' if bypass is None else bool(bypass)
        self.lock = threading.RLock()
        self.scan = None
        self.received = None
        self.max_age = .5
        self.envelope = float(os.environ.get("TURTBOT_STOP_ENVELOPE_M", ".30"))
        if not math.isfinite(self.envelope) or not .28 <= self.envelope <= .8:
            raise ValueError("Obstacle envelope must be between 0.28 and 0.8 m")

    def update(self, scan):
        with self.lock:
            self.scan = scan
            self.received = self.clock()

    def reason(self, linear, angular):
        if self.bypassed:
            return None
        return self.scan_reason(linear, angular)

    def scan_reason(self, linear, angular):
        with self.lock:
            if self.received is None or self.clock() - self.received > self.max_age:
                return 'LiDAR missing or older than 500 ms'
            s = self.scan
            if s.get('frame_id') != 'base_scan':
                return 'Unvalidated LiDAR frame; expected base_scan'
            ranges = s.get('ranges', [])
            step = s.get('angle_increment', 0)
            start = s.get('angle_min', 0)
            if not ranges or not all(math.isfinite(v) for v in (step, start)) or step == 0:
                return 'Invalid scan geometry'
            if not linear and not angular:
                return None
            if abs(angular) > 1e-6:
                selected = list(range(len(ranges)))  # turns sweep the full footprint
                required_span = math.tau
            else:
                heading = 0 if linear > 0 else math.pi
                half_width = math.radians(70)
                selected = [i for i in range(len(ranges))
                            if abs(math.atan2(math.sin(start+i*step-heading), math.cos(start+i*step-heading))) <= half_width]
                required_span = 2 * half_width
            if len(selected) * abs(step) < required_span * .95:
                return 'Incomplete scan coverage in the requested direction'
            limit = self.envelope + abs(linear) * .6 + linear * linear / .4
            valid = 0
            unknown_run = longest_unknown = 0
            flags = []
            for i in selected:
                distance = ranges[i]
                known = isinstance(distance, (int, float)) and math.isfinite(distance) and s['range_min'] <= distance <= s['range_max'] and distance > 0
                flags.append(known)
                if known:
                    valid += 1
                    unknown_run = 0
                    if distance <= limit:
                        return f'Obstacle inside {limit:.2f} m stop envelope'
                else:
                    unknown_run += 1
                    longest_unknown = max(longest_unknown, unknown_run)
            # selected order can wrap across 0 degrees; count endpoint unknown gaps too.
            prefix = next((i for i, flag in enumerate(flags) if flag), len(flags))
            suffix = next((i for i, flag in enumerate(reversed(flags)) if flag), len(flags))
            longest_unknown = max(longest_unknown, min(len(flags), prefix + suffix))
            if valid / max(1, len(selected)) < .85 or longest_unknown * abs(step) > math.radians(12):
                return 'Unknown or invalid LiDAR coverage in the requested direction'
            return None

    def state(self):
        with self.lock:
            directions = {'forward': self.scan_reason(.08, 0), 'reverse': self.scan_reason(-.08, 0), 'turn': self.scan_reason(0, .5)}
            age = None if self.received is None else self.clock() - self.received
            return {'status': 'bypassed' if self.bypassed else 'monitoring' if any(v is None for v in directions.values()) else 'blocked',
                    'bypassed': self.bypassed,
                    'directions': directions, 'scan_age_s': age, 'stop_envelope_m': self.envelope,
                    'max_scan_age_ms': 500, 'validated_on_robot': False,
                    'limitation': '2D scan plane only; cannot detect cliffs or obstacles above/below the scan. Physical stopping is unvalidated.'}
