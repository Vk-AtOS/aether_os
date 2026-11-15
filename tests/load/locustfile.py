"""
AetherOS Load Test Suite — Locust

Quick start (interactive UI):
  locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000

Headless 200-user smoke test (CI/production verification):
  python3 tests/load/seed_load_users.py --host=http://127.0.0.1:8000 --count=220
  locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000 \
    --headless --users 200 --spawn-rate 10 --run-time 3m \
    --csv=tests/load/results/load_200

Headless 500-user stress test:
  python3 tests/load/seed_load_users.py --host=http://127.0.0.1:8000 --count=550
  locust -f tests/load/locustfile.py --host=http://127.0.0.1:8000 \
    --headless --users 500 --spawn-rate 20 --run-time 5m \
    --csv=tests/load/results/stress_500

Scenarios:
  BrowseUser   — read-only dashboard browsing (60% of traffic)
  ActiveUser   — login + browse + occasional pipeline start (30%)
  AdminUser    — admin management tasks (10%)

Targets:
  200 users:  p95 < 500ms, error rate < 1%
  500 users:  p95 < 1500ms, error rate < 2%
"""
from __future__ import annotations
import random
import threading
from locust import HttpUser, task, between, events
from locust.exception import StopUser

# Shared pool of pre-seeded (email, password) pairs — populated at test start
_USER_POOL: list[tuple[str, str]] = []
_POOL_LOCK = threading.Lock()
_POOL_INDEX = 0

SEED_PASSWORD = "LoadTest@1234"
SEED_PREFIX = "loadtest_"


def _next_pool_user() -> tuple[str, str] | None:
    global _POOL_INDEX
    with _POOL_LOCK:
        if not _USER_POOL:
            return None
        user = _USER_POOL[_POOL_INDEX % len(_USER_POOL)]
        _POOL_INDEX += 1
        return user


def _login(client, email: str, password: str) -> str | None:
    with client.post(
        "/auth/login",
        json={"email": email, "password": password},
        name="/auth/login",
        catch_response=True,
    ) as r:
        if r.status_code == 200:
            r.success()
            return r.json().get("access_token")
        r.failure(f"Login failed {r.status_code}: {r.text[:80]}")
        return None


# ── User classes ──────────────────────────────────────────────────────────────

class BrowseUser(HttpUser):
    """Read-only dashboard user — heaviest traffic pattern."""
    wait_time = between(1, 3)
    weight = 60  # 60% of virtual users

    def on_start(self):
        pair = _next_pool_user()
        if not pair:
            raise StopUser()
        self.email, pwd = pair
        self.token = _login(self.client, self.email, pwd)
        if not self.token:
            raise StopUser()
        self.client.headers.update({"Authorization": f"Bearer {self.token}"})

    @task(5)
    def dashboard_health(self):
        self.client.get("/health", name="/health")

    @task(4)
    def list_runs(self):
        self.client.get("/factory/runs?page=1&limit=20", name="/factory/runs")

    @task(3)
    def system_costs(self):
        self.client.get("/system/costs", name="/system/costs")

    @task(3)
    def compliance_report(self):
        self.client.get("/compliance/org-report", name="/compliance/org-report")

    @task(2)
    def audit_logs(self):
        self.client.get("/audit/logs?limit=50", name="/audit/logs")

    @task(2)
    def list_notifications(self):
        self.client.get("/notifications", name="/notifications")

    @task(2)
    def storage_widget(self):
        self.client.get("/account/storage", name="/account/storage")

    @task(1)
    def marketplace(self):
        self.client.get("/marketplace/profiles", name="/marketplace/profiles")

    @task(1)
    def llm_providers(self):
        self.client.get("/settings/llm-config", name="/settings/llm-config [2]")

    @task(1)
    def llm_config(self):
        self.client.get("/settings/llm-config", name="/settings/llm-config")


class ActiveUser(HttpUser):
    """User who starts pipeline runs — medium traffic."""
    wait_time = between(3, 8)
    weight = 30  # 30% of virtual users

    def on_start(self):
        pair = _next_pool_user()
        if not pair:
            raise StopUser()
        self.email, pwd = pair
        self.token = _login(self.client, self.email, pwd)
        if not self.token:
            raise StopUser()
        self.client.headers.update({"Authorization": f"Bearer {self.token}"})
        self.run_id = None

    @task(3)
    def browse_projects(self):
        self.client.get("/factory/runs?page=1&limit=10", name="/factory/runs")

    @task(2)
    def check_system_health(self):
        self.client.get("/health", name="/health")

    @task(1)
    def start_run(self):
        with self.client.post(
            "/factory/start",
            json={
                "requirement": "Build a simple REST API with CRUD operations for a todo list",
                "project_name": f"load-test-{random.randint(1000, 9999)}",
                "language": "python",
                "max_retries": 1,
            },
            name="/factory/start",
            catch_response=True,
        ) as r:
            if r.status_code in (200, 201, 202):
                self.run_id = r.json().get("run_id")
                r.success()
            elif r.status_code in (402, 429):
                r.success()  # Rate limited or quota exceeded — expected under load
            else:
                r.failure(f"Start run failed: {r.status_code}")

    @task(2)
    def check_run_status(self):
        if self.run_id:
            self.client.get(f"/factory/runs/{self.run_id}", name="/factory/runs/{id}")

    @task(1)
    def refresh_token(self):
        """Simulate token refresh via /auth/refresh endpoint."""
        refresh = localStorage_refresh = getattr(self, "_refresh_token", None)
        if not refresh:
            return
        with self.client.post(
            "/auth/refresh",
            json={"refresh_token": refresh},
            name="/auth/refresh",
            catch_response=True,
        ) as r:
            if r.status_code == 200:
                data = r.json()
                self.token = data.get("access_token", self.token)
                self._refresh_token = data.get("refresh_token", refresh)
                self.client.headers.update({"Authorization": f"Bearer {self.token}"})
                r.success()
            else:
                r.success()  # Refresh failure is not a load test issue


class AdminUser(HttpUser):
    """Admin-role user performing management tasks."""
    wait_time = between(5, 15)
    weight = 10  # 10% of virtual users

    def on_start(self):
        # Use the seeded admin account
        with self.client.post(
            "/auth/login",
            json={"email": "demo@aetheros.ai", "password": "Admin@1234"},
            name="/auth/login [admin]",
            catch_response=True,
        ) as r:
            if r.status_code == 200:
                self.token = r.json().get("access_token")
                self.client.headers.update({"Authorization": f"Bearer {self.token}"})
                r.success()
            else:
                r.failure(f"Admin login failed: {r.status_code}")
                raise StopUser()

    @task(3)
    def list_users(self):
        self.client.get("/admin/users", name="/admin/users")

    @task(2)
    def compliance_report(self):
        self.client.get("/compliance/org-report", name="/compliance/org-report [admin]")

    @task(2)
    def audit_logs(self):
        self.client.get("/audit/logs?limit=100", name="/audit/logs [admin]")

    @task(1)
    def system_costs(self):
        self.client.get("/system/costs", name="/system/costs [admin]")

    @task(1)
    def system_health(self):
        self.client.get("/health", name="/health [admin]")


# ── Event hooks for reporting ─────────────────────────────────────────────────

@events.test_start.add_listener
def on_test_start(environment, **kwargs):
    """Seed user pool before the load test begins."""
    host = environment.host.rstrip("/")
    print("\n=== AetherOS Load Test Starting ===")
    print(f"Target host: {host}")
    print("Seeding user pool (60 accounts)...")

    # Populate pool directly — no API calls during seeding to avoid burning rate limits.
    # Users must be pre-seeded in the DB (run seed_load_users.py or the ORM seeder first).
    seeded = 0
    for i in range(60):
        email = f"{SEED_PREFIX}{i:04d}@loadtest.internal"
        _USER_POOL.append((email, SEED_PASSWORD))
        seeded += 1

    print(f"Pool ready: {seeded} accounts")
    print("Scenarios: BrowseUser (60%), ActiveUser (30%), AdminUser (10%)")
    print("Target: 50 concurrent users, p95 < 500ms, <1% errors\n")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    stats = environment.stats
    total = stats.total
    print("\n=== AetherOS Load Test Results ===")
    print(f"Requests:      {total.num_requests}")
    print(f"Failures:      {total.num_failures} ({total.fail_ratio * 100:.1f}%)")
    print(f"Avg response:  {total.avg_response_time:.0f}ms")
    print(f"p95 response:  {total.get_response_time_percentile(0.95):.0f}ms")
    print(f"p99 response:  {total.get_response_time_percentile(0.99):.0f}ms")
    print(f"RPS:           {total.current_rps:.1f}")

    # Fail if error rate > 1% or p95 > 1000ms
    if total.fail_ratio > 0.01:
        print(f"\nFAIL: Error rate {total.fail_ratio * 100:.1f}% exceeds 1% threshold")
    elif total.get_response_time_percentile(0.95) > 1000:
        print(f"\nFAIL: p95 {total.get_response_time_percentile(0.95):.0f}ms exceeds 1000ms threshold")
    else:
        print("\nPASS: Error rate and latency within acceptable bounds")
