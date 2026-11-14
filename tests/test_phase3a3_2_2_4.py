"""阶段3A.3.2.2.4：正式口径验证闸门一致性测试。

直接调用 `_require_formal()`，不经过回测，验证闸门自身的判定行为。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.validation.runner import (
    FORMAL_ACCOUNTING_BASIS,
    ValidationError,
    _require_formal,
)


def _result(basis, formal):
    return SimpleNamespace(accounting_basis=basis, formal_valuation=formal)


def _bare(**kwargs):
    return SimpleNamespace(**kwargs)


# ------------------------------------------------ 允许通过

def test_formal_basis_with_true_passes():
    """formal_receivable + True：唯一允许通过的组合。"""
    _require_formal(_result(FORMAL_ACCOUNTING_BASIS, True), "测试")
    assert FORMAL_ACCOUNTING_BASIS == "formal_receivable"


# ------------------------------------------------ 必须拒绝

def test_disabled_basis_with_false_rejected():
    with pytest.raises(ValidationError, match="非正式会计口径"):
        _require_formal(_result("disabled_non_official", False), "测试")


def test_disabled_basis_with_true_rejected():
    """自相矛盾：口径非正式但布尔标记为真，旧实现会放行。"""
    with pytest.raises(ValidationError, match="非正式会计口径"):
        _require_formal(_result("disabled_non_official", True), "测试")


def test_formal_basis_with_false_rejected():
    """自相矛盾：口径是正式但布尔标记为假。"""
    with pytest.raises(ValidationError, match="非正式会计口径"):
        _require_formal(_result(FORMAL_ACCOUNTING_BASIS, False), "测试")


def test_unknown_legacy_with_true_rejected():
    """未知口径即使布尔为真也必须拒绝。"""
    with pytest.raises(ValidationError, match="非正式会计口径"):
        _require_formal(_result("unknown_legacy", True), "测试")


def test_missing_accounting_basis_rejected():
    """缺 accounting_basis 属性。"""
    with pytest.raises(ValidationError, match="accounting_basis"):
        _require_formal(_bare(formal_valuation=True), "测试")
    # 属性存在但为 None
    with pytest.raises(ValidationError, match="accounting_basis"):
        _require_formal(_result(None, True), "测试")


def test_missing_formal_valuation_rejected():
    """缺 formal_valuation 属性。"""
    with pytest.raises(ValidationError, match="formal_valuation"):
        _require_formal(_bare(accounting_basis=FORMAL_ACCOUNTING_BASIS), "测试")
    # 属性存在但为 None
    with pytest.raises(ValidationError, match="formal_valuation"):
        _require_formal(_result(FORMAL_ACCOUNTING_BASIS, None), "测试")


@pytest.mark.parametrize("value", [1, 0, "yes", "True", [1], (1,), {"a": 1}, 1.0])
def test_non_boolean_formal_valuation_rejected(value):
    """非布尔类型即使真值判断为真，也必须拒绝。"""
    with pytest.raises(ValidationError, match="formal_valuation"):
        _require_formal(_result(FORMAL_ACCOUNTING_BASIS, value), "测试")


@pytest.mark.parametrize("value", [None, "", "FORMAL_RECEIVABLE", "formal", 0, ["formal_receivable"]])
def test_non_whitelisted_accounting_basis_rejected(value):
    """口径必须精确命中白名单字符串，不做大小写或前缀匹配。"""
    with pytest.raises(ValidationError, match="accounting_basis"):
        _require_formal(_result(value, True), "测试")


def test_error_message_names_both_fields():
    """错误信息必须同时点出两个字段，便于定位是哪一个不满足。"""
    with pytest.raises(ValidationError) as excinfo:
        _require_formal(_result("disabled_non_official", "yes"), "样本外回测")
    text = str(excinfo.value)
    assert "样本外回测" in text
    assert "accounting_basis" in text
    assert "formal_valuation" in text
    assert "formal_receivable" in text
