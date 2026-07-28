import unittest
from datetime import date

from modules.Emergency_help.weekly_report.weekly_report_generator import WeeklyReportGenerator
from modules.backend_api import main as backend_main


class WeeklyReportGeneratorTests(unittest.TestCase):
    def test_closure_window_keeps_current_monday_cutoff(self) -> None:
        windows = WeeklyReportGenerator()._closure_windows(date(2026, 7, 6))

        self.assertEqual(windows["current_week_start"], date(2026, 7, 6))
        self.assertEqual(windows["current_week_end"], date(2026, 7, 12))
        self.assertEqual(windows["current_notice_start"], date(2026, 6, 29))
        self.assertEqual(windows["current_notice_end"], date(2026, 6, 29))

    def test_backend_report_date_selects_previous_week(self) -> None:
        result = backend_main._generate_weekly_report({
            "report_date": "2026-06-29",
            "vulnerability_notice_dir": "",
            "event_notice_dir": "",
        })

        self.assertEqual(result["status"], "success")
        self.assertEqual(result["report_date"], "2026-06-29")
        self.assertEqual(result["summary"]["windows"]["current_week_start"], "2026-06-29")
        self.assertEqual(result["summary"]["windows"]["current_week_end"], "2026-07-05")


if __name__ == "__main__":
    unittest.main()
