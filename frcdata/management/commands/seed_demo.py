"""
Create a fake event full of realistic-looking data so you can try every page
without a TBA API key.

    python manage.py seed_demo --team 1234 --email you@example.com

* Creates (or reuses) team 1234, approves it, and makes that user its admin.
* Creates event "2026demo" with 36 teams, a qualification schedule,
  scores, rankings, EPA, a match scouting form and scouting entries.
"""
import math
import random
import uuid
from datetime import date, datetime, timedelta, timezone

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from events.models import TrackedEvent
from frcdata.models import Event, EventTeam, FRCTeam, Match, TeamSeason
from scouting.models import FormField, MatchNote, ScoutEntry, ScoutingForm
from scouting.templates_starter import STARTER_MATCH_FIELDS, STARTER_PIT_FIELDS
from teams.models import Membership, Role, Team

ADJ = ["Iron", "Robo", "Cyber", "Thunder", "Quantum", "Steel", "Neon", "Atomic", "Electric", "Galactic", "Nova", "Titan"]
NOUN = ["Eagles", "Wolves", "Panthers", "Gears", "Knights", "Bots", "Falcons", "Dragons", "Sparks", "Rhinos", "Owls", "Pirates"]


class Command(BaseCommand):
    help = "Create a demo event with fake data (no API key needed)."

    def add_arguments(self, parser):
        parser.add_argument("--team", type=int, default=9999, help="Your team number (added to the event).")
        parser.add_argument("--email", help="Make this existing user an admin of the team.")
        parser.add_argument("--played", type=int, default=None, help="How many quals have been played (default: all).")
        parser.add_argument("--seed", type=int, default=2026)

    @transaction.atomic
    def handle(self, *args, **opts):
        rnd = random.Random(opts["seed"])
        our = opts["team"]

        team, _ = Team.objects.get_or_create(number=our, defaults={"nickname": "Demo Team"})
        team.status = Team.Status.APPROVED
        team.save()
        if opts.get("email"):
            user = get_user_model().objects.filter(email=opts["email"]).first()
            if user:
                Membership.objects.update_or_create(user=user, team=team, defaults={"role": Role.ADMIN})
                self.stdout.write(f"{user.email} is now admin of {our}")
            else:
                self.stdout.write(self.style.WARNING(f"No user with email {opts['email']} (sign up first)."))

        Event.objects.filter(key="2026demo").delete()
        start = date.today() - timedelta(days=1)
        event = Event.objects.create(
            key="2026demo", year=2026, name="Demo Regional (practice data)", short_name="Demo Regional",
            event_type=0, event_type_string="Regional", city="Monterrey", state_prov="NL", country="Mexico",
            start_date=start, end_date=start + timedelta(days=2), is_demo=True,
        )
        TrackedEvent.objects.get_or_create(team=team, event=event, defaults={"source": TrackedEvent.Source.MANUAL})

        # Teams and their "true" strength
        numbers = sorted(set([our] + rnd.sample(range(100, 9800), 35)))
        strength = {}
        for n in numbers:
            ft, _ = FRCTeam.objects.get_or_create(number=n)
            if not ft.nickname:
                ft.nickname = f"{rnd.choice(ADJ)} {rnd.choice(NOUN)}" if n != our else team.nickname
                ft.city, ft.country = rnd.choice([("Monterrey", "Mexico"), ("Houston", "USA"), ("Toronto", "Canada"),
                                                  ("Guadalajara", "Mexico"), ("Austin", "USA")])
                ft.save()
            total = max(4.0, rnd.gauss(32, 13))
            a, e = rnd.uniform(0.15, 0.3), rnd.uniform(0.1, 0.25)
            strength[n] = {"auto": total * a, "endgame": total * e, "teleop": total * (1 - a - e), "total": total}
            EventTeam.objects.create(event=event, team=ft)

        # Qualification schedule: each team plays ~12 matches
        rounds = 12
        n_matches = math.ceil(len(numbers) * rounds / 6)
        pool, schedule = [], []
        for _ in range(n_matches):
            if len(pool) < 6:
                extra = numbers[:]
                rnd.shuffle(extra)
                pool += [t for t in extra if t not in pool]
            six, pool = pool[:6], pool[6:]
            schedule.append(six)
        played_n = n_matches if opts["played"] is None else max(0, min(opts["played"], n_matches))
        t0 = datetime.combine(start + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=15)

        record = {n: [0, 0, 0] for n in numbers}  # W L T
        rp = {n: 0 for n in numbers}
        for i, six in enumerate(schedule, start=1):
            red, blue = six[:3], six[3:]
            exp_r = sum(strength[t]["total"] for t in red)
            exp_b = sum(strength[t]["total"] for t in blue)
            m = Match(key=f"2026demo_qm{i}", event=event, comp_level="qm", set_number=1, match_number=i,
                      red_teams=red, blue_teams=blue, scheduled_time=t0 + timedelta(minutes=7 * i),
                      pred_red_score=round(exp_r, 1), pred_blue_score=round(exp_b, 1),
                      pred_red_win_prob=round(1 / (1 + math.exp(-(exp_r - exp_b) / 14)), 3))
            if i <= played_n:
                rs = max(0, round(rnd.gauss(exp_r, 14)))
                bs = max(0, round(rnd.gauss(exp_b, 14)))

                def fake_breakdown(total, side):
                    auto = round(sum(strength[t]["auto"] for t in side) * rnd.uniform(.8, 1.2))
                    end = round(sum(strength[t]["endgame"] for t in side) * rnd.uniform(.7, 1.2))
                    foul = rnd.choice([0, 0, 0, 2, 5])
                    return {"autoPoints": auto, "teleopPoints": max(0, total - auto - end - foul), "endGamePoints": end,
                            "foulPoints": foul, "foulCount": foul // 2, "totalPoints": total,
                            "energizedBonusAchieved": total > 90, "traversalBonusAchieved": end > 20}

                m.score_breakdown = {"red": fake_breakdown(rs, red), "blue": fake_breakdown(bs, blue)}
                m.red_score, m.blue_score = rs, bs
                m.winning_alliance = "red" if rs > bs else "blue" if bs > rs else ""
                m.actual_time = m.scheduled_time
                for side, score, other in ((red, rs, bs), (blue, bs, rs)):
                    for t in side:
                        if score > other:
                            record[t][0] += 1; rp[t] += 3
                        elif score < other:
                            record[t][1] += 1
                        else:
                            record[t][2] += 1; rp[t] += 1
                        rp[t] += rnd.random() < strength[t]["total"] / 60  # bonus RP
            m.save()

        # Rankings + EPA
        order = sorted(numbers, key=lambda n: (-rp[n], -strength[n]["total"]))
        for rank, n in enumerate(order, start=1):
            w, l, t = record[n]
            mp = w + l + t
            s = strength[n]
            noise = lambda v: round(max(0, v + rnd.gauss(0, 2.5)), 1)
            EventTeam.objects.filter(event=event, team__number=n).update(
                rank=rank if played_n else None, wins=w, losses=l, ties=t, matches_played=mp,
                ranking_score=round(rp[n] / mp, 2) if mp else None,
                epa_total=noise(s["total"]), epa_auto=noise(s["auto"]), epa_teleop=noise(s["teleop"]),
                epa_endgame=noise(s["endgame"]), opr=noise(s["total"] * 1.05),
                epa_start=noise(s["total"] * 0.9), epa_norm=round(1500 + (s["total"] - 30) * 12),
                epa_breakdown={"auto_fuel": round(s["auto"] / 3, 2), "auto_tower": round(s["auto"] / 4, 2),
                               "teleop_fuel": round(s["teleop"] / 2.5, 2), "endgame_tower": round(s["endgame"], 2),
                               "energized_rp": round(min(1, s["total"] / 60), 2), "traversal_rp": round(min(1, s["endgame"] / 12), 2)},
            )

        s = strength[our]
        TeamSeason.objects.update_or_create(team=FRCTeam.objects.get(number=our), year=2026, defaults={
            "epa": round(s["total"], 1), "world_rank": 1200, "world_count": 3600, "world_percentile": 0.67,
            "country_rank": 18, "country_count": 90, "wins": 14, "losses": 10, "ties": 0})

        # Scouting forms + entries
        ScoutEntry.objects.filter(team=team, event=event).delete()
        form = team.scouting_forms.filter(kind=ScoutingForm.Kind.MATCH, season=2026).first()
        if not form:
            form = ScoutingForm.objects.create(team=team, name="Match scouting", kind=ScoutingForm.Kind.MATCH, season=2026)
            for i, spec in enumerate(STARTER_MATCH_FIELDS):
                FormField.objects.create(form=form, order=i, **spec)
        pit = team.scouting_forms.filter(kind=ScoutingForm.Kind.PIT, season=2026).first()
        if not pit:
            pit = ScoutingForm.objects.create(team=team, name="Pit scouting", kind=ScoutingForm.Kind.PIT, season=2026)
            for i, spec in enumerate(STARTER_PIT_FIELDS):
                FormField.objects.create(form=pit, order=i, **spec)

        scout = Membership.objects.filter(team=team).select_related("user").first()
        scout_user = scout.user if scout else None
        fields = {f.key for f in form.fields.all()}
        count = 0
        for m in Match.objects.filter(event=event, red_score__isnull=False):
            for t in m.all_teams:
                if rnd.random() > 0.65 and t != our:
                    continue
                s = strength[t]
                died = rnd.random() < 0.05
                k = 0.2 if died else 1.0
                data = {
                    "starting_position": rnd.choice(["Left", "Center", "Right"]),
                    "auto_leave": rnd.random() < 0.9,
                    "auto_scored": max(0, round(rnd.gauss(s["auto"] / 5, 0.8) * k)),
                    "teleop_scored": max(0, round(rnd.gauss(s["teleop"] / 2, 2) * k)),
                    "teleop_missed": max(0, round(rnd.gauss(3, 2))),
                    "played_defense": rnd.random() < (0.5 if s["total"] < 25 else 0.1),
                    "endgame": "Climb high" if s["endgame"] > 8 and not died else rnd.choice(["Parked", "Climb low", "None", "Failed attempt"]),
                    "driver_skill": max(1, min(5, round(s["total"] / 12 + rnd.gauss(0, .7)))),
                    "disabled": died,
                    "comments": "Robot stopped moving mid-match" if died else "",
                }
                ScoutEntry.objects.create(
                    team=team, event=event, form=form, match=m, match_key=m.key, scouted_team=t,
                    alliance=m.alliance_of(t), data={k2: v for k2, v in data.items() if k2 in fields},
                    scout=scout_user, client_uuid=uuid.uuid4(), recorded_at=m.actual_time,
                )
                count += 1
                if died:
                    MatchNote.objects.create(team=team, event=event, match=m, match_key=m.key, about_team=t,
                                             category=MatchNote.Category.ROBOT, author=scout_user,
                                             text="Robot lost power about 40s into teleop. Possibly battery or breaker.")
        for t in rnd.sample(numbers, 10):
            ScoutEntry.objects.create(team=team, event=event, form=pit, scouted_team=t, scout=scout_user,
                                      client_uuid=uuid.uuid4(),
                                      data={"drivetrain": rnd.choice(["Swerve", "Swerve", "Tank / West coast"]),
                                            "weight_lbs": rnd.randint(95, 125),
                                            "capabilities": rnd.sample(["Score low", "Score high", "Ground intake", "Climb", "Defense"], 3),
                                            "auto_routines": rnd.randint(1, 5), "pit_notes": ""})
        MatchNote.objects.create(team=team, event=event, match_key="2026demo_qm3", about_team=our,
                                 category=MatchNote.Category.COMMS, author=scout_user,
                                 text="Radio rebooted after hitting the barrier. Re-mount the radio away from the bumper.")
        self.stdout.write(self.style.SUCCESS(
            f"Demo event ready: {len(numbers)} teams, {n_matches} quals ({played_n} played), {count} scouting entries. "
            f"Open /t/{our}/e/2026demo/"
        ))
