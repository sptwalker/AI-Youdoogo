"""Excel 上传模板规格与注册表（docs/11 A类数据源）。

每类业务数据对应一份官方模板：固定表头、字段类型、必填标记、业务唯一键。
解析器按表头指纹匹配模板；非模板文件拒收（不猜测自由格式）。
"""

from __future__ import annotations

from dataclasses import dataclass

ColumnType = str  # "str" | "int" | "float" | "date"


@dataclass(frozen=True)
class ColumnSpec:
    """一列的规格：Excel 表头文本 → 标准字段名 + 类型 + 是否必填。"""

    header: str  # Excel 中的表头文本
    key: str  # 标准化输出字段名
    type: ColumnType = "str"
    required: bool = True
    unit: str = ""  # 单位备注，仅文档用途


@dataclass(frozen=True)
class TemplateSpec:
    """一份业务数据模板。"""

    name: str  # 模板标识，如 "ops_daily"
    version: str  # 版本号，如 "v1"
    columns: tuple[ColumnSpec, ...]
    unique_keys: tuple[str, ...] = ()  # 业务唯一键（标准字段名），用于批内去重

    @property
    def headers(self) -> frozenset[str]:
        """本模板声明的全部表头文本。"""
        return frozenset(c.header for c in self.columns)


class TemplateRegistry:
    """模板注册表：按表头指纹匹配文件对应的模板。"""

    def __init__(self) -> None:
        self._templates: list[TemplateSpec] = []

    def register(self, template: TemplateSpec) -> None:
        """注册（或按 name+version 覆盖）一份模板。"""
        self._templates = [
            t for t in self._templates if (t.name, t.version) != (template.name, template.version)
        ]
        self._templates.append(template)

    def match(self, file_headers: list[str]) -> TemplateSpec | None:
        """按表头指纹选模板：声明表头全部出现在文件表头中，匹配列最多者胜。

        多模板并存时以列数最多的为准（更具体的模板优先）；无匹配返回 None。
        """
        present = {h.strip() for h in file_headers if h and h.strip()}
        candidates = [t for t in self._templates if t.headers <= present]
        if not candidates:
            return None
        return max(candidates, key=lambda t: len(t.columns))


registry = TemplateRegistry()

# 平台运营部日数据模板（首个落地部门，字段为示例，联调时按真实报表定稿）
registry.register(
    TemplateSpec(
        name="ops_daily",
        version="v1",
        columns=(
            ColumnSpec("日期", "stat_date", "date"),
            ColumnSpec("产品", "product", "str"),
            ColumnSpec("日活", "dau", "int", unit="人"),
            ColumnSpec("新增", "new_users", "int", required=False, unit="人"),
            ColumnSpec("次留", "retention_d1", "float", required=False, unit="%"),
        ),
        unique_keys=("stat_date", "product"),
    )
)
