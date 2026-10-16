"""A generic starter form teams can adapt to the current game."""

STARTER_MATCH_FIELDS = [
    {"key": "starting_position", "label": "Starting position", "field_type": "choice", "phase": "prematch",
     "options": ["Left", "Center", "Right"]},
    {"key": "auto_leave", "label": "Left starting zone", "field_type": "boolean", "phase": "auto", "points": 3},
    {"key": "auto_scored", "label": "Game pieces scored (auto)", "field_type": "counter", "phase": "auto",
     "min_value": 0, "max_value": 30, "points": 5},
    {"key": "teleop_scored", "label": "Game pieces scored (teleop)", "field_type": "counter", "phase": "teleop",
     "min_value": 0, "max_value": 60, "points": 2},
    {"key": "teleop_missed", "label": "Missed shots / drops", "field_type": "counter", "phase": "teleop",
     "min_value": 0, "max_value": 60},
    {"key": "played_defense", "label": "Played defense", "field_type": "boolean", "phase": "teleop"},
    {"key": "endgame", "label": "Endgame result", "field_type": "choice", "phase": "endgame",
     "options": ["None", "Parked", "Climb low", "Climb high", "Failed attempt"]},
    {"key": "driver_skill", "label": "Driver skill", "field_type": "rating", "phase": "general"},
    {"key": "disabled", "label": "Robot disabled / died", "field_type": "boolean", "phase": "general"},
    {"key": "comments", "label": "Comments", "field_type": "text", "phase": "general"},
]

STARTER_PIT_FIELDS = [
    {"key": "drivetrain", "label": "Drivetrain", "field_type": "choice", "phase": "general",
     "options": ["Swerve", "Tank / West coast", "Mecanum", "Other"]},
    {"key": "weight_lbs", "label": "Robot weight (lbs)", "field_type": "number", "phase": "general",
     "min_value": 0, "max_value": 150},
    {"key": "capabilities", "label": "Can do", "field_type": "multi", "phase": "general",
     "options": ["Score low", "Score high", "Ground intake", "Climb", "Defense"]},
    {"key": "auto_routines", "label": "Number of auto routines", "field_type": "number", "phase": "auto",
     "min_value": 0, "max_value": 20},
    {"key": "pit_notes", "label": "Notes", "field_type": "text", "phase": "general"},
]
