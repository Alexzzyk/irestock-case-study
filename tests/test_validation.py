import pytest

from irestock_demo.domain import Dataset, Policy, StockRow


@pytest.mark.parametrize("field,value", [("stock", -1), ("stock", 1.5), ("in_order", True),
                                         ("sales_7d", "2"), ("main_push", "Y"), ("sku", "")])
def test_invalid_domain_values_rejected(field, value):
    values = dict(sku="SKU-1", style="STYLE-1", store="STORE-A", store_brand="BRAND-A")
    values[field] = value
    with pytest.raises(ValueError):
        StockRow(**values)


def test_duplicate_rows_rejected_before_allocation():
    item = StockRow("SKU-1", "STYLE-1", "A", "BRAND-A")
    with pytest.raises(ValueError, match="duplicate"):
        Dataset((item, item), {})


def test_store_brand_conflict_rejected_before_transfer():
    with pytest.raises(ValueError, match="inconsistent brand"):
        Dataset((StockRow("SKU-1", "STYLE-1", "A", "X"), StockRow("SKU-2", "STYLE-2", "A", "Y")), {})


@pytest.mark.parametrize("values", [{"cover_days": 0}, {"warehouse_reserve": -1}])
def test_invalid_policy_rejected(values):
    with pytest.raises(ValueError):
        Policy(**values)
