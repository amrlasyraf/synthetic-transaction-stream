import tempfile
import unittest
from datetime import date
from pathlib import Path

from synthetic_transaction_stream.generator import Config, Generator
from synthetic_transaction_stream.validate import validate_output


class GeneratorTests(unittest.TestCase):
    def test_reproducible_month_and_valid_lifecycle(self):
        config = Config(seed=17, start_date=date(2026, 1, 1), days=30,
                        transactions_per_day=120)
        with tempfile.TemporaryDirectory() as first_dir, tempfile.TemporaryDirectory() as second_dir:
            first = Path(first_dir)
            second = Path(second_dir)
            Generator(config).generate().write(first)
            Generator(config).generate().write(second)
            for path in first.iterdir():
                self.assertEqual(path.read_bytes(), (second / path.name).read_bytes(), path.name)
            report = validate_output(first)
            self.assertGreater(report["status_counts"].get("declined", 0), 0)
            self.assertGreater(report["status_counts"].get("refunded", 0), 0)
            self.assertGreater(report["scenario_transactions"], 0)
            self.assertGreater(report["hourly_counts_utc"]["18"],
                               report["hourly_counts_utc"]["03"])

    def test_anomalies_can_be_disabled(self):
        config = Config(days=5, transactions_per_day=20, anomalies=False)
        generated = Generator(config).generate()
        self.assertEqual(generated.labels, [])
        self.assertTrue(generated.events)


if __name__ == "__main__":
    unittest.main()
