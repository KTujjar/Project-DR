"""Server-side command ownership and deadman policy; no ROS dependencies."""
import math
import threading
import time


class ControlDenied(ValueError):
    pass


class SafetyController:
    def __init__(self, enabled=False, publish=None, prepare=None, release=None, conflicts=None, guard=None, clock=time.monotonic):
        self.enabled = enabled
        self.publish = publish or (lambda linear, angular: None)
        self.prepare = prepare or (lambda: None)
        self.release = release or (lambda: None)
        self.conflicts = conflicts or (lambda: 0)
        self.guard = guard
        self.clock = clock
        self.lock = threading.RLock()
        self.owner = None
        self.linear = self.angular = 0.0
        self.target_linear = self.target_angular = 0.0
        self.ramp_time = self.clock()
        self.last_heartbeat = self.last_command = 0.0
        self.reason = "Motion locked: initial physical validation is incomplete" if not enabled else "Disarmed"

    def state(self):
        with self.lock:
            return {"enabled": self.enabled, "armed": self.owner is not None,
                    "linear": self.linear, "angular": self.angular, "reason": self.reason,
                    "command_timeout_ms": 250, "heartbeat_timeout_ms": 600,
                    "max_linear": 0.08, "max_angular": 0.5,
                    "target_linear": self.target_linear, "target_angular": self.target_angular,
                    "linear_acceleration": 0.12, "angular_acceleration": 0.8,
                    "obstacle_guard": self.guard.state() if self.guard else {"status": "unavailable"}}

    def arm(self, owner):
        with self.lock:
            if not self.enabled:
                raise ControlDenied("Movement is disabled on this server")
            if self.owner and self.owner != owner:
                raise ControlDenied("Another browser owns the control lease")
            if self.conflicts():
                raise ControlDenied("Another /cmd_vel publisher is active")
            if self.guard:
                reason = self.guard.reason(0, 0)
                if reason:
                    raise ControlDenied("Obstacle guard: " + reason)
            self.prepare()
            self.owner = owner
            self.ramp_time = self.clock()
            self.last_heartbeat = self.last_command = self.clock()
            self.reason = "Armed; hold a direction to drive"

    def heartbeat(self, owner):
        with self.lock:
            if self.owner == owner:
                self.last_heartbeat = self.clock()

    def command(self, owner, linear, angular):
        with self.lock:
            if not self.enabled or self.owner != owner:
                raise ControlDenied("Arm this browser before driving")
            if self.clock() - self.last_heartbeat > 0.6:
                self.disarm("Browser heartbeat expired")
                raise ControlDenied("Control lease expired")
            if not all(math.isfinite(value) for value in (linear, angular)):
                raise ControlDenied("Velocity values must be finite")
            if self.conflicts():
                self.disarm("Competing motor publisher detected")
                raise ControlDenied(self.reason)
            self.target_linear = max(-0.08, min(0.08, linear))
            self.target_angular = max(-0.5, min(0.5, angular))
            if self.guard:
                reason = self.guard.reason(self.linear, self.angular) or self.guard.reason(self.target_linear, self.target_angular)
                if reason:
                    self.disarm("Obstacle guard: " + reason)
                    raise ControlDenied(self.reason)
            self.last_command = self.clock()
            if not self.target_linear and not self.target_angular:
                self.stop("Zero command")
            else:
                self.advance()

    def advance(self):
        elapsed = max(0., min(.1, self.clock()-self.ramp_time))
        self.ramp_time = self.clock()
        def step(current, target, acceleration):
            limit=acceleration*elapsed
            return current+max(-limit,min(limit,target-current))
        self.linear=step(self.linear,self.target_linear,.12)
        self.angular=step(self.angular,self.target_angular,.8)
        self.publish(self.linear,self.angular)

    def stop(self, reason="Direction released"):
        with self.lock:
            if self.owner is not None:
                self.publish(0.0, 0.0)
            self.linear = self.angular = self.target_linear = self.target_angular = 0.0
            self.ramp_time = self.clock()
            self.reason = reason

    def disarm(self, reason="Disarmed"):
        with self.lock:
            try:
                self.stop(reason)
            finally:
                self.owner = None
                self.release()

    def disconnect(self, owner):
        with self.lock:
            if self.owner == owner:
                self.disarm("Browser connection lost")

    def tick(self):
        with self.lock:
            if self.owner is None:
                return
            if self.guard and (reason := (self.guard.reason(self.linear, self.angular) or self.guard.reason(self.target_linear, self.target_angular))):
                self.disarm("Obstacle guard: " + reason)
            elif self.conflicts():
                self.disarm("Competing motor publisher detected")
            elif self.clock() - self.last_heartbeat > 0.6:
                self.disarm("Browser heartbeat expired")
            elif (self.target_linear or self.target_angular) and self.clock() - self.last_command > 0.25:
                self.disarm("Command deadman timeout")
            elif self.target_linear or self.target_angular:
                self.advance()
