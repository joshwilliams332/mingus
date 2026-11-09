import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import build_data as B  # noqa: E402


class ReserveStatus(unittest.TestCase):
    def test_injured_reserve_counts_as_out(self):
        inj = B.reserve_status({"status": "RES", "status_description_abbr": "R01", "week": "9"}, None)
        self.assertEqual((inj["status"], inj["injury"], inj["reserve"]), ("Out", "Injured reserve", True))

    def test_this_weeks_injury_report_wins(self):
        report = {"status": "Questionable", "injury": "Knee", "practice": "Limited", "week": 10}
        self.assertIs(B.reserve_status({"status": "RES", "status_description_abbr": "R48", "week": "9"}, report), report)

    def test_active_and_practice_squad_untouched(self):
        self.assertIsNone(B.reserve_status({"status": "ACT", "status_description_abbr": "A01"}, None))
        self.assertIsNone(B.reserve_status({"status": "DEV", "status_description_abbr": "P01"}, None))
        self.assertEqual(B.reserve_status({"status": "CUT", "status_description_abbr": "W03"}, None)["injury"], "Released")


if __name__ == "__main__":
    unittest.main()
