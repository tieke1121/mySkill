#!/usr/bin/env python3
"""Dated, end-of-period DCF. Standard library only; see --help and model-contract.md."""

import argparse
from datetime import date
import json
import math
from pathlib import Path


def number(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label}: expected a number")
    value = float(value)
    if not math.isfinite(value) or (positive and value <= 0):
        raise ValueError(f"{label}: expected a finite {'positive ' if positive else ''}number")
    return value


def text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: expected nonempty text")
    return value


def fields(obj, required, label):
    if not isinstance(obj, dict):
        raise ValueError(f"{label}: expected an object")
    missing, extra = set(required) - obj.keys(), obj.keys() - set(required)
    if missing or extra:
        raise ValueError(f"{label}: missing={sorted(missing)}, unknown={sorted(extra)}")


def iso_date(value, label):
    text(value, label)
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError(f"{label}: use YYYY-MM-DD")
    return parsed


def validate(model):
    """Reject ambiguous dimensions, past/overlapping periods and double debt subtraction."""
    fields(model, (
        "schema_version", "as_of", "currency", "amount_scale", "cash_flow_type",
        "discount_rate", "discount_rate_basis", "terminal_growth", "terminal_growth_basis",
        "terminal_cash_flow", "terminal_basis",
        "periods", "bridge", "shares", "quote", "sensitivity",
    ), "model")
    if type(model["schema_version"]) is not int or model["schema_version"] != 1:
        raise ValueError("schema_version must be integer 1")
    as_of = iso_date(model["as_of"], "as_of")
    for key in ("currency", "discount_rate_basis", "terminal_growth_basis", "terminal_basis"):
        text(model[key], key)
    number(model["amount_scale"], "amount_scale", positive=True)
    if model["amount_scale"] not in (1, 1000, 10000, 1000000, 100000000, 1000000000):
        raise ValueError("amount_scale must be 1, 1000, 10000, 1000000, 100000000 or 1000000000")
    if model["cash_flow_type"] not in ("FCFF", "FCFE"):
        raise ValueError("cash_flow_type must be FCFF or FCFE")
    rate = number(model["discount_rate"], "discount_rate", positive=True)
    growth = number(model["terminal_growth"], "terminal_growth")
    if not -1 < growth < rate:
        raise ValueError("terminal_growth must satisfy -1 < g < discount_rate")
    number(model["terminal_cash_flow"], "terminal_cash_flow", positive=True)

    periods = model["periods"]
    if not isinstance(periods, list) or not periods:
        raise ValueError("periods must be a nonempty list")
    previous = as_of
    for i, period in enumerate(periods):
        label = f"periods[{i}]"
        fields(period, ("start", "end", "cash_flow", "basis"), label)
        start, end = iso_date(period["start"], label), iso_date(period["end"], label)
        if start != previous or end <= start:
            raise ValueError(f"{label}: periods must be contiguous, ordered, and start at as_of")
        number(period["cash_flow"], f"{label}.cash_flow")
        text(period["basis"], f"{label}.basis")
        previous = end

    if not isinstance(model["bridge"], list):
        raise ValueError("bridge must be a list")
    if model["cash_flow_type"] == "FCFE" and model["bridge"]:
        raise ValueError("FCFE bridge must be empty; do not subtract debt twice")
    labels = set()
    for item in model["bridge"]:
        fields(item, ("label", "value", "basis"), "bridge item")
        label = text(item["label"], "bridge.label")
        if label in labels:
            raise ValueError("bridge labels must be unique")
        labels.add(label)
        number(item["value"], "bridge.value")
        text(item["basis"], "bridge.basis")

    fields(model["shares"], ("count", "basis"), "shares")
    number(model["shares"]["count"], "shares.count", positive=True)
    text(model["shares"]["basis"], "shares.basis")
    quote = model["quote"]
    fields(quote, ("currency", "fx_per_model_currency", "ordinary_shares_per_quote_unit", "basis"), "quote")
    text(quote["currency"], "quote.currency")
    number(quote["fx_per_model_currency"], "quote.fx_per_model_currency", positive=True)
    number(quote["ordinary_shares_per_quote_unit"], "quote.ordinary_shares_per_quote_unit", positive=True)
    text(quote["basis"], "quote.basis")
    if quote["currency"] == model["currency"] and quote["fx_per_model_currency"] != 1:
        raise ValueError("same-currency FX must be 1")

    grid = model["sensitivity"]
    fields(grid, ("discount_rates", "terminal_growth_rates"), "sensitivity")
    for key in grid:
        if not isinstance(grid[key], list) or not grid[key]:
            raise ValueError(f"sensitivity.{key}: expected nonempty list")
        for value in grid[key]:
            value = number(value, f"sensitivity.{key}", positive=key == "discount_rates")
            if key == "terminal_growth_rates" and value <= -1:
                raise ValueError("sensitivity growth rates must be greater than -1")


def _price(model, rate, growth, terminal_cash_flow):
    """Values remain in the declared amount unit until the per-share conversion."""
    as_of = date.fromisoformat(model["as_of"])
    rows = []
    for period in model["periods"]:
        years = (date.fromisoformat(period["end"]) - as_of).days / 365.0
        factor = (1 + rate) ** years
        rows.append({**period, "years": years, "present_value": period["cash_flow"] / factor})
    explicit = math.fsum(row["present_value"] for row in rows)
    terminal = terminal_cash_flow / (rate - growth)
    terminal_pv = terminal / ((1 + rate) ** rows[-1]["years"])
    discounted = explicit + terminal_pv
    adjustment = math.fsum(item["value"] for item in model["bridge"])
    equity = discounted + adjustment
    quote = model["quote"]
    conversion = (model["amount_scale"] / model["shares"]["count"]
                  * quote["fx_per_model_currency"] * quote["ordinary_shares_per_quote_unit"])
    return {
        "periods": rows, "explicit_present_value": explicit,
        "terminal_value": terminal, "terminal_present_value": terminal_pv,
        "discounted_cash_flow_value": discounted,
        "enterprise_value": discounted if model["cash_flow_type"] == "FCFF" else None,
        "bridge_total": adjustment, "equity_value": equity,
        "value_per_quote_unit": equity * conversion if equity > 0 else None,
        "terminal_share_of_dcf": terminal_pv / discounted if discounted > 0 else None,
    }


def calculate(model, target_price=None):
    """Pure public entry point. Does not fetch data or validate economic assumptions."""
    validate(model)
    rate, growth = model["discount_rate"], model["terminal_growth"]
    base = _price(model, rate, growth, model["terminal_cash_flow"])
    warnings = []
    if base["equity_value"] <= 0:
        warnings.append("Nonpositive modeled equity: use a distress/restructuring analysis; no share price emitted.")
    if base["terminal_share_of_dcf"] is not None and base["terminal_share_of_dcf"] > 0.8:
        warnings.append("Terminal PV exceeds 80% of DCF value; a heuristic sensitivity flag, not a validity threshold.")
    grid = []
    for r in model["sensitivity"]["discount_rates"]:
        for g in model["sensitivity"]["terminal_growth_rates"]:
            # Keep next-year terminal cash flow fixed: only r and g change in this grid.
            cell = {"discount_rate": r, "terminal_growth": g}
            if r <= g:
                cell.update(value_per_quote_unit=None, status="invalid: r <= g")
            else:
                value = _price(model, r, g, model["terminal_cash_flow"])["value_per_quote_unit"]
                cell.update(value_per_quote_unit=value, status="ok" if value is not None else "nonpositive equity")
            grid.append(cell)

    reverse = None
    if target_price is not None:
        target_price = number(target_price, "target_price", positive=True)
        quote = model["quote"]
        target_equity = (target_price * model["shares"]["count"] / model["amount_scale"]
                         / quote["fx_per_model_currency"] / quote["ordinary_shares_per_quote_unit"])
        required_pv = target_equity - base["bridge_total"] - base["explicit_present_value"]
        required_cf = required_pv * (1 + rate) ** base["periods"][-1]["years"] * (rate - growth)
        reverse = {
            "target_price": target_price,
            "required_next_annual_terminal_cash_flow": required_cf,
            "status": "conditional" if required_cf > 0 else "outside positive-terminal-cash-flow model",
            "interpretation": "Only terminal cash flow is solved; all other inputs fixed. Not observed market consensus.",
        }
    result = {
        "schema_version": 1, "as_of": model["as_of"], "currency": model["currency"],
        "amount_scale": model["amount_scale"], "quote_currency": model["quote"]["currency"],
        "cash_flow_type": model["cash_flow_type"], "discount_convention": "period-end, ACT/365",
        "base": base, "sensitivity": grid, "reverse": reverse, "warnings": warnings,
        "inputs": model,
    }
    # Reject overflow/nonfinite output instead of silently emitting nonstandard JSON.
    json.dumps(result, allow_nan=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="JSON model; see references/model-contract.md")
    parser.add_argument("--output", type=Path, help="New result file; an existing file is not overwritten")
    parser.add_argument("--target-price", type=float, help="Quote-currency price for reverse terminal-CF analysis")
    args = parser.parse_args()
    try:
        model = json.loads(args.input.read_text(encoding="utf-8"))
        result = calculate(model, args.target_price)
        rendered = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8") as output:
                output.write(rendered)
        else:
            print(rendered, end="")
    except (ValueError, OSError, OverflowError, ZeroDivisionError) as error:
        parser.exit(2, f"DCF error: {error}\n")


if __name__ == "__main__":
    main()
