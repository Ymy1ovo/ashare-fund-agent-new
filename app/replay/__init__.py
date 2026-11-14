"""阶段3A.3.2.3.1 历史记录重放体系。

只读历史记录、只写新记录，绝不覆盖或删除任何历史回测与验证结果。
"""
from app.replay.manifest import (  # noqa: F401
    BACKTEST,
    CLASS_CURRENT_FORMAL,
    CLASS_LEGACY,
    CLASS_NON_REPLAYABLE,
    CLASS_REPLAYED,
    CLASS_UNKNOWN_LEGACY,
    SRC_DEFAULTED,
    SRC_DERIVED,
    SRC_MISSING,
    SRC_RECORDED,
    VALIDATION,
    ReplayError,
    backtest_manifest,
    validation_manifest,
)
from app.replay.registry import (  # noqa: F401
    ReplayOutcome,
    find_success,
    init_replay_schema,
    list_attempts,
    start_attempt,
    finish_attempt,
)
