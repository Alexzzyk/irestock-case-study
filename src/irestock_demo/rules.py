from __future__ import annotations

from typing import Protocol

from .domain import Candidate, Decision, Policy


class Rule(Protocol):
    rule_id: str
    phase: str

    def evaluate(self, candidate: Candidate, policy: Policy) -> Decision | None: ...


class IncomingStockGate:
    rule_id, phase = "G001", "filter"

    def evaluate(self, candidate: Candidate, policy: Policy) -> Decision | None:
        row = candidate.row
        if row.in_order or row.in_transit:
            return Decision(self.rule_id, self.phase, "block", "Pending incoming stock", {
                "in_order": row.in_order, "in_transit": row.in_transit,
            })
        return None


class CompatibilityGate:
    rule_id, phase = "G002", "match"

    def evaluate(self, candidate: Candidate, policy: Policy) -> Decision | None:
        if not candidate.row.compatible:
            return Decision(self.rule_id, self.phase, "block", "Product/store pairing is disabled")
        return None


class SalesCoverageTarget:
    rule_id, phase = "Q001", "quantity"

    def evaluate(self, candidate: Candidate, policy: Policy) -> Decision:
        row = candidate.row
        sales_target = (row.sales_30d * policy.cover_days + 29) // 30
        floor = policy.display_floor if row.sales_90d else 0
        if row.main_push:
            floor = max(floor, policy.main_push_floor)
        return Decision(self.rule_id, self.phase, "target", "Sales coverage and display floor", {
            "target": max(sales_target, floor),
            "sales_target": sales_target,
            "floor": floor,
            "projected_stock": row.projected_stock,
        })


class RuleRegistry:
    PHASES = ("filter", "match", "quantity")

    def __init__(self, rules: tuple[Rule, ...] | None = None) -> None:
        self.rules = rules if rules is not None else (
            IncomingStockGate(), CompatibilityGate(), SalesCoverageTarget(),
        )
        identifiers = [rule.rule_id for rule in self.rules]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate rule identifiers")
        if any(rule.phase not in self.PHASES for rule in self.rules):
            raise ValueError("unknown rule phase")

    def evaluate(self, candidate: Candidate, policy: Policy) -> None:
        for phase in self.PHASES:
            for rule in self.rules:
                if not candidate.eligible:
                    return
                if rule.phase == phase:
                    decision = rule.evaluate(candidate, policy)
                    if decision is not None:
                        candidate.apply(decision)
        if candidate.eligible and candidate.need is None:
            raise ValueError("eligible candidate has no quantity rule")
