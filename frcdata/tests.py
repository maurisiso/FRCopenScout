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


# Real Statbotics v3 shapes (from github.com/avgupta456/statbotics backend to_dict())
SB_TEAM_EVENT = {
    "team": 254, "year": 2026, "event": "2026casj",
    "epa": {"total_points": 61.3, "unitless": 2010, "norm": 1890,
            "breakdown": {"total_points": 61.3, "auto_points": 18.2, "teleop_points": 30.1, "endgame_points": 13.0,
                          "energized_rp": 0.8, "auto_fuel": 9.5, "endgame_tower": 13.0},
            "stats": {"start": 55.0, "pre_elim": 60.1, "mean": 58.0, "max": 63.0}},
    "record": {"qual": {"wins": 9, "losses": 1, "ties": 0, "rank": 1}},
}
SB_TEAM_YEAR = {
    "team": 254, "year": 2026,
    "epa": {"total_points": 60.0, "norm": 1880, "breakdown": {"total_points": 60.0},
            "ranks": {"total": {"rank": 3, "percentile": 0.999, "team_count": 3600},
                      "country": {"rank": 2, "percentile": 0.99, "team_count": 2500},
                      "district": {"rank": None, "percentile": None, "team_count": None}}},
    "record": {"wins": 40, "losses": 5, "ties": 0, "count": 45, "winrate": 0.89},
}


class StatboticsShapeTests(SimpleTestCase):
    def test_team_event(self):
        p = parsing.parse_statbotics_team_event(SB_TEAM_EVENT)
        self.assertEqual(p["epa_total"], 61.3)
        self.assertEqual(p["epa_auto"], 18.2)
        self.assertEqual(p["epa_start"], 55.0)
        self.assertEqual(p["epa_norm"], 1890)
        self.assertEqual(p["epa_breakdown"]["auto_fuel"], 9.5)

    def test_team_year(self):
        p = parsing.parse_statbotics_team_year(SB_TEAM_YEAR)
        self.assertEqual(p["epa"], 60.0)
        self.assertEqual(p["world_rank"], 3)
        self.assertEqual(p["wins"], 40)
        self.assertIsNone(p["district_rank"])

    def test_match_pred(self):
        p = parsing.parse_statbotics_match({"pred": {"winner": "red", "red_win_prob": 0.7, "red_score": 120, "blue_score": 100}})
        self.assertEqual(p["pred_red_win_prob"], 0.7)


class FakeStatbotics:
    """Mimics the statbotics package: raises UserWarning when there's no data."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def get_team_events(self, event=None, limit=0, offset=0):
        self.calls.append(offset)
        page = self.rows[offset:offset + limit]
        if not page:
            raise UserWarning("Invalid inputs, no data recieved")
        return page

    def get_team_year(self, team, year):
        raise UserWarning("no data")


class StatboticsClientTests(SimpleTestCase):
    def test_pages_and_empty(self):
        from .clients import StatboticsClient

        fake = FakeStatbotics([{"team": i} for i in range(1500)])
        client = StatboticsClient(client=fake)
        self.assertEqual(len(client.team_events("2026x")), 1500)
        self.assertEqual(fake.calls, [0, 1000])
        self.assertIsNone(client.team_year(1, 2026))
        self.assertEqual(StatboticsClient(client=FakeStatbotics([])).team_events("none"), [])


class TBAEtagTests(SimpleTestCase):
    def test_304_uses_cache(self):
        from unittest import mock

        from django.core.cache import cache

        from .clients import TBAClient

        cache.clear()
        first = mock.Mock(status_code=200, headers={"ETag": 'W/"abc"'})
        first.json.return_value = {"current_season": 2026}
        second = mock.Mock(status_code=304, headers={})
        session = mock.Mock()
        session.get.side_effect = [first, second]
        tba = TBAClient(api_key="k", session=session)
        self.assertEqual(tba.status()["current_season"], 2026)
        self.assertEqual(tba.status()["current_season"], 2026)
        self.assertEqual(session.get.call_args.kwargs["headers"]["If-None-Match"], 'W/"abc"')
