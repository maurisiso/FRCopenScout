from django.test import SimpleTestCase

from . import parsing


class ParsingTests(SimpleTestCase):
    def test_team_number(self):
        self.assertEqual(parsing.team_number("frc254"), 254)
        self.assertEqual(parsing.team_number("frc1678B"), 1678)

    def test_dig_fallbacks(self):
        d = {"epa": {"total_points": {"mean": 42.0}}}
        self.assertEqual(parsing.dig(d, "epa.breakdown.total_points", "epa.total_points.mean"), 42.0)
        self.assertIsNone(parsing.dig(d, "nope.nothing"))

    def test_parse_match_unplayed(self):
        m = parsing.parse_match({
            "comp_level": "qm", "set_number": 1, "match_number": 7, "time": 1700000000,
            "alliances": {"red": {"team_keys": ["frc1", "frc2", "frc3"], "score": -1},
                          "blue": {"team_keys": ["frc4", "frc5", "frc6"], "score": -1}},
        })
        self.assertEqual(m["red_teams"], [1, 2, 3])
        self.assertIsNone(m["red_score"])
        self.assertIsNotNone(m["scheduled_time"])

    def test_parse_rankings(self):
        r = parsing.parse_rankings({"rankings": [
            {"rank": 1, "team_key": "frc254", "record": {"wins": 9, "losses": 1, "ties": 0}, "matches_played": 10, "sort_orders": [3.2, 1]},
        ]})
        self.assertEqual(r[254]["rank"], 1)
        self.assertEqual(r[254]["ranking_score"], 3.2)

    def test_parse_statbotics_team_event(self):
        out = parsing.parse_statbotics_team_event({"epa": {"breakdown": {"total_points": 50, "auto_points": 10,
                                                                          "teleop_points": 30, "endgame_points": 10}}})
        self.assertEqual(out["epa_total"], 50)
        self.assertEqual(out["epa_teleop"], 30)

    def test_parse_alliances(self):
        rows = parsing.parse_alliances([{"picks": ["frc1", "frc5", "frc9"], "declines": ["frc3"], "backup": None}])
        self.assertEqual(rows[0]["picks"], [1, 5, 9])
        self.assertEqual(rows[0]["declines"], [3])
