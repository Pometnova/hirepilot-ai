"""Dashboard numbers. FREE: no model call. The funnel and task numbers are cross-checked against evals/build_expected.py,
which reads only data/raw, so the dashboard is not graded by the services it combines."""
import json

import pytest
from streamlit.testing.v1 import AppTest

from backend import config
from backend.agent import core
from backend.services import analytics, funnel
from evals import build_expected
from web import dashboard, theme

EXP = build_expected.build()
D = analytics.dashboard()
APP = str(config.ROOT / "web" / "app.py")


def test_kpis_add_up_to_the_roles():
    k = D["kpis"]
    assert k["applications"] == sum(r["applications"] for r in D["roles"]) == 45
    assert k["applications"] == k["active"] + k["hired"] + k["rejected"] + k["withdrawn"]
    assert k["open_roles"] == 3 and k["hired"] == 1
    assert k["hire_rate"] == round(1 / 45, 3)


def test_funnel_numbers_match_the_raw_files():
    for job_id, f in D["funnels"].items():
        for s in f["stages"]:
            e = EXP["funnel"][job_id][s["stage"]]
            assert (s["entered"], s["moved_on"], s["rejected"], s["withdrew"], s["hired"], s["still_in_stage"]) == \
                   (e["entered"], e["moved_on"], e["rejected"], e["withdrew"], e["hired"], e["still_there"]), (job_id, s["stage"])
            assert s["entered"] == s["moved_on"] + s["rejected"] + s["withdrew"] + s["hired"] + s["still_in_stage"]


def test_biggest_loss_is_the_stage_with_most_rejected_plus_withdrew():
    for job_id, f in D["funnels"].items():
        lost = {st: v["rejected"] + v["withdrew"] for st, v in EXP["funnel"][job_id].items()}
        top = max(lost.values())
        if top == 0:
            assert f["biggest_loss"] is None
        else:
            assert lost[f["biggest_loss"]["stage"]] == top and f["biggest_loss"]["lost"] == top
    assert D["funnels"]["j-backend"]["biggest_loss"] == {"stage": "Take-Home", "lost": 5, "entered": 11}


def test_task_counts_and_overdue_list_match_the_raw_files():
    exp = {t["task_id"]: t["state"] for t in EXP["tasks"]}
    c = D["tasks"]["counts"]
    assert c["overdue"] == sum(v == "overdue" for v in exp.values()) == 5
    assert c["due_today"] == sum(v == "due_today" for v in exp.values()) == 1
    assert c["pending"] + c["pending_no_due_date"] == sum(v.startswith("pending") for v in exp.values())
    assert {t["task_id"] for t in D["tasks"]["overdue"]} == {k for k, v in exp.items() if v == "overdue"}
    days = [t["days_overdue"] for t in D["tasks"]["overdue"]]
    assert days == sorted(days, reverse=True) and all(d > 0 for d in days)
    assert D["kpis"]["open_tasks"] == len(exp) == 11


def test_issue_counts_are_consistent():
    i = D["issues"]
    assert i["total"] == sum(i["by_severity"].values()) == sum(i["by_type"].values()) == D["kpis"]["data_issues"]


def test_a_failing_service_gives_a_safe_error(monkeypatch):
    monkeypatch.setattr(funnel, "get_funnel", lambda job_id: {"ok": False, "error": {"code": "internal_error", "message": "x"}})
    with pytest.raises(analytics.AnalyticsError) as e:
        analytics.dashboard()
    assert "internal_error" in str(e.value) and "Traceback" not in str(e.value)


# ---------- the Overview page in the real app (AppTest, no API) ----------
def start(page="Overview"):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["page"] = page
    return at.run()


def chart_specs(at):
    """The Plotly figures on the page, as dicts, in page order: roles, funnel, dwell, tasks, severity, issue types."""
    return [json.loads(e.proto.spec) for e in at.get("plotly_chart")]


def test_overview_renders_kpis_positions_and_plotly_charts():
    at = start()
    assert not at.exception
    assert [b.label for b in at.sidebar.button if b.key.startswith("nav-")] == ["Overview", "Ask AI", "Candidates", "Tasks"]
    labels = {m.label: m.value for m in at.metric}
    assert labels == {"Overdue tasks": "05", "Pending scorecards": "05", "Unanswered emails": "02", "Upcoming offer deadlines": "00"}   # row 1 only
    text = " ".join(m.value for m in at.markdown)
    for r in D["roles"]:                                                                              # Open Positions: applicants, active, hired per role
        assert r["title"] in text and f"{r['applications']} applicants" in " ".join(c.value for c in at.caption)
        assert f"**{r['active']}** active · **{r['hired']}** hired" in text
    assert [e.key for e in at.get("plotly_chart")] == ["chart-funnel", "chart-dwell", "chart-exits", "chart-cov-cvs",
                                                       "chart-cov-recruiter-emails", "chart-cov-submitted-scorecards", "chart-roles"]
    assert len(at.get("vega_lite_chart")) == 0


def test_the_charts_on_the_page_show_the_real_numbers():
    specs = chart_specs(start())
    funnel = next(sp for sp in specs if sp["data"][0]["y"] == list(EXP["funnel"]["j-backend"]))
    assert funnel["data"][0]["x"] == [v["entered"] for v in EXP["funnel"]["j-backend"].values()]       # pipeline order, raw-file counts
    tasks = next(sp for sp in chart_specs(start("Tasks")) if sp["data"][0]["y"] == ["Overdue", "Due today", "Pending", "Pending, no due date"])
    assert tasks["data"][0]["x"] == [5, 1, 2, 3]                                                      # now on the Tasks page


def test_role_picker_switches_the_funnel():
    at = start()
    box = at.selectbox(key="dash-role")
    assert box.value == "j-backend"
    at = box.select("j-csm").run()
    assert not at.exception
    funnel = next(sp for sp in chart_specs(at) if sp["data"][0]["y"] == list(EXP["funnel"]["j-csm"]))
    assert funnel["data"][0]["x"] == [v["entered"] for v in EXP["funnel"]["j-csm"].values()]
    assert any("Largest drop-off" in m.value for m in at.markdown)                                      # warning line is on the page
    assert any("Recruitment Funnel — Customer Success Manager" in m.value for m in at.markdown)


def test_dashboard_failure_shows_a_friendly_message(monkeypatch):
    monkeypatch.setattr(analytics, "dashboard", lambda: (_ for _ in ()).throw(RuntimeError("boom secret")))
    dashboard.load.clear()
    at = start()
    text = " ".join(e.value for e in at.error)
    assert "could not be built" in text and "boom" not in text and "secret" not in text
    dashboard.load.clear()


# ---------- figure builders (pure functions) ----------
CORAL, PURPLE = theme.CORAL, theme.PURPLE


def test_funnel_figure_is_in_pipeline_order_and_marks_the_largest_dropoff_in_coral():
    for job_id, f in D["funnels"].items():
        fig = dashboard.funnel_figure(f)
        bar = fig.data[0]
        assert list(bar.y) == list(EXP["funnel"][job_id]) and list(bar.x) == [v["entered"] for v in EXP["funnel"][job_id].values()]
        big = f["largest_dropoff"]["to_stage"] if f["largest_dropoff"] else None
        assert [c == CORAL for c in bar.marker.color] == [s == big for s in bar.y]                       # only the largest drop-off is coral
        assert all(c in (CORAL, PURPLE) for c in bar.marker.color)
        assert fig.layout.yaxis.autorange == "reversed"                                                  # first stage on top
        notes = {a.y: a.font.color for a in fig.layout.annotations if a.yref == "y"}                     # drop-off % right of each bar
        assert set(notes) == set(bar.y) and all((c == CORAL) == (st == big) for st, c in notes.items())  # coral % only at the largest drop-off
    hover = dashboard.funnel_figure(D["funnels"]["j-backend"]).data[0].hovertemplate
    assert "Reached" in hover and "Still in progress" in hover and "Rejected here" in hover and "Withdrew here" in hover


def test_dwell_figure_marks_the_slowest_stage_and_skips_stages_with_no_value():
    f = D["funnels"]["j-backend"]
    bar = dashboard.dwell_figure(f).data[0]
    assert "Offer" not in bar.y                                                                           # nobody has left the last stage
    slowest = max(bar.x)
    assert [c == CORAL for c in bar.marker.color] == [v == slowest for v in bar.x]
    assert "based on" in bar.hovertemplate


def test_other_figures_use_the_theme_and_the_same_numbers():
    roles = dashboard.roles_figure(D["roles"])
    assert [sum(t.x[i] for t in roles.data) for i in range(3)] == [r["applications"] for r in D["roles"]]
    assert list(dashboard.tasks_figure(D["tasks"]["counts"]).data[0].x) == [5, 1, 2, 3]
    dwell = dashboard.dwell_figure(D["funnels"]["j-backend"])
    for fig in (roles, dwell, dashboard.funnel_figure(D["funnels"]["j-backend"]), dashboard.tasks_figure(D["tasks"]["counts"])):
        assert fig.layout.font.family == theme.FONT and fig.layout.paper_bgcolor == "rgba(0,0,0,0)"


# ---------- Stage 1.1: aligned charts, readable labels ----------
def all_figures():
    f = D["funnels"]["j-backend"]
    return {"roles": dashboard.roles_figure(D["roles"]), "funnel": dashboard.funnel_figure(f), "dwell": dashboard.dwell_figure(f),
            "tasks": dashboard.tasks_figure(D["tasks"]["counts"])}


def test_every_chart_has_the_same_height_top_bottom_margins_and_coral_hover():
    figs = all_figures()
    assert {fig.layout.height for fig in figs.values()} == {theme.CHART_HEIGHT}
    assert len({(fig.layout.margin.t, fig.layout.margin.b, fig.layout.margin.l) for fig in figs.values()}) == 1     # funnel only has a wider right margin for the % column
    assert figs["funnel"].layout.margin.r > figs["dwell"].layout.margin.r
    assert all(fig.layout.hoverlabel.bordercolor == theme.CORAL for fig in figs.values())


def test_value_labels_have_room_so_the_longest_bar_is_not_clipped():
    figs = all_figures()
    for name in ("funnel", "dwell", "tasks"):
        rng = figs[name].layout.xaxis.range
        top = max(figs[name].data[0].x)
        assert rng[0] == 0 and rng[1] >= (1.04 if name == "funnel" else 1.15) * top, (name, rng, top)      # funnel labels sit inside the bars
    assert max(figs["dwell"].data[0].x) == 24.0                                                          # the label that used to be cut
    assert figs["funnel"].data[0].textangle == 0                                                         # labels are never rotated


def test_overview_charts_sit_in_cards():
    import inspect
    src = inspect.getsource(dashboard)
    assert src.count("card(") >= 4 and 'card("dwell"' in src and 'card("roles"' in src and 'card("stalled"' in src
    assert 'st.container(key="card-tall-funnel")' in src and 'st.container(key="card-tall-exits")' in src         # row 3: three tall cards
    assert 'st.container(key="card-wide-health")' in src and 'st.container(key="card-wide-quality")' in src   # row 4: Data Health Check + Data Quality
    assert "def card(" in src and 'st.container(key=f"card-' in src
