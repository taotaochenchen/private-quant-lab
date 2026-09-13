"""中信 Mac 持仓导入。只读取本地 XLS，白名单输出，不保留账户身份列。"""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
from io import StringIO


class HoldingsImportError(ValueError):
    """导入错误仅描述字段和行号，不回显账户数据。"""


FIELDS = {
    "证券代码": "security_code", "证券名称": "name", "股份余额": "quantity",
    "参考持股": "reference_quantity", "可用股份": "available_quantity", "冻结数量": "frozen_quantity",
    "成本价": "cost_price", "当前价": "last_price", "最新市值": "market_value",
}
REQUIRED = {"证券代码", "证券名称", "可用股份", "冻结数量", "成本价", "当前价", "最新市值"}
MISSING = {"", "--", "-", "—"}


def _text(value):
    return str(value).replace("\ufeff", "").strip() if value is not None else ""


def _number(value, row, column, integer=False, nonnegative=True):
    text = _text(value).replace(",", "").replace("，", "")
    if text in MISSING:
        raise HoldingsImportError("row {0}: missing {1}".format(row, column))
    try:
        if isinstance(value, bool):
            raise InvalidOperation
        number = Decimal(text)
    except InvalidOperation as exc:
        raise HoldingsImportError("row {0}: invalid {1}".format(row, column)) from exc
    if not number.is_finite() or (nonnegative and number < 0) or (integer and number != number.to_integral_value()):
        raise HoldingsImportError("row {0}: invalid {1}".format(row, column))
    return int(number) if integer else format(number, "f")


def parse_holdings_rows(rows):
    """解析表头及数据行；资金字段使用十进制字符串，缺失不补零。

    输出原证券代码，不根据代码猜测市场、证券类型或交易权限；同代码多行不合并。
    """
    if not rows:
        raise HoldingsImportError("missing header")
    headers = [_text(value) for value in rows[0]]
    missing = REQUIRED - set(headers)
    if missing or not {"股份余额", "参考持股"}.intersection(headers):
        raise HoldingsImportError("missing required holdings columns")
    for field in FIELDS:
        if headers.count(field) > 1:
            raise HoldingsImportError("duplicate holdings column: " + field)
    indexes = {field: headers.index(field) for field in FIELDS if field in headers}
    positions, warnings, codes = [], [], set()
    for row_number, row in enumerate(rows[1:], start=2):
        if not any(_text(value) for value in row):
            continue
        if len(row) != len(headers):
            raise HoldingsImportError("row {0}: inconsistent column count".format(row_number))
        # 身份相关列不进入结果对象或诊断信息。
        values = {field: row[index] for field, index in indexes.items()}
        code = _text(values["证券代码"])
        if isinstance(values["证券代码"], (int, float)) and not isinstance(values["证券代码"], bool):
            code = str(_number(values["证券代码"], row_number, "证券代码", integer=True)).zfill(6)
        if not re.fullmatch(r"\d{6}", code):
            raise HoldingsImportError("row {0}: invalid security code".format(row_number))
        name = _text(values["证券名称"])
        if not name:
            raise HoldingsImportError("row {0}: missing security name".format(row_number))
        quantity_field = "股份余额" if "股份余额" in values else "参考持股"
        quantity = _number(values[quantity_field], row_number, quantity_field, integer=True)
        available = _number(values["可用股份"], row_number, "可用股份", integer=True)
        frozen = _number(values["冻结数量"], row_number, "冻结数量", integer=True)
        if available + frozen > quantity:
            raise HoldingsImportError("row {0}: available plus frozen exceeds holdings".format(row_number))
        item = dict(security_code=code, name=name, quantity=quantity, available_quantity=available,
                    frozen_quantity=frozen, source_row=row_number)
        for field in ("成本价", "当前价", "最新市值"):
            item[FIELDS[field]] = _number(values[field], row_number, field, nonnegative=field != "成本价")
        if "参考持股" in values and _number(values["参考持股"], row_number, "参考持股", integer=True) != quantity:
            warnings.append("row {0}: reference quantity differs from share balance".format(row_number))
        if code in codes:
            warnings.append("row {0}: duplicate security code retained separately".format(row_number))
        codes.add(code)
        positions.append(item)
    return {"source": "citic_mac_xls_export", "positions": positions, "warnings": warnings,
            "is_mock": False, "snapshot_at": None, "execution_ready": False,
            "imported_at": datetime.now(timezone.utc).isoformat(),
            "limitations": ["导出文件不是实时账户快照；实际下单前需重新查询资金与可卖数量。",
                            "证券市场、证券类型与交易规则尚未核验。"]}


def load_citic_holdings(path):
    """识别二进制 XLS 并导入唯一持仓表，不修改源文件、不写磁盘。"""
    try:
        import xlrd
    except ImportError as exc:
        raise HoldingsImportError("install broker-import extra: pip install -e '.[broker-import]'") from exc
    source = Path(path)
    try:
        if source.stat().st_size > 10 * 1024 * 1024:
            raise HoldingsImportError("XLS exceeds 10 MiB limit")
        data = source.read_bytes()
    except OSError as exc:
        raise HoldingsImportError("cannot read holdings file") from exc
    if not data.startswith(bytes.fromhex("D0CF11E0A1B11AE1")):
        raise HoldingsImportError("expected binary XLS; HTML, text and XLSX are not supported")
    workbook = None
    try:
        workbook = xlrd.open_workbook(file_contents=data, on_demand=True, logfile=StringIO())
        candidates = []
        for sheet in workbook.sheets():
            if sheet.nrows and "证券代码" in [_text(v) for v in sheet.row_values(0)]:
                candidates.append(sheet)
        if len(candidates) != 1:
            raise HoldingsImportError("expected exactly one holdings sheet")
        sheet = candidates[0]
        if sheet.nrows > 10001:
            raise HoldingsImportError("too many holdings rows")
        return parse_holdings_rows([sheet.row_values(index) for index in range(sheet.nrows)])
    except HoldingsImportError:
        raise
    except Exception as exc:
        raise HoldingsImportError("cannot decode holdings workbook") from exc
    finally:
        if workbook is not None:
            workbook.release_resources()
