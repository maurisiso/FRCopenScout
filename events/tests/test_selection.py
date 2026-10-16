from django.test import SimpleTestCase

from events.alliance_selection import AllianceSelection, SelectionError, default_alliance_count, predict


class AllianceSelectionTests(SimpleTestCase):
    def setUp(self):
        self.ranks = list(range(1, 31))  # team N is ranked N

    def test_initial_captains(self):
        sel = AllianceSelection(self.ranks)
        self.assertEqual([a[0] for a in sel.alliances], [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertEqual(sel.current_alliance, 0)

    def test_serpentine_order(self):
        sel = AllianceSelection(self.ranks)
        self.assertEqual(sel.turn_order, list(range(8)) + list(range(7, -1, -1)))
        self.assertEqual(len(AllianceSelection(self.ranks, rounds=3).turn_order), 24)

    def test_picking_a_captain_promotes_everyone_below(self):
        sel = AllianceSelection(self.ranks)
        promoted = sel.pick(2)  # Alliance 1 picks Alliance 2's captain
        self.assertEqual(promoted, 9)
        self.assertEqual(sel.alliances[0], [1, 2])
        self.assertEqual([a[0] for a in sel.alliances], [1, 3, 4, 5, 6, 7, 8, 9])
        self.assertEqual(sel.current_alliance, 1)  # former Alliance 3 now picks as Alliance 2

    def test_declined_team_cannot_be_picked_but_can_become_captain(self):
        sel = AllianceSelection(self.ranks)
        sel.decline(9)  # A1 invites rank 9, who declines
        self.assertEqual(sel.current_alliance, 0)  # same captain picks again
        with self.assertRaises(SelectionError):
            sel.pick(9)
        sel.pick(2)  # A1 picks captain 2 -> rank 9 (declined) is next unaffiliated team, becomes captain 8
        self.assertEqual(sel.alliances[7], [9])

    def test_declining_captain_stays_captain(self):
        sel = AllianceSelection(self.ranks)
        sel.decline(3)
        self.assertEqual(sel.alliances[2], [3])
        self.assertNotIn(3, sel.available())

    def test_cannot_pick_higher_captain_or_in_round_two(self):
        sel = AllianceSelection(self.ranks)
        sel.pick(10)  # A1
        with self.assertRaises(SelectionError):
            sel.pick(1)  # A2 can't pick A1 captain
        for t in [11, 12, 13, 14, 15, 16, 17]:
            sel.pick(t)
        self.assertEqual(sel.current_round, 2)
        self.assertEqual(sel.current_alliance, 7)
        self.assertNotIn(7, sel.available())  # captains can't be picked in round 2

    def test_predict_is_complete_and_unique(self):
        scores = {t: 100 - t for t in self.ranks}
        sel = predict(self.ranks, scores)
        self.assertTrue(sel.is_complete)
        teams = [t for a in sel.alliances for t in a]
        self.assertEqual(len(teams), 24)
        self.assertEqual(len(set(teams)), 24)

    def test_replay(self):
        sel = AllianceSelection.replay(self.ranks, [{"type": "pick", "team": 2}, {"type": "decline", "team": 4}])
        self.assertEqual(sel.alliances[0], [1, 2])
        self.assertIn(4, sel.declined)

    def test_small_event(self):
        self.assertEqual(default_alliance_count(18), 6)
        self.assertEqual(default_alliance_count(40), 8)
        sel = predict(list(range(1, 13)), {}, num_alliances=4)
        self.assertTrue(sel.is_complete)
        self.assertEqual(len(sel.alliances), 4)
