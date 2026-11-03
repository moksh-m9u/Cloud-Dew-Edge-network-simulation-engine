"""Team details used on the report's title block, its contributions table and the title slide."""

TEAM = [
    ("Moksh", "06719051624"),
    ("Bhavya Bisht", "05019051624"),
    ("Dhruv Sharma", "05719051624"),
    ("Bhuwan Chugh", "04219051624"),
]
"""(name, enrollment number) for each member, in the order they appear."""

CONTRIBUTIONS = {
    "Moksh": "Placement policies, simulator, experiments",
    "Bhavya Bisht": "VM manager and security, Streamlit app",
    "Dhruv Sharma": "Results export and charts, testing",
    "Bhuwan Chugh": "Settings system, workload generator and task files, command-line menu; report, slides, architecture diagram",
}


def team_line() -> str:
    """All members as one line, e.g. ``"Moksh (06719051624) · Bhavya Bisht (05019051624) · ..."``."""
    return " · ".join(f"{name} ({number})" for name, number in TEAM)
