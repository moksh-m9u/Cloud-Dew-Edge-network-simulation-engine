"""Streamlit app: the browser interface, alongside the command-line menu in ``cli``.

Start it with ``python -m edgefogsim web`` (it accepts the same options as the
menu, e.g. ``--seed 7``). Like the menu, it holds no simulation logic: every
page reads input, calls the engine modules and shows the result.

Streamlit re-runs this whole script on every click, so everything that must
survive a click (settings, tasks, who is logged in) lives in
``st.session_state``. Widgets have fixed keys so tests can drive them with
Streamlit's ``AppTest`` (see ``tests/test_web.py``).
"""

import json
import os
import sys
import tempfile
from dataclasses import asdict
from pathlib import Path

# Project root; added to sys.path because `streamlit run` only adds this file's folder.
# (Constants here use comments, not docstrings: Streamlit would print bare strings on the page.)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402  (must follow the sys.path fix above)
import streamlit as st  # noqa: E402

from edgefogsim.__main__ import WEB_ARGS_ENV, build_parser, prepare  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402

from edgefogsim import charts  # noqa: E402
from edgefogsim.config import (  # noqa: E402
    NODE_EDITABLE,
    ConfigError,
    Settings,
    describe_settings,
    load_settings,
    parse_value,
    set_node_value,
    set_value,
    settings_as_json,
)
from edgefogsim.models import SENSITIVITIES, Node, Tenant  # noqa: E402
from edgefogsim.policies import POLICIES, CapacityAware  # noqa: E402
from edgefogsim.qos import latency_breakdown  # noqa: E402
from edgefogsim.security import AccessDenied, AuditLog, find_task, find_vm, visible  # noqa: E402
from edgefogsim.results import (  # noqa: E402
    decisions_table,
    export_before_after,
    export_comparison,
    export_run,
    new_export_dir,
    summary_table,
)
from edgefogsim.simulator import (  # noqa: E402
    BeforeAfter,
    RunResult,
    compare_before_after,
    compare_policies,
    create_vm,
    empty_cluster,
    fresh_nodes,
    run_workload,
    submit,
)
from edgefogsim.workload import generate_tasks, load_tasks, make_task  # noqa: E402

# Pages in the sidebar, in order. Home is shown first and to anyone not logged in.
PAGES = ("Home", "Nodes", "Workload", "Placement", "VMs", "Security", "Results", "Settings")

# What you do on each page, for the Home page's step-by-step guide.
GUIDE = [
    ("Nodes", "See the Edge, Fog and Cloud computers: their size, network distance, speed and how busy they are."),
    ("Workload", "Create tasks: generate random ones (the same seed gives the same tasks), upload a CSV or JSON "
                 "file, or add one by hand."),
    ("Placement", "Pick a policy and run it. Every task gets a node, or is rejected, with the reason. Or compare "
                  "all four policies on the same tasks."),
    ("VMs", "See the virtual machines your tasks run in. Create one ahead of time, stop one to free its node, or "
            "place a single task now."),
    ("Security", "Look up a task or VM by id. Another tenant's records are refused (ACCESS DENIED) and logged."),
    ("Results", "Charts and CSV/JSON downloads. The admin can also change a node and compare before/after, and "
                "run the four experiments."),
    ("Settings", "Every number the simulator uses, where it came from, and a form to change it."),
]

# The "next step" buttons at the bottom of each page: (page to open, button label).
NEXT_STEPS = {
    "Nodes": [("Workload", "Build a workload")],
    "Workload": [("Placement", "Run a placement policy")],
    "Placement": [("Results", "See charts and export"), ("VMs", "Look at the VMs")],
    "VMs": [("Security", "Try the security check"), ("Placement", "Back to placement")],
    "Security": [("Results", "See the results")],
    "Results": [("Settings", "Change a setting"), ("Home", "Back to Home")],
    "Settings": [("Placement", "Run placement again"), ("Home", "Back to Home")],
}

# Sample task file offered on the Workload page.
SAMPLE_TASKS = ROOT / "examples" / "tasks_sample.csv"


def init_state() -> None:
    """Load settings and the starting workload once per browser session.

    Options given to ``python -m edgefogsim web`` arrive as a JSON list in the
    ``EDGEFOGSIM_ARGS`` environment variable and are parsed exactly as the menu
    parses them. A settings error is shown on the page and stops the app.
    """
    if "settings" in st.session_state:
        return
    options = json.loads(os.environ.get(WEB_ARGS_ENV, "[]"))
    try:
        settings, tasks = prepare(build_parser().parse_args(["web", *options]))
    except ConfigError as exc:
        st.error(f"Settings error: {exc}")
        st.stop()
    st.session_state.settings = settings
    st.session_state.tasks = tasks
    st.session_state.last_run = None
    st.session_state.comparison = None
    st.session_state.before_after = None


def sidebar(settings: Settings) -> tuple[Tenant | None, str, "st.delta_generator.DeltaGenerator"]:
    """Draw the login box and page picker.

    Args:
        settings: Current settings; supplies the list of tenants.

    Returns:
        The logged-in tenant (None until one is chosen), the selected page name,
        and an empty sidebar slot for the task count, filled in after the page
        runs so it reflects any change the page just made.
    """
    st.sidebar.title("EdgeFogSim")
    st.sidebar.caption("Edge / Fog / Cloud placement simulator")
    tenant_ids = [t.tenant_id for t in settings.tenants]
    chosen = st.sidebar.selectbox("Log in as", tenant_ids, index=None, placeholder="Choose a tenant", key="login")
    user = settings.tenant(chosen) if chosen else None
    if user:
        st.sidebar.success(f"Logged in as **{user.tenant_id}** ({user.role})")
    page = st.sidebar.radio("Page", PAGES, key="page")
    return user, page, st.sidebar.empty()


def go_to(page: str) -> None:
    """Button callback: switch the sidebar's page selection (applied before the next run draws it)."""
    st.session_state.page = page


def next_steps(page: str) -> None:
    """Draw the "next step" buttons at the bottom of a page.

    Args:
        page: The page being shown; its entry in ``NEXT_STEPS`` decides the buttons.
    """
    steps = NEXT_STEPS.get(page)
    if not steps:
        return
    st.divider()
    st.caption("Next step")
    for column, (target, label) in zip(st.columns(3), steps):
        column.button(f"{label} →", key=f"next_{page}_{target}", on_click=go_to, args=(target,), width="stretch")


def quick_start() -> None:
    """Button callback: load the sample tasks, run every policy on them, and open the Placement page."""
    settings = st.session_state.settings
    tasks = load_tasks(SAMPLE_TASKS, settings)
    st.session_state.tasks = tasks
    st.session_state.comparison = compare_policies(settings, tasks)
    st.session_state.last_run = run_workload(settings, tasks, "capacity")
    st.session_state.page = "Placement"


def home_page(settings: Settings, user: Tenant | None) -> None:
    """The start page: what the simulator is, a quick start, a step-by-step guide and how it works.

    Args:
        settings: Current settings; every number shown is read from them.
        user: Who is logged in, or None (the guide's buttons then stay disabled until login).
    """
    st.title("EdgeFogSim")
    st.markdown("#### Where should a computing task run: on a small **Edge** node next to the user, a **Fog** "
                "node nearby, or the big **Cloud** far away?")
    st.write("Nearby nodes answer fast but are small; the cloud is huge but far away. EdgeFogSim simulates that "
             "decision. You create tasks, a placement policy picks a node for each one, the task runs in a "
             "virtual machine there, and you see how long it took, whether it met its deadline, and how busy "
             "every node got. Nothing runs on real servers: every computer, task and VM is data in the program.")
    if user is None:
        st.info("Choose who you are in the sidebar to start. **hospital-a** and **hospital-b** are tenants: each "
                "sees only their own tasks and VMs. **admin** sees everything and can change nodes.")

    columns = st.columns(len(settings.nodes))
    for column, node in zip(columns, settings.nodes):
        column.metric(f"{node.tier.capitalize()} · {node.id}", f"{node.cpu_cores:g} CPU")
        column.caption(f"{node.memory_gb:g} GB · {node.base_latency_ms:g} ms away · speed {node.speed_factor:g}")

    st.subheader("Quick start")
    st.write("Load the 10 sample tasks, run all four placement policies on them, and jump straight to the "
             "decisions and the comparison.")
    st.button("Load the sample tasks and compare policies →", key="quick_start", type="primary",
              on_click=quick_start, disabled=user is None)

    st.subheader("How to use it")
    for number, (page, what) in enumerate(GUIDE, start=1):
        text, button = st.columns([6, 1])
        text.markdown(f"**{number}. {page}**: {what}")
        button.button("Open", key=f"open_{page}", on_click=go_to, args=(page,), disabled=user is None,
                      width="stretch")

    st.subheader("How it works")
    tiers, latency, policies, vms, security, experiments = st.tabs(
        ["Edge, Fog and Cloud", "Latency formula", "Placement policies", "Virtual machines", "Security",
         "Experiments"])
    with tiers:
        _home_tiers(settings)
    with latency:
        _home_latency(settings)
    with policies:
        _home_policies(settings)
    with vms:
        _home_vms(settings)
    with security:
        _home_security(settings)
    with experiments:
        _home_experiments()


def _home_tiers(settings: Settings) -> None:
    """Home tab: the three tiers and the trade-off between them."""
    st.write("Each tier trades distance against size. Edge is your own kitchen: instant, but one stove. Fog is "
             "the café down the street. Cloud is the chain's central kitchen across the city: huge, but far.")
    good_for = {"edge": "urgent, small tasks", "fog": "medium tasks that still need to be quick",
                "cloud": "big tasks that can wait a moment"}
    st.dataframe(pd.DataFrame([{
        "Tier": n.tier.capitalize(), "Node": n.id, "CPU cores": n.cpu_cores, "Memory (GB)": n.memory_gb,
        "Network delay (ms)": n.base_latency_ms, "Speed": n.speed_factor, "Good for": good_for.get(n.tier, ""),
    } for n in settings.nodes]), hide_index=True, width="stretch")
    st.caption("Change any node in config/nodes.json, with --nodes my_nodes.json, or (admin) on the Results page.")


def _home_latency(settings: Settings) -> None:
    """Home tab: the latency and congestion formulas, what each term means, and a worked example."""
    qos = settings.simulation["qos"]
    deadlines = qos["deadlines_ms"]
    st.write("For every task and candidate node, the simulator estimates the delay **L** before placing it:")
    st.latex(r"L \;=\; d \;+\; \frac{W}{s} \times C")
    st.latex(r"C \;=\; \frac{1}{1 - \min(u,\ " + f"{qos['congestion_cap']:g}" + r")}")
    st.latex(r"u \;=\; \frac{\text{CPU in use} + \text{task CPU}}{\text{node CPU cores}}")
    nodes = settings.nodes
    work = settings.simulation["generator"]["work_range"]
    st.markdown(f"""
| Term | Meaning | Default values |
|---|---|---|
| **L** | Latency: time from sending the task to getting the answer (ms) | result of the formula |
| **d** | Network delay to reach the node (ms) | {", ".join(f"{n.tier} {n.base_latency_ms:g}" for n in nodes)} |
| **W** | Work units: how much processing the task needs | high {work["high"][0]}–{work["high"][1]}, medium {work["medium"][0]}–{work["medium"][1]}, low {work["low"][0]}–{work["low"][1]} |
| **s** | Node speed (Fog = 1, so W ÷ s is processing time in ms) | {", ".join(f"{n.tier} {n.speed_factor:g}" for n in nodes)} |
| **C** | Congestion: how much a busy node slows work down | 1 when idle, 2 at half load, 10 at 90% load |
| **u** | CPU load on the node after placing the task (0 to 1) | capped at {qos["congestion_cap"]:.0%} so C stays finite |
| **D** | Deadline, set by the task's sensitivity (ms) | high {deadlines["high"]:g}, medium {deadlines["medium"]:g}, low {deadlines["low"]:g} |
""")
    st.write("A task **succeeds** if it is placed and **L ≤ D**. Congestion is a simple queueing (M/M/1-style) "
             "model: like a queue at a counter, a nearly full node gets slow very fast.")
    task = load_tasks(SAMPLE_TASKS, settings)[0]
    edge = next(n for n in fresh_nodes(settings) if n.tier == "edge")
    b = latency_breakdown(task, edge, settings)
    st.markdown(f"""**Worked example**: sample task {task.id} ({task.cpu_cores:g} CPU, W = {task.work_units:g}, {task.sensitivity} sensitivity) on an empty {edge.id}:

- u = (0 + {task.cpu_cores:g}) ÷ {edge.cpu_cores:g} = **{b["load_after"]:g}**
- C = 1 ÷ (1 − {b["load_after"]:g}) = **{b["congestion"]:g}**
- L = {b["network_ms"]:g} + ({b["work_units"]:g} ÷ {b["speed"]:g}) × {b["congestion"]:g} = {b["network_ms"]:g} + {b["processing_ms"]:.2f} × {b["congestion"]:g} = **{b["latency_ms"]:.1f} ms**
- D = {b["deadline_ms"]:g} ms, so {b["latency_ms"]:.1f} {"≤" if b["latency_ms"] <= b["deadline_ms"] else ">"} {b["deadline_ms"]:g}: **{"on time" if b["latency_ms"] <= b["deadline_ms"] else "late"}**
""")


def _home_policies(settings: Settings) -> None:
    """Home tab: the four policies, the Capacity-Aware rules and its score formula with an example."""
    policy = settings.simulation["policy"]
    w = policy["capacity_weights"]
    st.dataframe(pd.DataFrame([{"Policy": p.label, "Key": key, "How it decides": p.summary}
                               for key, p in POLICIES.items()]), hide_index=True, width="stretch")
    st.markdown(f"""**Capacity-Aware** is the rule-based algorithm the brief asks for:

1. **Prefer tiers by urgency**: high → Edge, Fog, Cloud · medium → Fog, Edge, Cloud · low → Cloud, Fog, Edge.
2. **Rule out** nodes that can't host the task (no room in a VM or for a new one), would pass {policy["headroom"]:.0%} CPU load, or would miss the deadline.
3. **Score** every node left (formula below) and place the task on the highest score. If that isn't its first-choice tier, it's an **offload**.
4. If nothing passes, retry once allowing nodes up to 100% load; if still nothing, **reject** with the reason.
""")
    st.latex(r"S \;=\; " + f"{w['tier']:g}" + r"\,T \;+\; " + f"{w['slack']:g}" + r"\,\frac{D - L}{D} \;+\; "
             + f"{w['free']:g}" + r"\,(1 - u)")
    st.markdown("""
| Term | Meaning |
|---|---|
| **S** | Score of a node for this task; the highest wins |
| **T** | Tier preference: 1 for the first-choice tier, 0.5 for the second, 0 for the third |
| **(D − L) ÷ D** | Share of the deadline left over: more spare time scores higher |
| **1 − u** | Share of the node's CPU left free after placing the task: emptier nodes score higher |
| weights | How much each part counts; change them in Settings (policy.capacity_weights) |
""")
    task = load_tasks(SAMPLE_TASKS, settings)[0]
    choice = CapacityAware(settings).choose(task, fresh_nodes(settings))
    ranking = ", ".join(f"{node} **{score:.2f}**" for node, score in sorted(choice.scores.items(),
                                                                          key=lambda kv: -kv[1]))
    st.write(f"Example: for sample task {task.id} on empty nodes the scores are {ranking}, so it goes to "
             f"**{choice.node.id}**. **TOPSIS** instead ranks the nodes that meet the deadline by how close they "
             "are to an ideal node on latency, free CPU and free memory.")


def _home_vms(settings: Settings) -> None:
    """Home tab: shared tenant VMs and the two kinds of node usage."""
    sizes = settings.simulation["vm"]["sizes"]
    st.markdown(f"""A **VM** is a slice of one node, owned by one tenant. When a task is placed on a node it **joins** one of its tenant's VMs there if that VM has room; otherwise a **new VM** is created, sized to the tier's default ({", ".join(f"{t} {s['cpu_cores']:g} CPU / {s['memory_gb']:g} GB" for t, s in sizes.items())}) or to the task if it's bigger. Tenants never share a VM.

Each node therefore shows two numbers: **reserved** (CPU held by VMs, which decides whether a new VM fits) and **load** (CPU actually used by tasks, which drives latency). An empty VM reserves room but doesn't slow anything down. Stopping a VM frees its whole slice, so a task rejected earlier may now fit: try it on the **VMs** page.
""")


def _home_security(settings: Settings) -> None:
    """Home tab: tenant isolation and the audit log."""
    st.markdown(f"""Logging in means choosing a tenant id: no passwords exist anywhere, as the brief requires. One rule decides access: **a tenant may see and act on their own tasks and VMs; the admin may see and act on everything.**

Lists simply hide other tenants' rows. Asking for another tenant's record by id (looking it up, stopping its VM, placing its task) is refused with **ACCESS DENIED** and written to the audit log (`{settings.get("security.audit_log")}`). Try it on the **Security** page while logged in as hospital-b, with task T01.
""")


def _home_experiments() -> None:
    """Home tab: the four required experiments."""
    st.markdown("""
| Experiment | Question | What it shows |
|---|---|---|
| **E1** Policy comparison | Is the rule-based policy better? | The same 20 tasks through all four policies: the deadline-aware ones run nothing late |
| **E2** Overload | What happens when a node is full? | Edge 90% busy, then 10 urgent tasks: they are moved to Fog or rejected with a reason |
| **E3** Unauthorised access | Can one tenant see another's data? | Every attempt is refused and logged; the admin can still read it |
| **E4** Node change | What if a node gets bigger or slower? | More Edge CPU helps; a slower Cloud pushes medium tasks out |

Each one states its expected outcome first and checks it against the actual numbers. The admin can run all four on the **Results** page, or run `python run_experiments.py`.
""")


def nodes_page(settings: Settings) -> None:
    """Show the nodes: their usage after the last placement run, or empty if nothing has run.

    Args:
        settings: Current settings; supplies the node definitions.
    """
    st.header("Nodes")
    run: RunResult | None = st.session_state.last_run
    if run:
        st.caption(f"Usage after the last run ({run.label}, {len(run.decisions)} tasks).")
        nodes_table(run.nodes)
    else:
        st.caption("Nothing placed yet. Run a policy on the Placement page to see usage.")
        nodes_table(settings.nodes)
    st.caption("Edit nodes in config/nodes.json or start with --nodes my_nodes.json. "
               "Node editing in the app arrives with the before/after comparison (Phase 4).")


def nodes_table(nodes: list[Node]) -> None:
    """Draw a table of nodes with size, usage, latency, speed and a CPU utilisation bar.

    Args:
        nodes: The nodes to show.
    """
    rows = [{
        "Node": n.id,
        "Tier": n.tier,
        "CPU reserved / cores": f"{n.cpu_used:g} / {n.cpu_cores:g}",
        "GB reserved / total": f"{n.memory_used:g} / {n.memory_gb:g}",
        "Latency (ms)": n.base_latency_ms,
        "Speed": n.speed_factor,
        "Reserved": n.cpu_util,
        "Load": n.load_util,
    } for n in nodes]
    bar = {c: st.column_config.ProgressColumn(c, min_value=0, max_value=1, format="percent") for c in ("Reserved", "Load")}
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", column_config=bar)
    st.caption("Reserved = CPU held by VMs (decides if a new VM fits). Load = CPU used by tasks (drives latency).")


def placement_page(settings: Settings, user: Tenant) -> None:
    """Run a policy on the workload and show the decisions, or compare all policies.

    Args:
        settings: Current settings; policies read deadlines, headroom and weights from it.
        user: Who is logged in; a tenant sees only their own tasks' decisions
            (totals and node usage are cluster-wide).
    """
    st.header("Placement")
    tasks = st.session_state.tasks
    if not tasks:
        st.info("No tasks yet. Build a workload on the Workload page first.")
        return
    keys = list(POLICIES)
    key = st.selectbox("Policy", keys, index=keys.index("capacity"), key="policy",
                       format_func=lambda k: POLICIES[k].label)
    st.caption(POLICIES[key].summary)
    col1, col2 = st.columns(2)
    if col1.button(f"Run {POLICIES[key].label} on {len(tasks)} tasks", key="run_placement", type="primary"):
        st.session_state.last_run = run_workload(settings, tasks, key)
    if col2.button("Compare all policies", key="compare"):
        st.session_state.comparison = compare_policies(settings, tasks)

    comparison: list[RunResult] | None = st.session_state.comparison
    if comparison:
        st.subheader("Policy comparison")
        _stale_warning(comparison[0], tasks)
        rows = []
        for r in comparison:
            m = r.summary()
            rows.append({"Policy": r.label, "On time": m["on_time"], "Late": m["late"], "Rejected": m["rejected"],
                         "Offloaded": m["offloaded"], "Success": m["success_rate"],
                         "Avg ms": m["avg_latency_ms"], "P95 ms": m["p95_latency_ms"],
                         **{f"{n.id} util": m[f"{n.id} util"] for n in r.nodes}})
        frame = pd.DataFrame(rows)
        for column in frame.columns:
            if column == "Success" or column.endswith(" util"):
                frame[column] = (frame[column] * 100).round()
        percent = {c: st.column_config.NumberColumn(c, format="%d%%")
                   for c in frame.columns if c == "Success" or c.endswith(" util")}
        decimals = {c: st.column_config.NumberColumn(c, format="%.1f") for c in ("Avg ms", "P95 ms")}
        st.dataframe(frame, hide_index=True, width="stretch", column_config={**percent, **decimals})
        st.bar_chart(frame.set_index("Policy")[["On time", "Late", "Rejected"]],
                     color=list(charts.OUTCOME_COLORS.values()), stack=True, horizontal=True)

    run: RunResult | None = st.session_state.last_run
    if run:
        st.subheader(f"Decisions: {run.label}")
        _stale_warning(run, tasks)
        m = run.summary()
        cols = st.columns(6)
        cols[0].metric("Tasks", m["total"])
        cols[1].metric("On time", m["on_time"])
        cols[2].metric("Late", m["late"])
        cols[3].metric("Rejected", m["rejected"])
        cols[4].metric("Offloaded", m["offloaded"])
        cols[5].metric("Success", f"{m['success_rate']:.0%}")
        columns = ["task", "tenant", "sensitivity", "node", "vm", "new_vm", "latency_ms", "deadline_ms", "outcome",
                   "offloaded", "reason", "cpu_cores", "memory_gb", "work_units"]
        rows = visible(user, run.rows(), lambda r: r["tenant"])
        hidden = len(run.decisions) - len(rows)
        if hidden:
            st.caption(f"Showing your {len(rows)} tasks; {hidden} decisions for other tenants are hidden. "
                       "Totals above are cluster-wide.")
        if rows:
            st.dataframe(pd.DataFrame(rows)[columns], hide_index=True, width="stretch",
                         column_config={"reason": st.column_config.TextColumn("reason", width="large")})
        st.caption(f"Average latency {_ms(m['avg_latency_ms'])} ms, p95 {_ms(m['p95_latency_ms'])} ms "
                   "(over placed tasks). Offloaded = placed outside the task's first-choice tier.")
        st.subheader("Nodes after this run")
        nodes_table(run.nodes)


def vms_page(settings: Settings, user: Tenant) -> None:
    """List the user's VMs; create or stop one; or place one task now (it joins or creates a VM).

    Args:
        settings: Current settings; used when placing a single task.
        user: Who is logged in; a tenant sees and stops only their own VMs.
    """
    st.header("Virtual machines")
    run: RunResult | None = st.session_state.last_run
    vms = visible(user, run.vms.vms) if run else []
    if vms:
        st.dataframe(pd.DataFrame([{"VM": vm.vm_id, "Tenant": vm.tenant_id, "Node": vm.node_id,
                                    "CPU used / size": f"{vm.cpu_load:g} / {vm.cpu_cores:g}",
                                    "GB used / size": f"{vm.memory_load:g} / {vm.memory_gb:g}",
                                    "Tasks": ", ".join(vm.task_ids) or "-", "Status": vm.status} for vm in vms]),
                     hide_index=True, width="stretch")
        st.caption("A VM is a slice of its node owned by one tenant; that tenant's tasks run inside it while it has room.")
    else:
        st.info("No VMs yet. Run a policy on the Placement page, or create a VM or place one task below.")

    st.subheader("Create a VM")
    nodes = run.nodes if run else settings.nodes
    owners = [t.tenant_id for t in settings.tenants if t.role == "tenant" and (user.is_admin or t == user)]
    with st.form("create_vm"):
        col1, col2, col3, col4 = st.columns(4)
        node_id = col1.selectbox("Node", [n.id for n in nodes], key="vm_node")
        owner = col2.selectbox("Owner", owners, key="vm_owner")
        tier = next(n.tier for n in nodes if n.id == node_id)
        size = settings.simulation["vm"]["sizes"][tier]
        cpu = col3.number_input("CPU cores", min_value=0.5, value=float(size["cpu_cores"]), step=0.5, key="vm_cpu")
        memory = col4.number_input("Memory (GB)", min_value=0.5, value=float(size["memory_gb"]), step=0.5,
                                   key="vm_memory")
        if st.form_submit_button("Create VM"):
            if run is None:
                run = st.session_state.last_run = empty_cluster(settings)
            try:
                vm = create_vm(run, owner, node_id, cpu, memory)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.success(f"Created {vm.vm_id} for {owner} on {node_id} ({cpu:g} CPU / {memory:g} GB).")
                st.rerun()

    running = [vm.vm_id for vm in vms if vm.running]
    st.subheader("Stop a VM")
    col1, col2 = st.columns([3, 1])
    vm_id = col1.selectbox("Running VM", running, index=None, placeholder="Choose a VM", key="stop_vm_id")
    if col2.button("Stop VM", key="stop_vm", disabled=vm_id is None):
        vm = run.vms.get(vm_id)
        run.stop_vm(vm_id)
        node = run.vms.node(vm.node_id)
        st.success(f"Stopped {vm_id} ({', '.join(vm.task_ids) or 'no tasks'}). Freed {vm.cpu_cores:g} CPU and "
                   f"{vm.memory_gb:g} GB on {node.id}, now {node.cpu_util:.0%} reserved.")

    st.subheader("Place one task now")
    st.caption("Places a task on the cluster as it is now, e.g. a task that was rejected before you freed room.")
    has_vm = {task_id for vm in run.vms.running() for task_id in vm.task_ids} if run else set()
    candidates = [t.id for t in visible(user, st.session_state.tasks) if t.id not in has_vm]
    col1, col2, col3 = st.columns([2, 2, 1])
    task_id = col1.selectbox("Task", candidates, index=None, placeholder="Choose a task", key="place_task_id")
    keys = list(POLICIES)
    key = col2.selectbox("Policy", keys, index=keys.index("capacity"), key="place_policy",
                         format_func=lambda k: POLICIES[k].label)
    if col3.button("Place", key="place_one", disabled=task_id is None):
        if run is None:
            run = st.session_state.last_run = empty_cluster(settings, key)
        task = next(t for t in st.session_state.tasks if t.id == task_id)
        decision = submit(run, task, key, settings)
        message = (f"{task_id}: {decision.outcome} on {decision.node_id} as {decision.vm_id}" if decision.placed
                   else f"{task_id}: rejected")
        (st.success if decision.outcome == "on time" else st.warning)(f"{message}. Why: {decision.reason}")

    if run:
        st.subheader("Nodes now")
        nodes_table(run.nodes)


def security_page(settings: Settings, user: Tenant) -> None:
    """Look up a task or VM by id (another tenant's is refused and logged) and show the audit log.

    Args:
        settings: Current settings; supplies the audit log path.
        user: Who is logged in.
    """
    st.header("Security")
    st.write("A tenant can see only their own tasks and VMs; an admin can see everything. "
             "Try looking up another tenant's task here.")
    audit = AuditLog(settings.get("security.audit_log"))
    col1, col2 = st.columns([3, 1])
    record_id = col1.text_input("Task or VM id", placeholder="e.g. T05 or vm-0002", key="lookup_id").strip()
    if col2.button("Look up", key="lookup", disabled=not record_id):
        run: RunResult | None = st.session_state.last_run
        try:
            if record_id.lower().startswith("vm-"):
                if run is None:
                    raise KeyError(f"no VM '{record_id}'")
                vm = find_vm(user, record_id, run.vms, audit)
                st.success(f"{vm.vm_id}: {vm.tenant_id}'s VM on {vm.node_id}, {vm.cpu_cores:g} CPU / "
                           f"{vm.memory_gb:g} GB, running tasks: {', '.join(vm.task_ids) or 'none'}, {vm.status}")
            else:
                task = find_task(user, record_id, st.session_state.tasks, audit)
                st.success(f"{task.id}: {task.tenant_id}, {task.cpu_cores:g} CPU, {task.memory_gb:g} GB, "
                           f"{task.sensitivity} sensitivity, {task.work_units:g} work units")
        except KeyError as exc:
            st.error(exc.args[0])
        except AccessDenied as exc:
            st.error(f"🔒 {exc}")
            st.caption(f"Recorded in {audit.path}.")

    st.subheader("Audit log" if user.is_admin else "Your refused attempts")
    entries = audit.entries(viewer=user)
    if entries:
        st.dataframe(pd.DataFrame(entries), hide_index=True, width="stretch")
    else:
        st.caption("No refused attempts yet.")


def workload_page(settings: Settings, user: Tenant) -> None:
    """Build the workload (generate, upload or add by hand) and show it.

    Args:
        settings: Current settings; supplies generator defaults and tenants.
        user: Who is logged in; a tenant adding a task owns it by default.
    """
    st.header("Workload")
    generate_tab, upload_tab, add_tab = st.tabs(["Generate", "Upload a file", "Add a task"])
    gen = settings.simulation["generator"]

    with generate_tab:
        col1, col2 = st.columns(2)
        count = col1.number_input("How many tasks", min_value=1, value=gen["count"], step=1, key="gen_count")
        seed = col2.number_input("Seed", value=gen["seed"], step=1, key="gen_seed")
        if st.button("Generate (replaces the workload)", key="generate", type="primary"):
            st.session_state.tasks = generate_tasks(settings, count=int(count), seed=int(seed))
            st.success(f"Generated {int(count)} tasks with seed {int(seed)}.")

    with upload_tab:
        uploaded = st.file_uploader("CSV or JSON task file", type=["csv", "json"], key="task_file")
        col1, col2 = st.columns(2)
        if col1.button("Load uploaded file", key="load_upload", disabled=uploaded is None):
            _load_task_file(_save_upload(uploaded), settings)
        if col2.button("Load the sample file", key="load_sample"):
            _load_task_file(SAMPLE_TASKS, settings)
        st.caption("Columns: id, tenant_id, cpu_cores, memory_gb, sensitivity, work_units. Leave id blank to number automatically.")

    with add_tab:
        # A tenant may only add tasks for themselves; an admin may add for anyone.
        owners = [t.tenant_id for t in settings.tenants if t.role == "tenant" and (user.is_admin or t == user)]
        with st.form("add_task", clear_on_submit=True):
            task_id = st.text_input("Task id (blank = automatic)", key="add_id")
            owner = st.selectbox("Tenant", owners, index=owners.index(user.tenant_id) if user.tenant_id in owners else 0,
                                 key="add_tenant")
            col1, col2, col3 = st.columns(3)
            cpu = col1.number_input("CPU cores", min_value=0.1, value=1.0, step=0.5, key="add_cpu")
            memory = col2.number_input("Memory (GB)", min_value=0.1, value=1.0, step=0.5, key="add_memory")
            work = col3.number_input("Work units", min_value=0.1, value=5.0, step=1.0, key="add_work")
            sensitivity = st.selectbox("Sensitivity", SENSITIVITIES, key="add_sensitivity")
            if st.form_submit_button("Add task"):
                raw = {"id": task_id, "tenant_id": owner, "cpu_cores": cpu, "memory_gb": memory,
                       "sensitivity": sensitivity, "work_units": work}
                try:
                    task = make_task(raw, settings, existing=st.session_state.tasks)
                except ConfigError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.tasks = [*st.session_state.tasks, task]
                    st.success(f"Added {task.id}.")

    tasks = st.session_state.tasks
    mine = visible(user, tasks)
    st.subheader(f"Tasks ({len(tasks)})" if user.is_admin else f"Your tasks ({len(mine)} of {len(tasks)})")
    if not tasks:
        st.info("No tasks yet. Generate, upload or add some above.")
        return
    if not user.is_admin:
        st.caption("Other tenants' tasks are hidden.")
    if mine:
        st.dataframe(pd.DataFrame([asdict(t) for t in mine]), hide_index=True, width="stretch")
    if st.button("Clear all tasks", key="clear_tasks"):
        st.session_state.tasks = []
        st.rerun()


def settings_page(settings: Settings) -> None:
    """Show every setting with its source; change one, download all, or apply a settings file.

    Args:
        settings: Current settings; changed in place by edits.
    """
    st.header("Settings")
    rows = describe_settings(settings)
    st.dataframe(
        pd.DataFrame([{"Setting": p, "Value": json.dumps(v), "From": s} for p, v, s in rows]),
        hide_index=True,
        width="stretch",
    )

    st.subheader("Change a setting")
    with st.form("change_setting"):
        path = st.selectbox("Setting", [p for p, _, _ in rows], key="setting_path")
        value = st.text_input("New value (JSON, e.g. 40, true, [1, 4])", key="setting_value")
        if st.form_submit_button("Apply"):
            try:
                set_value(settings, path, parse_value(value.strip()), source="web app")
            except ConfigError as exc:
                st.error(str(exc))
            else:
                st.success(f"{path} = {parse_value(value.strip())!r}")
                st.rerun()

    st.subheader("Save or load")
    st.download_button("Download settings (JSON)", settings_as_json(settings), file_name="my_settings.json",
                       mime="application/json", key="download_settings")
    uploaded = st.file_uploader("Apply a settings file (same format as --config)", type=["json"], key="settings_file")
    if uploaded is not None and st.button("Apply settings file", key="apply_settings"):
        path = _save_upload(uploaded)
        try:
            st.session_state.settings = load_settings(config_file=path)
        except ConfigError as exc:
            st.error(_tidy(str(exc), path))
        else:
            st.success(f"Applied {uploaded.name} on top of the defaults.")
            st.rerun()


def main() -> None:
    """Render the app: sidebar, then the selected page (login required)."""
    st.set_page_config(page_title="EdgeFogSim", layout="wide")
    init_state()
    settings = st.session_state.settings
    user, page, task_count = sidebar(settings)
    if user is None or page == "Home":
        home_page(settings, user)
    elif page == "Nodes":
        nodes_page(settings)
    elif page == "Workload":
        workload_page(settings, user)
    elif page == "Placement":
        placement_page(settings, user)
    elif page == "VMs":
        vms_page(settings, user)
    elif page == "Security":
        security_page(settings, user)
    elif page == "Results":
        results_page(settings, user)
    else:
        settings_page(st.session_state.settings)
    if user is not None:
        next_steps(page)
    task_count.caption(f"{len(st.session_state.tasks)} tasks loaded")


def results_page(settings: Settings, user: Tenant) -> None:
    """Charts and exports for the last run and comparison, plus the admin's before/after node change.

    Args:
        settings: Current settings; supplies ``output.dir`` and is changed if a node change is kept.
        user: Who is logged in; a tenant's exports contain only their own decisions and VMs.
    """
    st.header("Results")
    run: RunResult | None = st.session_state.last_run
    comparison: list[RunResult] | None = st.session_state.comparison
    if not run and not comparison:
        st.info("Nothing to show yet. Run a policy or compare policies on the Placement page.")

    if comparison:
        st.subheader("Policy comparison")
        st.dataframe(summary_table(comparison), hide_index=True, width="stretch")
        col1, col2 = st.columns(2)
        _show(col1, charts.outcomes_chart(comparison))
        _show(col2, charts.tiers_chart(comparison))
        _show(st, charts.latency_chart(comparison))
        col1, col2 = st.columns(2)
        col1.download_button("Download comparison.csv", summary_table(comparison).to_csv(index=False),
                             file_name="comparison.csv", mime="text/csv", key="dl_comparison")
        if col2.button("Save comparison to results folder", key="save_comparison"):
            folder = new_export_dir(settings, "comparison")
            export_comparison(comparison, settings, folder)
            charts.save_comparison_charts(comparison, folder)
            st.success(f"Saved to {folder}/")

    if run and run.decisions:
        st.subheader(f"Last run: {run.label}")
        col1, col2 = st.columns(2)
        _show(col1, charts.node_usage_chart(run))
        _show(col2, charts.latency_chart([run]))
        col1, col2, col3 = st.columns(3)
        col1.download_button("Download decisions.csv", decisions_table(run, user).to_csv(index=False),
                             file_name="decisions.csv", mime="text/csv", key="dl_decisions")
        col2.download_button("Download summary.json", json.dumps({"policy": run.label, **run.summary()}, indent=2),
                             file_name="summary.json", mime="application/json", key="dl_summary")
        if col3.button("Save run to results folder", key="save_run"):
            folder = new_export_dir(settings, run.policy)
            export_run(run, settings, folder, viewer=user)
            charts.save_run_charts(run, folder)
            st.success(f"Saved to {folder}/")

    st.subheader("Run all four experiments")
    if user.is_admin:
        st.caption("Runs E1-E4 from config/experiments.json and writes experiments.md plus evidence to the "
                   "results folder. Your workload and nodes are not changed.")
        if st.button("Run experiments", key="run_experiments"):
            from edgefogsim.experiments import load_experiments, run_all, summary_frame

            try:
                run_exp = run_all(settings, load_experiments())
            except ConfigError as exc:
                st.error(str(exc))
            else:
                st.dataframe(summary_frame(run_exp), hide_index=True, width="stretch")
                st.success(f"Write-up: {run_exp.report}")
                st.download_button("Download experiments.md", run_exp.report.read_text(), file_name="experiments.md",
                                   mime="text/markdown", key="dl_experiments")
    else:
        st.caption("Only the admin can run the experiments.")

    st.subheader("Change a node and compare before / after")
    if not user.is_admin:
        st.caption("Only the admin can change nodes.")
        return
    if not st.session_state.tasks:
        st.caption("Build a workload first.")
        return
    with st.form("before_after_form"):
        col1, col2, col3, col4 = st.columns(4)
        node_id = col1.selectbox("Node", [n.id for n in settings.nodes], key="ba_node")
        key = col2.selectbox("Field", NODE_EDITABLE, key="ba_field")
        current = getattr(next(n for n in settings.nodes if n.id == node_id), key)
        value = col3.number_input("New value", min_value=0.0, value=float(current) * 2, step=1.0, key="ba_value")
        keys = list(POLICIES)
        policy = col4.selectbox("Policy", keys, index=keys.index("capacity"), key="ba_policy",
                                format_func=lambda k: POLICIES[k].label)
        if st.form_submit_button("Compare"):
            try:
                st.session_state.before_after = compare_before_after(
                    settings, st.session_state.tasks, policy, {node_id: {key: value}})
                st.session_state.before_after_key = (node_id, key, value)
            except ConfigError as exc:
                st.error(str(exc))
    result: BeforeAfter | None = st.session_state.before_after
    if result:
        st.dataframe(pd.DataFrame(result.diff()), hide_index=True, width="stretch")
        _show(st, charts.before_after_chart(result.before, result.after, result.change))
        col1, col2 = st.columns(2)
        if col1.button("Save before/after to results folder", key="save_before_after"):
            folder = new_export_dir(settings, "before-after")
            export_before_after(result, settings, folder)
            charts.save_before_after_chart(result.before, result.after, result.change, folder)
            st.success(f"Saved to {folder}/")
        if col2.button("Keep this change", key="keep_change"):
            node_id, key, value = st.session_state.before_after_key
            set_node_value(settings, node_id, key, value, source="web app")
            st.session_state.last_run = result.after
            st.success(f"Kept: {result.change}. Later runs use the changed node.")


def _show(where, fig) -> None:
    """Draw a matplotlib figure in the app, then free it."""
    where.pyplot(fig)
    plt.close(fig)


def _stale_warning(run: RunResult, tasks: list) -> None:
    """Warn if the workload has changed since ``run`` was made."""
    if run.tasks != tasks:
        st.warning("The workload has changed since this run. Run it again to update.")


def _ms(value: float | None) -> str:
    """Format milliseconds to one decimal, or "-" when there is no value."""
    return "-" if value is None else f"{value:.1f}"


def _save_upload(uploaded) -> Path:
    """Write an uploaded file to a temporary folder under its original name and return the path."""
    path = Path(tempfile.mkdtemp(prefix="edgefogsim-")) / uploaded.name
    path.write_bytes(uploaded.getvalue())
    return path


def _load_task_file(path: Path, settings: Settings) -> None:
    """Replace the workload with a task file's tasks, showing the result or the row error."""
    try:
        st.session_state.tasks = load_tasks(path, settings)
    except ConfigError as exc:
        st.error(_tidy(str(exc), path))
    else:
        st.success(f"Loaded {len(st.session_state.tasks)} tasks from {path.name}.")


def _tidy(message: str, path: Path) -> str:
    """Show just the file name instead of its full (often temporary) path in an error message."""
    return message.replace(str(path), path.name)


main()
