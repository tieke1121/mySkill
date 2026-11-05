"""Numerical and rejection tests through the calculator's public interface."""

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "stock-research/scripts/dcf.py"
EXAMPLE = ROOT / "stock-research/assets/dcf-example.json"
spec = importlib.util.spec_from_file_location("dcf", SCRIPT)
dcf = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dcf)


def model():
    return json.loads(EXAMPLE.read_text(encoding="utf-8"))


class DCFTests(unittest.TestCase):
    def test_level_perpetuity_closed_form(self):
        data = model()
        data.update(as_of="2025-01-01", terminal_growth=0, terminal_cash_flow=100, bridge=[])
        data["periods"] = [{"start": "2025-01-01", "end": "2026-01-01", "cash_flow": 100, "basis": "fixture"}]
        base = dcf.calculate(data)["base"]
        self.assertAlmostEqual(base["enterprise_value"], 1000)
        self.assertAlmostEqual(base["value_per_quote_unit"], 10)

    def test_stub_and_leap_year_use_actual_dates(self):
        data = model()
        rows = dcf.calculate(data)["base"]["periods"]
        self.assertAlmostEqual(rows[0]["years"], 56 / 365)
        self.assertAlmostEqual(rows[0]["present_value"], 15 / 1.1 ** (56 / 365))
        self.assertAlmostEqual(rows[-1]["years"], (56 + 365 + 366) / 365)

    def test_amount_unit_change_leaves_price_unchanged(self):
        data, changed = model(), model()
        changed["amount_scale"] = 1
        for period in changed["periods"]:
            period["cash_flow"] *= 1000000
        changed["terminal_cash_flow"] *= 1000000
        for item in changed["bridge"]:
            item["value"] *= 1000000
        self.assertAlmostEqual(dcf.calculate(data)["base"]["value_per_quote_unit"],
                               dcf.calculate(changed)["base"]["value_per_quote_unit"])

    def test_stock_split_changes_per_share_not_equity(self):
        data = model()
        before = dcf.calculate(data)["base"]
        data["shares"]["count"] *= 4
        after = dcf.calculate(data)["base"]
        self.assertEqual(before["equity_value"], after["equity_value"])
        self.assertAlmostEqual(before["value_per_quote_unit"] / 4, after["value_per_quote_unit"])

    def test_fx_and_adr_direction(self):
        data = model()
        ordinary = dcf.calculate(data)["base"]["value_per_quote_unit"]
        data["quote"].update(currency="HKD", fx_per_model_currency=7.8, ordinary_shares_per_quote_unit=2)
        self.assertAlmostEqual(dcf.calculate(data)["base"]["value_per_quote_unit"], ordinary * 7.8 * 2)

    def test_bridge_sign_and_no_extra_discount(self):
        data = model()
        before = dcf.calculate(data)["base"]
        data["bridge"].append({"label": "other claim", "value": -100, "basis": "fixture"})
        after = dcf.calculate(data)["base"]
        self.assertAlmostEqual(after["equity_value"], before["equity_value"] - 100)
        self.assertAlmostEqual(after["value_per_quote_unit"], before["value_per_quote_unit"] - 1)

    def test_fcfe_no_double_subtraction(self):
        data = model()
        data["cash_flow_type"] = "FCFE"
        with self.assertRaisesRegex(ValueError, "bridge must be empty"):
            dcf.calculate(data)
        data["bridge"] = []
        base = dcf.calculate(data)["base"]
        self.assertIsNone(base["enterprise_value"])
        self.assertEqual(base["equity_value"], base["discounted_cash_flow_value"])

    def test_reverse_round_trip_with_adr_fx_and_bridge(self):
        data = model()
        data["quote"].update(currency="HKD", fx_per_model_currency=7.8, ordinary_shares_per_quote_unit=2)
        price = dcf.calculate(data)["base"]["value_per_quote_unit"]
        result = dcf.calculate(data, target_price=price)
        self.assertAlmostEqual(result["reverse"]["required_next_annual_terminal_cash_flow"], data["terminal_cash_flow"])

    def test_reverse_nonpositive_solution_flagged(self):
        result = dcf.calculate(model(), target_price=0.0001)
        self.assertIn("outside", result["reverse"]["status"])

    def test_sensitivity_monotonicity_and_base_cell(self):
        data = model()
        result = dcf.calculate(data)
        grid = {(c["discount_rate"], c["terminal_growth"]): c["value_per_quote_unit"] for c in result["sensitivity"]}
        self.assertEqual(grid[(0.10, 0.03)], result["base"]["value_per_quote_unit"])
        self.assertGreater(grid[(0.09, 0.03)], grid[(0.11, 0.03)])
        self.assertGreater(grid[(0.10, 0.04)], grid[(0.10, 0.02)])

    def test_invalid_sensitivity_cell_has_no_value(self):
        data = model()
        data["sensitivity"] = {"discount_rates": [0.03], "terminal_growth_rates": [0.03, 0.04]}
        for cell in dcf.calculate(data)["sensitivity"]:
            self.assertIsNone(cell["value_per_quote_unit"])
            self.assertIn("invalid", cell["status"])

    def test_distress_does_not_emit_negative_share_price(self):
        data = model()
        data["bridge"][1]["value"] = -100000
        result = dcf.calculate(data)
        self.assertLess(result["base"]["equity_value"], 0)
        self.assertIsNone(result["base"]["value_per_quote_unit"])
        self.assertTrue(result["warnings"])

    def test_negative_explicit_cash_flow_allowed(self):
        data = model()
        data["periods"][0]["cash_flow"] = -20
        self.assertLess(dcf.calculate(data)["base"]["periods"][0]["present_value"], 0)

    def test_period_errors_rejected(self):
        for index, key, value in [(0, "start", "2026-01-01"), (1, "start", "2026-12-30"),
                                  (1, "start", "2027-01-02"), (0, "end", "2026-11-05")]:
            with self.subTest(index=index, key=key, value=value):
                data = model()
                data["periods"][index][key] = value
                with self.assertRaises(ValueError):
                    dcf.calculate(data)

    def test_invalid_numbers_and_rates_rejected(self):
        for key, value in [("terminal_growth", 0.10), ("terminal_growth", -1),
                           ("discount_rate", 0), ("discount_rate", float("nan")),
                           ("terminal_cash_flow", float("inf")), ("terminal_cash_flow", 0),
                           ("amount_scale", True), ("amount_scale", 7), ("discount_rate", "0.1")]:
            with self.subTest(key=key, value=value):
                data = model()
                data[key] = value
                with self.assertRaises(ValueError):
                    dcf.calculate(data)

    def test_missing_unknown_and_invalid_fields_rejected(self):
        variants = []
        data = model()
        del data["shares"]
        variants.append(data)
        data = model()
        data["discount_rates"] = 0.10
        variants.append(data)
        data = model()
        data["shares"]["count"] = 0
        variants.append(data)
        data = model()
        data["periods"] = []
        variants.append(data)
        data = model()
        data["quote"]["fx_per_model_currency"] = 7.8
        variants.append(data)
        data = model()
        data["periods"][0]["basis"] = ""
        variants.append(data)
        for data in variants:
            with self.subTest(data=data):
                with self.assertRaises(ValueError):
                    dcf.calculate(data)

    def test_inputs_unmodified_and_result_reproducible(self):
        data = model()
        original = deepcopy(data)
        self.assertEqual(dcf.calculate(data), dcf.calculate(data))
        self.assertEqual(data, original)

    def test_cli_json_output_and_no_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "result.json"
            command = [sys.executable, str(SCRIPT), str(EXAMPLE), "--output", str(output), "--target-price", "25"]
            first = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stderr)
            payload = output.read_bytes()
            self.assertEqual(json.loads(payload)["reverse"]["target_price"], 25)
            second = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(second.returncode, 0)
            self.assertEqual(payload, output.read_bytes())

    def test_cli_invalid_input_nonzero_and_no_output(self):
        with tempfile.TemporaryDirectory() as folder:
            input_path, output = Path(folder) / "input.json", Path(folder) / "result.json"
            input_path.write_text('{"schema_version": 1}', encoding="utf-8")
            run = subprocess.run([sys.executable, str(SCRIPT), str(input_path), "--output", str(output)], capture_output=True, text=True)
            self.assertEqual(run.returncode, 2)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
