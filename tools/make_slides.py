"""Write the presentation: ``python tools/make_slides.py`` → ``docs/report/EdgeFogSim_Slides.pptx``.

Seven 16:9 slides with speaker notes: title, architecture, formulas (every term
explained, with a worked example), algorithm, E1, E2–E4, conclusion. Numbers come from a fresh experiment run in
``docs/evidence/`` and the E1 chart is a native PowerPoint chart, so it can be
restyled in PowerPoint. Re-run this script after changing code or settings.
"""

import sys
from pathlib import Path

from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_LABEL_POSITION, XL_LEGEND_POSITION
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Emu, Inches, Pt

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence import ROOT, build_experiments  # noqa: E402
from team import TEAM  # noqa: E402

from edgefogsim.config import load_settings  # noqa: E402
from edgefogsim.experiments import ExperimentRun  # noqa: E402
from edgefogsim.policies import CapacityAware  # noqa: E402
from edgefogsim.qos import latency_breakdown  # noqa: E402
from edgefogsim.simulator import fresh_nodes, run_workload  # noqa: E402
from edgefogsim.workload import load_tasks  # noqa: E402

OUTPUT = ROOT / "docs" / "report" / "EdgeFogSim_Slides.pptx"

NAVY, INK, MUTED, WHITE, CARD = "14213D", "1F2937", "5B6472", "FFFFFF", "F3F6FA"
TIER = {"edge": "2A78D6", "fog": "EB6834", "cloud": "1BAF7A"}
GOOD, WARN, BAD = "0CA30C", "FAB219", "D03B3B"
HEAD, BODY = "Cambria", "Calibri"
W, H = Inches(13.333), Inches(7.5)


def main() -> int:
    """Rebuild the evidence and write the slides."""
    print(write_slides(build_experiments()))
    return 0


def write_slides(run: ExperimentRun, path: Path = OUTPUT) -> Path:
    """Write the deck for an experiment run.

    Args:
        run: The experiments whose numbers go on the results slides.
        path: Destination ``.pptx``.

    Returns:
        The path written.
    """
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    e1, e2, e3, e4 = run.experiments
    title_slide(prs)
    system_slide(prs)
    formula_slide(prs)
    algorithm_slide(prs)
    policy_slide(prs, e1)
    stress_slide(prs, e2, e3, e4)
    conclusion_slide(prs, run)
    path.parent.mkdir(parents=True, exist_ok=True)
    prs.save(path)
    return path


def title_slide(prs) -> None:
    """Slide 1: name, one-line pitch, team, and the three-tier motif."""
    s = _slide(prs, NAVY)
    _tier_dots(s, Inches(0.8), Inches(1.4), Inches(0.42))
    _text(s, "EdgeFogSim", Inches(0.8), Inches(2.2), Inches(11), Inches(1.3), 60, WHITE, font=HEAD, bold=True)
    _text(s, "Where should a task run: Edge, Fog or Cloud? A rule-based placement simulator with VMs, "
             "tenant security and QoS results.", Inches(0.8), Inches(3.6), Inches(10.5), Inches(1.2), 22, "CADCFC")
    _text(s, "ARM 305 – Cloud, Dev, Edge and Fog Computing · Mini Project", Inches(0.8), Inches(5.5),
          Inches(10), Inches(0.5), 16, "CADCFC")
    _text(s, "   ·   ".join(f"{name} {number}" for name, number in TEAM), Inches(0.8), Inches(6.0),
          Inches(11.8), Inches(0.5), 15, WHITE)
    _notes(s, "Introduce the problem: urgent jobs need nearby, small edge nodes; heavy jobs can wait for the "
              "big, distant cloud. EdgeFogSim simulates choosing where each task runs and measures the result.")


def system_slide(prs) -> None:
    """Slide 2: the architecture diagram."""
    s = _slide(prs, WHITE)
    _title(s, "Every task passes access control, a policy and a shared VM")
    picture = s.shapes.add_picture(str(ROOT / "docs" / "architecture.png"), 0, Inches(1.45), height=Inches(5.75))
    picture.left = int((W - picture.width) / 2)
    _notes(s, "Walk left to right: tenants log in through the CLI menu or the Streamlit app; access control "
              "refuses other tenants' records; the placement engine picks a node using the QoS model; the VM "
              "manager runs the task inside one of that tenant's VMs; results are exported as CSV, JSON and charts.")


def formula_slide(prs) -> None:
    """Slide 3: the latency, congestion and score formulas, what every term means, and a worked example."""
    settings = load_settings()
    qos, policy = settings.simulation["qos"], settings.simulation["policy"]
    w, d = policy["capacity_weights"], qos["deadlines_ms"]
    nodes = settings.nodes
    s = _slide(prs, WHITE)
    _title(s, "How latency and the placement score are calculated")

    _card(s, Inches(0.6), Inches(1.35), Inches(7.6), Inches(3.15))
    _text(s, "Latency of a task on a node", Inches(0.9), Inches(1.5), Inches(7.0), Inches(0.4), 17, INK, bold=True)
    _text(s, "L = d + (W ÷ s) × C          C = 1 ÷ (1 − u)", Inches(0.9), Inches(1.95), Inches(7.0),
          Inches(0.5), 24, NAVY, font=HEAD, bold=True)
    _terms(s, [
        ("L", "latency: time until the answer comes back (ms)"),
        ("d", "network delay to the node: " + ", ".join(f"{n.tier} {n.base_latency_ms:g}" for n in nodes) + " ms"),
        ("W", "work units: how much processing the task needs"),
        ("s", "node speed: " + ", ".join(f"{n.tier} {n.speed_factor:g}" for n in nodes) + " (W ÷ s = ms of work)"),
        ("C", "congestion: 1 when idle, 2 at half load, 10 at 90% load"),
        ("u", f"node CPU load after adding the task, 0 to 1 (capped at {qos['congestion_cap']:.0%})"),
    ], Inches(0.9), Inches(2.6))

    _card(s, Inches(0.6), Inches(4.7), Inches(7.6), Inches(2.5))
    _text(s, "Placement score (Capacity-Aware)", Inches(0.9), Inches(4.85), Inches(7.0), Inches(0.4), 17, INK,
          bold=True)
    _text(s, f"S = {w['tier']:g}·T + {w['slack']:g}·(D − L) ÷ D + {w['free']:g}·(1 − u)", Inches(0.9),
          Inches(5.28), Inches(7.0), Inches(0.5), 22, NAVY, font=HEAD, bold=True)
    _terms(s, [
        ("T", "tier preference: 1st choice 1, 2nd 0.5, 3rd 0"),
        ("D", f"deadline by sensitivity: high {d['high']:g}, medium {d['medium']:g}, low {d['low']:g} ms"),
        ("(D−L)÷D", "share of the deadline left over; success means L ≤ D"),
        ("1 − u", "share of the node's CPU still free after adding the task"),
    ], Inches(0.9), Inches(5.82), symbol_width=Inches(1.15))

    task = load_tasks(ROOT / "examples" / "tasks_sample.csv", settings)[0]
    edge = next(n for n in fresh_nodes(settings) if n.tier == "edge")
    b = latency_breakdown(task, edge, settings)
    scores = CapacityAware(settings).choose(task, fresh_nodes(settings)).scores
    slack = (b["deadline_ms"] - b["latency_ms"]) / b["deadline_ms"]
    _card(s, Inches(8.45), Inches(1.35), Inches(4.3), Inches(5.85))
    _text(s, f"Worked example: {task.id} on {edge.id}", Inches(8.7), Inches(1.5), Inches(3.9), Inches(0.4), 17,
          INK, bold=True)
    _text(s, f"{task.cpu_cores:g} CPU · W = {task.work_units:g} · {task.sensitivity} → D = {b['deadline_ms']:g} ms",
          Inches(8.7), Inches(1.95), Inches(3.9), Inches(0.4), 13, MUTED)
    steps = [
        f"u = (0 + {task.cpu_cores:g}) ÷ {edge.cpu_cores:g} = {b['load_after']:g}",
        f"C = 1 ÷ (1 − {b['load_after']:g}) = {b['congestion']:g}",
        f"L = {b['network_ms']:g} + ({b['work_units']:g} ÷ {b['speed']:g}) × {b['congestion']:g}",
        f"   = {b['network_ms']:g} + {b['processing_ms']:.2f} × {b['congestion']:g} = {b['latency_ms']:.1f} ms",
        f"{b['latency_ms']:.1f} ≤ {b['deadline_ms']:g}  →  on time",
        f"S = {w['tier']:g}·1 + {w['slack']:g}·{slack:.2f} + {w['free']:g}·{1 - b['load_after']:g}",
        f"   = {scores[edge.id]:.2f}",
    ]
    _text(s, "\n".join(steps), Inches(8.7), Inches(2.5), Inches(3.9), Inches(3.3), 15, INK)
    others = ", ".join(f"{node} {score:.2f}" for node, score in scores.items() if node != edge.id)
    _text(s, f"Other nodes: {others}. Highest score wins, so {task.id} goes to {edge.id}.", Inches(8.7),
          Inches(5.95), Inches(3.9), Inches(0.9), 13, MUTED)
    _notes(s, "Latency L is network delay d plus processing time W divided by speed s, stretched by congestion C. "
              "C comes from the node's CPU load u after adding the task: an idle node has C = 1, a half-loaded "
              "node doubles processing time, and a 90% loaded node makes it ten times slower, like a queue. "
              "A task succeeds if L is within its deadline D. Capacity-Aware then scores each node that passes "
              "its filters: tier preference, the share of the deadline left over, and the CPU left free, with "
              "weights 0.5, 0.3 and 0.2. Walk through the worked example on the right: T01 on the empty Edge "
              "node has u = 0.5, so C = 2 and L = 18.3 ms, inside its 25 ms deadline, and Edge scores highest.")


def algorithm_slide(prs) -> None:
    """Slide 4: the Capacity-Aware rules, the four sample decisions, and the other policies."""
    settings = load_settings()
    policy = settings.simulation["policy"]
    w = policy["capacity_weights"]
    s = _slide(prs, WHITE)
    _title(s, "Capacity-Aware: filter, score, then offload or reject")
    steps = [
        ("Prefer tiers by urgency", "high → Edge, Fog, Cloud · medium → Fog first · low → Cloud first"),
        ("Filter out nodes", f"no room for the task's VM, CPU load over {policy['headroom']:.0%}, or L > D "
                             "(the deadline would be missed)"),
        ("Score the rest", f"S = {w['tier']:g}·T + {w['slack']:g}·(D − L) ÷ D + {w['free']:g}·(1 − u); "
                           "highest wins"),
        ("Offload or reject", "not first-choice tier = offload, with the reason; nothing passes (even at 100% "
                              "load) = reject, naming the failed check on each node"),
    ]
    y = Inches(1.5)
    for i, (head, body) in enumerate(steps, start=1):
        _circle_number(s, i, Inches(0.8), y + Inches(0.05))
        _text(s, head, Inches(1.55), y, Inches(5.5), Inches(0.45), 18, INK, bold=True)
        _text(s, body, Inches(1.55), y + Inches(0.45), Inches(5.5), Inches(0.8), 14, MUTED)
        y += Inches(1.35)
    worked = run_workload(settings, load_tasks(ROOT / "examples" / "tasks_sample.csv", settings)[:4], "capacity")
    rows = [["Task", "Needs", "Result"]] + [
        [f"{d.task.id} ({d.task.sensitivity})", f"{d.task.cpu_cores:g} CPU, W {d.task.work_units:g}",
         ("rejected" if not d.placed else f"{d.node_id}{' (offload)' if d.offloaded else ''}, {d.latency_ms:.0f} ms")]
        for d in worked.decisions]
    _text(s, "Sample tasks on empty nodes", Inches(7.4), Inches(1.5), Inches(5.3), Inches(0.4), 17, INK, bold=True)
    _table(s, rows, Inches(7.4), Inches(2.0), Inches(5.3), [Inches(1.6), Inches(1.6), Inches(2.1)])
    _card(s, Inches(7.4), Inches(4.4), Inches(5.3), Inches(2.4))
    _text(s, "Compared against", Inches(7.65), Inches(4.55), Inches(4.8), Inches(0.4), 16, INK, bold=True)
    _text(s, "Latency-First: nearest node with room, ignores deadlines\nCloud-Only: every task to the cloud\n"
             "TOPSIS: ranks nodes on latency, free CPU and free memory together", Inches(7.65), Inches(5.0),
          Inches(4.8), Inches(1.7), 14, INK)
    _notes(s, "Capacity-Aware is the rule-based algorithm the brief asks for. It prefers a tier by urgency, rules "
              "out nodes that have no room, are over 85% loaded or would miss the deadline, scores the rest with "
              "the formula from the previous slide, and offloads or rejects with a reason. In the sample: T01 "
              "fits on Edge; T02 is offloaded to Fog because Edge would be 100% loaded; T03 is low urgency so it "
              "goes to Cloud; T04 needs 20 CPUs, more than Edge or Fog have, and Cloud's 80 ms network delay "
              "already exceeds its 25 ms deadline, so it is rejected.")


def policy_slide(prs, e1) -> None:
    """Slide 4: E1 policy comparison as a native stacked bar chart with callouts."""
    s = _slide(prs, WHITE)
    rows = {r[0]: r for r in e1.tables[0][2]}
    total = sum(rows["Latency-First"][1:4])
    _title(s, f"Smart policies run 0 late; baselines run {rows['Latency-First'][2]} and "
              f"{rows['Cloud-Only'][2]} of {total} late")
    data = CategoryChartData()
    labels = list(rows)[::-1]
    data.categories = labels
    for name, col, color in (("On time", 1, GOOD), ("Late", 2, WARN), ("Rejected", 3, BAD)):
        data.add_series(name, [rows[label][col] or None for label in labels])  # None: no "0" label
    frame = s.shapes.add_chart(XL_CHART_TYPE.BAR_STACKED, Inches(0.6), Inches(1.5), Inches(8.0), Inches(5.3), data)
    chart = frame.chart
    chart.has_legend = True
    chart.legend.position = XL_LEGEND_POSITION.TOP
    chart.legend.include_in_layout = False
    chart.legend.font.size, chart.legend.font.name = Pt(13), BODY
    plot = chart.plots[0]
    plot.gap_width = 60
    plot.has_data_labels = True
    plot.data_labels.position = XL_LABEL_POSITION.CENTER
    plot.data_labels.font.size, plot.data_labels.font.name = Pt(13), BODY
    plot.data_labels.font.color.rgb = RGBColor.from_string(WHITE)
    for series, color in zip(plot.series, (GOOD, WARN, BAD)):
        series.format.fill.solid()
        series.format.fill.fore_color.rgb = RGBColor.from_string(color)
    chart.category_axis.tick_labels.font.size = chart.value_axis.tick_labels.font.size = Pt(13)
    chart.value_axis.has_major_gridlines = False
    chart.value_axis.visible = False
    workload = e1.setup[0].replace("Workload: ", "")
    _stat(s, str(rows["Capacity-Aware"][2]), "late with Capacity-Aware", Inches(9.0), Inches(1.6), GOOD)
    _stat(s, str(rows["Latency-First"][2]), "late with Latency-First", Inches(9.0), Inches(3.3), BAD)
    _text(s, workload, Inches(9.0), Inches(5.2), Inches(3.8), Inches(1.0), 12, MUTED)
    _notes(s, f"E1: {workload} Each policy starts from empty nodes. Capacity-Aware and TOPSIS check the deadline "
              "before placing, so they reject what they cannot finish in time instead of running it late.")


def stress_slide(prs, e2, e3, e4) -> None:
    """Slide 6: E2 overload, E3 unauthorised access and E4 node changes as three cards."""
    s = _slide(prs, WHITE)
    _title(s, "Overload, security and node changes behave as expected")
    width, gap, top, height = Inches(3.85), Inches(0.29), Inches(1.4), Inches(5.6)
    xs = [Inches(0.6) + (width + gap) * i for i in range(3)]

    rows = {r[0]: r for r in e2.tables[0][2]}
    cap, lf = rows["Capacity-Aware"], rows["Latency-First"]
    x = xs[0]
    _card(s, x, top, width, height)
    _text(s, "E2 · Overload", x + Inches(0.25), top + Inches(0.15), Inches(3.4), Inches(0.5), 20, INK, bold=True,
          font=HEAD)
    _text(s, "Edge already 90% busy, then 10 urgent tasks", x + Inches(0.25), top + Inches(0.7), Inches(3.4),
          Inches(0.6), 13, MUTED)
    for i, (value, label, color) in enumerate(((cap[4], "offloaded", TIER["fog"]),
                                               (cap[3], "rejected", BAD), (cap[2], "late", GOOD))):
        _stat(s, str(value), label, x + Inches(0.25) + Inches(1.15) * i, top + Inches(1.35), color,
              width=Inches(1.1), size=36)
    _text(s, "Offloaded tasks went to Fog in time; every rejection names the check that failed.\n"
             f"Latency-First on the same burst: {lf[1]} on time, {lf[2]} late.\n"
             "No node is ever allocated beyond its capacity.", x + Inches(0.25), top + Inches(2.75), Inches(3.4),
          Inches(2.4), 14, INK)

    x = xs[1]
    _card(s, x, top, width, height)
    _text(s, "E3 · Unauthorised access", x + Inches(0.25), top + Inches(0.15), Inches(3.4), Inches(0.5), 20, INK,
          bold=True, font=HEAD)
    actor = e3.quotes[0].split(" → ")[0]
    _text(s, f"{actor} tries another tenant's task and VM", x + Inches(0.25), top + Inches(0.7), Inches(3.4),
          Inches(0.6), 13, MUTED)
    attempts = [q.split(" → ")[1].split(":")[0] for q in e3.quotes if " → " in q and "ACCESS DENIED" in q]
    y = top + Inches(1.4)
    for attempt in attempts:
        _pill(s, "DENIED", x + Inches(0.25), y)
        _text(s, attempt, x + Inches(1.5), y + Inches(0.06), Inches(2.2), Inches(0.4), 14, INK)
        y += Inches(0.6)
    _text(s, "Each refusal is one line in the CSV audit log. The VM keeps running; the admin can still read both "
             "records.", x + Inches(0.25), top + Inches(3.3), Inches(3.4), Inches(1.6), 14, INK)

    x = xs[2]
    _card(s, x, top, width, height)
    _text(s, "E4 · Node changes", x + Inches(0.25), top + Inches(0.15), Inches(3.4), Inches(0.5), 20, INK,
          bold=True, font=HEAD)
    _text(s, "Same 20 tasks, one node changed at a time", x + Inches(0.25), top + Inches(0.7), Inches(3.4),
          Inches(0.6), 13, MUTED)
    y = top + Inches(1.35)
    for title, _, table_rows in e4.tables:
        change = title.split(": ", 1)[1]
        metrics = {r[0]: r for r in table_rows}
        lines = [f"on time {metrics['on time'][1]} → {metrics['on time'][2]}",
                 f"rejected {metrics['rejected'][1]} → {metrics['rejected'][2]}"]
        if "cpu_cores" in change:
            lines.append(f"tasks on edge {metrics['tasks on edge'][1]} → {metrics['tasks on edge'][2]}")
        else:
            lines.append(f"avg latency {metrics['avg latency ms'][1]} → {metrics['avg latency ms'][2]} ms")
        _text(s, change, x + Inches(0.25), y, Inches(3.4), Inches(0.4), 15, NAVY, bold=True)
        _text(s, "\n".join(lines), x + Inches(0.25), y + Inches(0.42), Inches(3.4), Inches(1.0), 14, INK)
        y += Inches(1.75)
    _notes(s, "E2 is the overload scenario: with Edge already 90% busy, Capacity-Aware moves tasks to Fog when "
              "Fog can still meet the deadline and rejects, with a reason, those no node can finish in time; "
              "Latency-First keeps using Edge and runs almost all of them late. E3 is the unauthorised access "
              "attempt: every read or stop of another tenant's records is refused and logged. E4 changes one "
              "node at a time: doubling Edge CPU lets more urgent tasks run on Edge, while making Cloud 150 ms "
              "away pushes medium tasks, whose deadline is 100 ms, off the Cloud.")


def conclusion_slide(prs, run: ExperimentRun) -> None:
    """Slide 7: takeaways, limitations and how to run it."""
    s = _slide(prs, NAVY)
    _tier_dots(s, Inches(0.8), Inches(0.75), Inches(0.3))
    _text(s, "What we learned", Inches(0.8), Inches(1.2), Inches(6), Inches(0.7), 32, WHITE, bold=True, font=HEAD)
    held = sum(h for e in run.experiments for _, h in e.checks)
    total = sum(len(e.checks) for e in run.experiments)
    _bullets(s, [f"All 4 experiments matched their expected outcome ({held}/{total} checks)",
                 "Checking the deadline before placing beats placing on the nearest node",
                 "Shared tenant VMs and one access rule keep tenants apart",
                 "Every number is a setting; runs are repeatable from settings_used.json"],
             Inches(0.8), Inches(2.05), Inches(6.0), Inches(3.6), WHITE)
    _text(s, "Limitations", Inches(7.3), Inches(1.2), Inches(5.3), Inches(0.7), 32, WHITE, bold=True, font=HEAD)
    _bullets(s, ["No task duration or arrival time; tasks run until their VM stops",
                 "Latency is a formula, not a measurement",
                 "Greedy, one task at a time; GA/PSO or Q-learning could do better",
                 "No VM migration; login is a tenant id by design"],
             Inches(7.3), Inches(2.05), Inches(5.4), Inches(3.6), "CADCFC")
    _text(s, "Try it:  python -m edgefogsim   ·   python -m edgefogsim web   ·   python run_experiments.py",
          Inches(0.8), Inches(6.3), Inches(11.8), Inches(0.5), 15, WHITE)
    _notes(s, "Close with the takeaways, then the limitations; offer a live demo of the menu or the Streamlit app.")


def _slide(prs, background: str):
    """A blank slide with a solid background colour."""
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = RGBColor.from_string(background)
    return slide


def _title(slide, text: str) -> None:
    """The slide title, same place and style on every content slide (kept to one line)."""
    _text(slide, text, Inches(0.6), Inches(0.45), Inches(12.1), Inches(0.8), 28, INK, bold=True, font=HEAD)


def _text(slide, text: str, x, y, w, h, size: float, color: str, bold: bool = False, font: str = BODY,
          align=PP_ALIGN.LEFT):
    """A word-wrapped text box; ``\\n`` starts a new paragraph."""
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    for i, line in enumerate(text.split("\n")):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        paragraph.alignment = align
        run = paragraph.add_run()
        run.text = line
        run.font.size, run.font.bold, run.font.name = Pt(size), bold, font
        run.font.color.rgb = RGBColor.from_string(color)
    return box


def _bullets(slide, items: list[str], x, y, w, h, color: str) -> None:
    """A bulleted list (real bullets, 18 pt, spaced paragraphs)."""
    box = slide.shapes.add_textbox(x, y, w, h)
    frame = box.text_frame
    frame.word_wrap = True
    for i, item in enumerate(items):
        paragraph = frame.paragraphs[0] if i == 0 else frame.add_paragraph()
        paragraph.space_after = Pt(10)
        properties = paragraph._p.get_or_add_pPr()
        properties.set("marL", str(Emu(Inches(0.3))))
        properties.set("indent", str(-Emu(Inches(0.3))))
        bullet = properties.makeelement("{http://schemas.openxmlformats.org/drawingml/2006/main}buChar",
                                        {"char": "•"})
        properties.append(bullet)
        run = paragraph.add_run()
        run.text = item
        run.font.size, run.font.name = Pt(18), BODY
        run.font.color.rgb = RGBColor.from_string(color)


def _terms(slide, rows: list[tuple[str, str]], x, y, symbol_width=Inches(0.55)) -> None:
    """A two-column legend for a formula: each term in bold, then what it means."""
    for symbol, meaning in rows:
        _text(slide, symbol, x, y, symbol_width, Inches(0.32), 14, NAVY, bold=True, font=HEAD)
        _text(slide, meaning, x + symbol_width, y + Inches(0.02), Inches(7.0) - symbol_width, Inches(0.32), 13, INK)
        y += Inches(0.3)


def _card(slide, x, y, w, h) -> None:
    """A tinted rounded rectangle behind a block of content."""
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, w, h)
    shape.adjustments[0] = 0.05
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(CARD)
    shape.line.fill.background()
    shape.shadow.inherit = False


def _stat(slide, value: str, label: str, x, y, color: str, width=Inches(3.8), size: float = 60) -> None:
    """A big number with a small label under it."""
    _text(slide, value, x, y, width, Inches(1.0), size, color, bold=True, font=HEAD)
    _text(slide, label, x, y + Inches(0.95 if size >= 60 else 0.75), width, Inches(0.6), 14, MUTED)


def _circle_number(slide, n: int, x, y) -> None:
    """A numbered navy circle (the step markers)."""
    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, x, y, Inches(0.5), Inches(0.5))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(NAVY)
    shape.line.fill.background()
    shape.shadow.inherit = False
    frame = shape.text_frame
    frame.margin_left = frame.margin_right = frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = str(n)
    run.font.size, run.font.bold, run.font.name = Pt(16), True, BODY
    run.font.color.rgb = RGBColor.from_string(WHITE)


def _pill(slide, text: str, x, y) -> None:
    """A small red rounded label, e.g. DENIED."""
    shape = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, x, y, Inches(1.1), Inches(0.4))
    shape.fill.solid()
    shape.fill.fore_color.rgb = RGBColor.from_string(BAD)
    shape.line.fill.background()
    shape.shadow.inherit = False
    frame = shape.text_frame
    frame.margin_top = frame.margin_bottom = 0
    frame.vertical_anchor = MSO_ANCHOR.MIDDLE
    paragraph = frame.paragraphs[0]
    paragraph.alignment = PP_ALIGN.CENTER
    run = paragraph.add_run()
    run.text = text
    run.font.size, run.font.bold, run.font.name = Pt(12), True, BODY
    run.font.color.rgb = RGBColor.from_string(WHITE)


def _tier_dots(slide, x, y, size) -> None:
    """The deck's motif: three circles in the Edge, Fog and Cloud colours."""
    for i, tier in enumerate(("edge", "fog", "cloud")):
        dot = slide.shapes.add_shape(MSO_SHAPE.OVAL, x + int(size * 1.35) * i, y, size, size)
        dot.fill.solid()
        dot.fill.fore_color.rgb = RGBColor.from_string(TIER[tier])
        dot.line.fill.background()
        dot.shadow.inherit = False


def _table(slide, rows: list[list], x, y, w, widths: list, size: float = 14) -> None:
    """A table with a navy header row."""
    shape = slide.shapes.add_table(len(rows), len(rows[0]), x, y, w, Inches(0.42) * len(rows))
    table = shape.table
    for j, width in enumerate(widths):
        table.columns[j].width = width
    for i, row in enumerate(rows):
        for j, value in enumerate(row):
            cell = table.cell(i, j)
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string(NAVY if i == 0 else WHITE)
            frame = cell.text_frame
            frame.paragraphs[0].text = ""
            run = frame.paragraphs[0].add_run()
            run.text = str(value)
            run.font.size, run.font.name, run.font.bold = Pt(size), BODY, i == 0
            run.font.color.rgb = RGBColor.from_string(WHITE if i == 0 else INK)


def _notes(slide, text: str) -> None:
    """Speaker notes for the slide."""
    slide.notes_slide.notes_text_frame.text = text


if __name__ == "__main__":
    sys.exit(main())
