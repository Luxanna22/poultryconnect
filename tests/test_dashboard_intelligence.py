import unittest
from datetime import date

from app.routes.dashboard.dashboard import _build_market_intelligence


class DashboardIntelligenceTests(unittest.TestCase):
    def test_market_intelligence_returns_actionable_guidance(self):
        result = _build_market_intelligence(
            recent_records=[
                type('Record', (), {'egg_count': 220, 'egg_price': 8.0, 'feed_cost': 180.0})(),
                type('Record', (), {'egg_count': 240, 'egg_price': 7.8, 'feed_cost': 170.0})(),
            ],
            monthly_expenses=1500.0,
            farm_count=2,
            today=date(2026, 7, 1),
        )

        self.assertEqual(result['farm_count'], 2)
        self.assertGreater(result['recommended_price'], 0)
        self.assertGreaterEqual(result['projected_profit'], 0)
        self.assertTrue(
            'demand' in result['demand_signal'].lower() or 'balanced' in result['demand_signal'].lower()
        )
        self.assertEqual(len(result['buyer_leads']), 3)


if __name__ == '__main__':
    unittest.main()
