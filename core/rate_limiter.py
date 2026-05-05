import time
import os
from collections import defaultdict
from typing import Dict, List, Optional

class RateLimiter:
    def __init__(self):
        self.max_concurrent_runs = int(os.environ.get("MAX_CONCURRENT_RUNS_PER_ORG", 5))
        self.max_starts_per_hour = int(os.environ.get("MAX_STARTS_PER_ORG_PER_HOUR", 20))
        self.max_login_attempts = int(os.environ.get("MAX_LOGIN_ATTEMPTS_PER_IP", 20))
        self.max_registrations = int(os.environ.get("MAX_REGISTRATIONS_PER_IP", 5))
        
        # storage
        self.active_runs = defaultdict(int) # org_id -> count
        self.hourly_starts = defaultdict(list) # org_id -> [timestamps]
        self.login_attempts = defaultdict(list) # ip -> [timestamps]
        self.registrations = defaultdict(list) # ip -> [timestamps]

    def check_concurrent_runs(self, org_id: str) -> bool:
        return self.active_runs[org_id] < self.max_concurrent_runs

    def check_hourly_starts(self, org_id: str) -> bool:
        now = time.time()
        self.hourly_starts[org_id] = [t for t in self.hourly_starts[org_id] if now - t < 3600]
        return len(self.hourly_starts[org_id]) < self.max_starts_per_hour

    def check_login_attempts(self, ip: str) -> bool:
        now = time.time()
        self.login_attempts[ip] = [t for t in self.login_attempts[ip] if now - t < 900]
        return len(self.login_attempts[ip]) < self.max_login_attempts

    def check_registration_attempts(self, ip: str) -> bool:
        now = time.time()
        self.registrations[ip] = [t for t in self.registrations[ip] if now - t < 3600]
        return len(self.registrations[ip]) < self.max_registrations

    def record_run_start(self, org_id: str):
        self.active_runs[org_id] += 1
        self.hourly_starts[org_id].append(time.time())

    def record_run_end(self, org_id: str):
        if self.active_runs[org_id] > 0:
            self.active_runs[org_id] -= 1

    def record_login_attempt(self, ip: str):
        self.login_attempts[ip].append(time.time())

    def record_registration_attempt(self, ip: str):
        self.registrations[ip].append(time.time())

_instance: Optional[RateLimiter] = None

def get_rate_limiter() -> RateLimiter:
    global _instance
    if _instance is None:
        _instance = RateLimiter()
    return _instance
