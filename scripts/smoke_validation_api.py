"""验证 API 与看板冒烟测试（不重跑验证，只读已存结果）。"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402


def main() -> int:
    client = TestClient(app)
    failures = []

    r = client.get("/api/validations?limit=5")
    print(f"GET /api/validations -> {r.status_code}")
    if r.status_code != 200:
        failures.append("/api/validations")
        items = []
    else:
        items = r.json().get("items", [])

    if items:
        vid = items[0]["validation_id"]
        r2 = client.get(f"/api/validations/{vid}")
        print(f"GET /api/validations/{vid} -> {r2.status_code}")
        if r2.status_code != 200:
            failures.append("detail")
        else:
            payload = r2.json()
            print(f"  windows={len(payload.get('windows', []))} "
                  f"grid={len(payload.get('grid', []))} "
                  f"stress={len(payload.get('stress', []))} "
                  f"conclusion={payload.get('conclusion')}")

    r3 = client.get("/api/validations/not_exist")
    print(f"GET /api/validations/not_exist -> {r3.status_code} (期望 404)")
    if r3.status_code != 404:
        failures.append("404")

    print()
    print("SMOKE_FAILED:", failures if failures else "无")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
