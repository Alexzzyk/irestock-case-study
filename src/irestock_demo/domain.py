from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


def nonnegative_integer(name: str, value: object) -> None:
    if type(value) is not int or value < 0:
        raise ValueError(f"{name} must be a nonnegative integer")


@dataclass(frozen=True)
class StockRow:
    sku: str
    style: str
    store: str
    store_brand: str
    stock: int = 0
    in_order: int = 0
    in_transit: int = 0
    sales_7d: int = 0
    sales_30d: int = 0
    sales_90d: int = 0
    main_push: bool = False
    compatible: bool = True

    def __post_init__(self) -> None:
        for name in ("sku", "style", "store", "store_brand"):
            value = getattr(self, name)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{name} must be a nonempty string")
        for name in ("stock", "in_order", "in_transit", "sales_7d", "sales_30d", "sales_90d"):
            nonnegative_integer(name, getattr(self, name))
        for name in ("main_push", "compatible"):
            if type(getattr(self, name)) is not bool:
                raise ValueError(f"{name} must be boolean")

    @property
    def key(self) -> tuple[str, str]:
        return self.sku, self.store

    @property
    def projected_stock(self) -> int:
        return self.stock + self.in_order + self.in_transit


@dataclass(frozen=True)
class Policy:
    cover_days: int = 15
    display_floor: int = 1
    main_push_floor: int = 2
    warehouse_reserve: int = 2

    def __post_init__(self) -> None:
        for name, value in asdict(self).items():
            nonnegative_integer(name, value)
        if not self.cover_days:
            raise ValueError("cover_days must be positive")


@dataclass(frozen=True)
class Dataset:
    rows: tuple[StockRow, ...]
    warehouse: dict[str, int]
    policy: Policy = field(default_factory=Policy)
    avoidance: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        keys: set[tuple[str, str]] = set()
        styles: dict[str, str] = {}
        brands: dict[str, str] = {}
        for row in self.rows:
            if row.key in keys:
                raise ValueError(f"duplicate SKU/store: {row.key}")
            keys.add(row.key)
            if row.sku in styles and styles[row.sku] != row.style:
                raise ValueError(f"inconsistent style for {row.sku}")
            if row.store in brands and brands[row.store] != row.store_brand:
                raise ValueError(f"inconsistent brand for {row.store}")
            styles[row.sku], brands[row.store] = row.style, row.store_brand
        for sku, quantity in self.warehouse.items():
            if not isinstance(sku, str) or not sku.strip():
                raise ValueError("warehouse SKU must be a nonempty string")
            nonnegative_integer(f"warehouse[{sku}]", quantity)
        pairs: set[tuple[str, str]] = set()
        for pair in self.avoidance:
            if len(pair) != 2 or pair[0] == pair[1] or not set(pair) <= set(brands):
                raise ValueError(f"invalid avoidance pair: {pair}")
            normalized = tuple(sorted(pair))
            if normalized in pairs:
                raise ValueError(f"duplicate avoidance pair: {pair}")
            pairs.add(normalized)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Dataset:
        return cls(
            rows=tuple(StockRow(**row) for row in data["rows"]),
            warehouse=dict(data.get("warehouse", {})),
            policy=Policy(**data.get("policy", {})),
            avoidance=tuple(tuple(pair) for pair in data.get("avoidance", [])),
        )


@dataclass(frozen=True)
class Decision:
    rule_id: str
    phase: str
    action: Literal["block", "target", "allocate"]
    reason: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass
class Candidate:
    row: StockRow
    eligible: bool = True
    target: int | None = None
    need: int | None = None
    allocated: int = 0
    trace: list[Decision] = field(default_factory=list)

    def apply(self, decision: Decision) -> None:
        self.trace.append(decision)
        if decision.action == "block":
            self.eligible = False
        elif decision.action == "target":
            self.target = decision.evidence["target"]
            self.need = max(0, self.target - self.row.projected_stock)

    def audit(self, reserve: int) -> dict[str, Any]:
        return {
            "sku": self.row.sku,
            "store": self.row.store,
            "eligible": self.eligible,
            "target_stock": self.target,
            "requested_qty": self.need,
            "allocated_qty": self.allocated,
            "warehouse_reserved_qty": reserve,
            "reserve_scope": "sku",
            "trace": [asdict(decision) for decision in self.trace],
        }


def priority(row: StockRow) -> tuple:
    return (-int(row.main_push), -row.sales_7d, -row.sales_30d, -row.sales_90d, row.store, row.sku)
