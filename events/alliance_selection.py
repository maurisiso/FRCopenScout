"""
FRC alliance selection engine (pure Python, no Django).

How alliance selection works:

* After qualifications, the top N ranked teams (usually 8) are Alliance Captains.
* Picking is "serpentine": round 1 goes Alliance 1 -> N, round 2 goes N -> 1
  (and, at Championship divisions, a round 3 goes 1 -> N again).
* In round 1 a captain may invite a *lower-seeded captain*. If that captain
  accepts, their alliance disappears, every alliance below moves up one seed,
  and the next-highest-ranked team that isn't on an alliance becomes the new
  last captain. (E.g. Alliance 1 picks Alliance 2's captain -> old Alliance 3
  becomes Alliance 2, ..., and the rank-9 team becomes Alliance 8 captain.)
* A team that DECLINES an invitation can't be picked by anyone afterwards,
  but it can still become a captain if teams above it get picked.
* Teams left over after selection form the backup pool, in rank order.

The engine replays a list of actions, which makes "undo" and saving a
user's prediction trivial: we store just the list of actions.
"""
from dataclasses import dataclass, field


class SelectionError(ValueError):
    pass


def default_alliance_count(num_teams):
    """8 alliances, unless the event is too small to fill them."""
    return max(2, min(8, num_teams // 3)) if num_teams else 8


@dataclass
class AllianceSelection:
    rankings: list  # team numbers, index 0 = rank 1
    num_alliances: int = 8
    rounds: int = 2  # picks per captain: 2 at regionals/districts, 3 at Championship divisions
    alliances: list = field(default_factory=list)
    declined: set = field(default_factory=set)
    turn: int = 0
    history: list = field(default_factory=list)

    def __post_init__(self):
        self.rankings = list(dict.fromkeys(self.rankings))  # dedupe, keep order
        self.num_alliances = min(self.num_alliances, len(self.rankings))
        if not self.alliances:
            self.alliances = [[team] for team in self.rankings[: self.num_alliances]]

    # --- Turn order -------------------------------------------------------
    @property
    def turn_order(self):
        """List of alliance indexes in picking order, e.g. 0..7, 7..0."""
        order = []
        forward = list(range(self.num_alliances))
        for r in range(self.rounds):
            order.extend(forward if r % 2 == 0 else list(reversed(forward)))
        return order

    @property
    def is_complete(self):
        return self.turn >= len(self.turn_order) or not self.available()

    @property
    def current_alliance(self):
        """0-based index of the alliance whose captain is picking, or None."""
        if self.is_complete:
            return None
        return self.turn_order[self.turn]

    @property
    def current_round(self):
        if self.is_complete:
            return None
        return self.turn // self.num_alliances + 1

    # --- Who can be picked ------------------------------------------------
    def on_alliance(self):
        return {t for a in self.alliances for t in a}

    def _cur(self):
        return self.turn_order[self.turn] if self.turn < len(self.turn_order) else None

    def lower_captains(self):
        """Captains below the one currently picking (they can still be invited in round 1)."""
        cur = self._cur()
        if cur is None or self.turn >= self.num_alliances:  # only during round 1
            return []
        return [a[0] for a in self.alliances[cur + 1:] if len(a) == 1]

    def available(self):
        """Teams the current captain may invite, in rank order."""
        taken = self.on_alliance()
        free = [t for t in self.rankings if t not in taken and t not in self.declined]
        lower = {t for t in self.lower_captains() if t not in self.declined}
        pool = set(free) | lower
        return [t for t in self.rankings if t in pool]

    def backup_pool(self, size=8):
        taken = self.on_alliance()
        return [t for t in self.rankings if t not in taken and t not in self.declined][:size]

    # --- Actions ----------------------------------------------------------
    def _promote_new_captain(self):
        taken = self.on_alliance()
        for team in self.rankings:  # declined teams CAN become captains
            if team not in taken:
                self.alliances.append([team])
                return team
        return None

    def pick(self, team):
        if self.is_complete:
            raise SelectionError("Alliance selection is already complete.")
        if team not in self.available():
            raise SelectionError(f"Team {team} cannot be picked now.")
        cur = self.current_alliance
        promoted = None
        was_captain = team in self.lower_captains()
        if was_captain:
            idx = next(i for i, a in enumerate(self.alliances) if a[0] == team)
        self.alliances[cur].append(team)
        if was_captain:
            # idx > cur always (only lower seeds can be invited), so `cur` stays valid.
            self.alliances.pop(idx)
            promoted = self._promote_new_captain()
        self.history.append({"type": "pick", "team": team, "alliance": cur + 1, "promoted": promoted})
        self.turn += 1
        return promoted

    def decline(self, team):
        if self.is_complete:
            raise SelectionError("Alliance selection is already complete.")
        if team not in self.available():
            raise SelectionError(f"Team {team} cannot be invited now.")
        self.declined.add(team)
        self.history.append({"type": "decline", "team": team, "alliance": self.current_alliance + 1})
        # Same captain picks again; turn does not advance.

    def apply(self, action):
        if action["type"] == "pick":
            return self.pick(int(action["team"]))
        if action["type"] == "decline":
            return self.decline(int(action["team"]))
        raise SelectionError(f"Unknown action {action}")

    @classmethod
    def replay(cls, rankings, actions, num_alliances=8, rounds=2):
        sel = cls(rankings=rankings, num_alliances=num_alliances, rounds=rounds)
        for action in actions:
            sel.apply(action)
        return sel

    # --- Automatic prediction --------------------------------------------
    def auto_pick(self, scores):
        """Current captain picks the best available team by score (higher = better)."""
        options = self.available()
        if not options:
            return None
        rank_index = {t: i for i, t in enumerate(self.rankings)}
        best = max(options, key=lambda t: (scores.get(t, float("-inf")), -rank_index[t]))
        self.pick(best)
        return best

    def auto_complete(self, scores):
        while not self.is_complete:
            self.auto_pick(scores)
        return self

    def as_dict(self):
        return {
            "alliances": [list(a) for a in self.alliances],
            "declined": sorted(self.declined),
            "complete": self.is_complete,
            "backup_pool": self.backup_pool(),
        }


def predict(rankings, scores, num_alliances=8, rounds=2):
    """Full automatic prediction: every captain greedily takes the best available team."""
    return AllianceSelection(rankings=rankings, num_alliances=num_alliances, rounds=rounds).auto_complete(scores)
