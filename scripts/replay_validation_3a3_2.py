"""阶段3A.3.2：用修复后的账本重新执行完整验证流程，生成新的 validation_id。

不覆盖旧记录：run_validation() 每次生成新 ID，旧记录完整保留。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.validation.config import ValidationConfig  # noqa: E402
from app.validation.fingerprint import fingerprint_from_db  # noqa: E402
from app.validation.runner import run_validation  # noqa: E402
from app.validation.storage import get_validation  # noqa: E402

SOURCE_VID = "32aead3291734f91"

def main() -> int:
    fp_before = fingerprint_from_db()
    source = get_validation(SOURCE_VID)
    if not source:
        raise SystemExit(f"源记录不存在：{SOURCE_VID}")

    # 完全沿用源记录的区间与参数；只让公司行为修复生效
    # 源记录是 41 只全池（pool_mode=all），必须沿用，否则只跑代表性池 6 只
    source_mode = "all" if len(source["etf_codes"]) > 10 else "representative"
    cfg = ValidationConfig(
        is_start=source["is_start"], is_end=source["is_end"],
        oos_start=source["oos_start"], oos_end=source["oos_end"],
        pool_mode=source_mode,
        initial_cash=1_000_000.0,
        ma_window_grid=(5, 10, 20, 30, 60, 120, 250),
    )
    print(f"池模式 {source_mode}（源记录 {len(source['etf_codes'])} 只）")
    print(f"重放区间 {cfg.is_start}~{cfg.is_end} / {cfg.oos_start}~{cfg.oos_end}")
    started = time.time()
    result = run_validation(cfg)
    elapsed = round(time.time() - started, 1)

    fp_after = fingerprint_from_db()
    record = get_validation(result.validation_id) or {}
    payload = {
        "phase": "3A.3.2",
        "source_validation_id": SOURCE_VID,
        "new_validation_id": result.validation_id,
        "status": result.status,
        "conclusion": result.conclusion,
        "elapsed_seconds": elapsed,
        "is_days": result.split.get("is_days"),
        "oos_days": result.split.get("oos_days"),
        "etf_count": len(result.codes),
        "input_hash": record.get("input_hash"),
        "data_fingerprint": record.get("input_hash"),
        "fingerprint_before": fp_before,
        "fingerprint_after": fp_after,
        "data_unchanged": fp_before.get("sha256") == fp_after.get("sha256"),
    }
    out = PROJECT_ROOT / "data" / "replay_validation_3a3_2.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                   encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    return 0 if payload["data_unchanged"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
