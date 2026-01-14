import os
import time
from typing import Any, Dict, List, Tuple

import requests
from dash import Dash, dcc, html, dash_table
from dash.dependencies import Input, Output
import plotly.graph_objects as go


# ---------------------------
# Configuration
# ---------------------------

# Coordinator base URL (can be overridden via env var).
COORDINATOR_URL = os.getenv("COORDINATOR_URL", "http://127.0.0.1:8000")

# How many last blocks to fetch and visualize.
CHAIN_LIMIT = int(os.getenv("CHAIN_LIMIT", "50"))

# Refresh interval in milliseconds (Dash will call callbacks periodically).
REFRESH_MS = int(os.getenv("REFRESH_MS", "1000"))

# ---------------------------
# In-memory time series buffer (dashboard-side)
# ---------------------------
# We keep a small history of rejected_total to compute a reject rate over time.
REJECT_SERIES_MAX_POINTS = int(os.getenv("REJECT_SERIES_MAX_POINTS", "300"))
_reject_series: List[Tuple[float, int]] = []  # (timestamp_s, rejected_total)

# Dashboard start time (used to show "seconds since start" on the X axis).
DASH_START_S = time.time()

# Track accepted_total as well (needed for reject ratio over time).
ACCEPT_SERIES_MAX_POINTS = int(os.getenv("ACCEPT_SERIES_MAX_POINTS", "300"))
_accept_series: List[Tuple[float, int]] = []  # (t_rel_s, blocks_accepted)


def _card_style() -> Dict[str, Any]:
    """
    Simple card styling for summary metrics.
    """
    return {
        "flex": "1 1 220px",
        "minWidth": "220px",
        "border": "1px solid #ddd",
        "borderRadius": "10px",
        "padding": "10px 12px",
        "backgroundColor": "#fafafa",
    }


def make_card(title: str, value: str, subtitle: str = "") -> html.Div:
    """
    Build a small metric card component.
    """
    return html.Div(
        children=[
            html.Div(title, style={"fontSize": "12px", "color": "#555"}),
            html.Div(value, style={"fontSize": "24px", "fontWeight": "bold"}),
            html.Div(subtitle, style={"fontSize": "12px", "color": "#777"}) if subtitle else html.Div(),
        ]
    )

# ---------------------------
# Helper functions (HTTP + data)
# ---------------------------

def fetch_json(url: str, timeout: int = 5) -> Dict[str, Any]:
    """
    Small helper to GET JSON from an endpoint.
    Returns an empty dict on errors to keep the dashboard resilient.
    """
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


def fetch_metrics() -> Dict[str, Any]:
    """
    Fetch /metrics from the coordinator.
    """
    return fetch_json(f"{COORDINATOR_URL}/metrics")


def fetch_chain(limit: int) -> Dict[str, Any]:
    """
    Fetch /chain snapshot from the coordinator.
    """
    return fetch_json(f"{COORDINATOR_URL}/chain?limit={limit}")


def compute_block_times(chain_blocks: List[Dict[str, Any]]) -> List[Tuple[int, int]]:
    """
    Compute block time deltas (accepted_timestamp_ms differences) from a list of blocks.

    Returns a list of tuples: (height, delta_ms) for heights >= 2 blocks in the window.
    """
    if not chain_blocks or len(chain_blocks) < 2:
        return []

    # Sort by height just in case.
    blocks = sorted(chain_blocks, key=lambda b: b["height"])
    out: List[Tuple[int, int]] = []

    for i in range(1, len(blocks)):
        prev_ts = blocks[i - 1]["accepted_timestamp_ms"]
        cur_ts = blocks[i]["accepted_timestamp_ms"]
        delta = cur_ts - prev_ts
        out.append((blocks[i]["height"], delta))

    return out

def normalize_reject_reason(reason: str) -> str:
    """
    Map verbose reject reasons to compact categories for plotting/reporting.
    """
    if not reason:
        return "other"
    r = reason.lower()
    if "wrong height" in r:
        return "wrong_height"
    if "prev_hash" in r:
        return "prev_hash_mismatch"
    if "invalid pow" in r:
        return "invalid_pow"
    return "other"


# ---------------------------
# Dash app
# ---------------------------

app = Dash(__name__)
app.title = "Distributed Mining Monitor - Dashboard"

app.layout = html.Div(
    style={"fontFamily": "Arial", "maxWidth": "1200px", "margin": "0 auto", "padding": "16px"},
    children=[
        html.H2("Distributed Mining Monitor", style={"marginBottom": "4px"}),
        html.Div(
            children=[
                html.Div(f"Coordinator: {COORDINATOR_URL}", style={"color": "#555"}),
                html.Div(f"Auto-refresh: {REFRESH_MS} ms", style={"color": "#555"}),
            ],
            style={"marginBottom": "12px"},
        ),

        # Periodic trigger (no UI)
        dcc.Interval(id="tick", interval=REFRESH_MS, n_intervals=0),

        # Top summary cards
        html.Div(
            style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "12px"},
            children=[
                html.Div(id="card-height", style=_card_style()),
                html.Div(id="card-rejected", style=_card_style()),
                html.Div(id="card-reject-ratio", style=_card_style()),
                html.Div(id="card-uptime", style=_card_style()),
            ],
        ),

        # Charts row
        html.Div(
            style={"display": "flex", "gap": "12px", "flexWrap": "wrap"},
            children=[
                html.Div(
                    style={"flex": "1 1 580px", "minWidth": "360px"},
                    children=[
                        html.H4("Block time (last blocks)", style={"marginBottom": "4px"}),
                        dcc.Graph(id="graph-block-time", config={"displayModeBar": False},style={"height": "360px"}),
                    ],
                ),
                html.Div(
                    style={"flex": "1 1 580px", "minWidth": "360px"},
                    children=[
                        html.H4("Accepted blocks by miner", style={"marginBottom": "4px"}),
                        dcc.Graph(id="graph-accepted-by-miner", config={"displayModeBar": False},style={"height": "360px"}),
                    ],
                ),
            ],
        ),
        
        # Charts row (2)
        html.Div(
            style={"marginTop": "12px"},
            children=[
                html.H4("Reject rate over time", style={"marginBottom": "4px"}),
                dcc.Graph(
                    id="graph-reject-rate",
                    config={"displayModeBar": False},
                    style={"height": "360px"},
                ),
            ],
        ),
        
        # Charts row (3)
        html.Div(
            style={"marginTop": "12px"},
            children=[
                html.H4("Reject ratio over time", style={"marginBottom": "4px"}),
                dcc.Graph(
                    id="graph-reject-ratio",
                    config={"displayModeBar": False},
                    style={"height": "360px"},
                ),
            ],
        ),


        html.H4("Last blocks", style={"marginTop": "16px", "marginBottom": "6px"}),

        # Blocks table
        dash_table.DataTable(
            id="table-blocks",
            columns=[
                {"name": "height", "id": "height"},
                {"name": "miner_id", "id": "miner_id"},
                {"name": "hash", "id": "block_hash_short"},
                {"name": "prev_hash", "id": "prev_hash_short"},
                {"name": "nonce", "id": "nonce"},
                {"name": "accepted_ts", "id": "accepted_timestamp_ms"},
            ],
            data=[],
            page_size=15,
            style_table={"overflowX": "auto"},
            style_cell={
                "fontFamily": "Arial",
                "fontSize": "13px",
                "padding": "6px",
                "whiteSpace": "nowrap",
            },
            style_header={"fontWeight": "bold"},
        ),

        # Status line for errors / no data
        html.Div(id="status-line", style={"marginTop": "10px", "color": "#777"}),
    ],
)


# ---------------------------
# Callbacks (refresh UI)
# ---------------------------

@app.callback(
    Output("card-height", "children"),
    Output("card-rejected", "children"),
    Output("card-reject-ratio", "children"),
    Output("card-uptime", "children"),
    Output("graph-block-time", "figure"),
    Output("graph-accepted-by-miner", "figure"),
    Output("graph-reject-rate", "figure"),
    Output("graph-reject-ratio", "figure"),
    Output("table-blocks", "data"),
    Output("status-line", "children"),
    Input("tick", "n_intervals"),
)
def refresh(_n: int):
    """
    Periodically refresh dashboard by pulling data from the coordinator endpoints.
    """
    metrics = fetch_metrics()
    chain_view = fetch_chain(CHAIN_LIMIT)

    # If coordinator is unreachable, return placeholders (must match Output order).
    if not metrics or not chain_view or "blocks" not in chain_view:
        empty = go.Figure()
        empty.update_layout(height=360, autosize=False, margin=dict(l=30, r=10, t=10, b=30))

        return (
            make_card("Chain height", "—", "Coordinator not reachable"),
            make_card("Rejected total", "—"),
            make_card("Reject ratio", "—"),
            make_card("Uptime", "—"),
            empty,  # block time
            empty,  # accepted by miner
            empty,  # reject rate
            empty,  # reject ratio
            [],     # table
            f"Waiting for coordinator at {COORDINATOR_URL} ...",
        )

    # ---------------------------
    # Read metrics (convert counters to int for safe arithmetic)
    # ---------------------------
    height = int(metrics.get("height", 0))
    blocks_accepted = int(metrics.get("blocks_accepted", 0))
    rejected_total = int(metrics.get("rejected_total", 0))
    uptime_ms = int(metrics.get("uptime_ms", 0))

    card_height = make_card("Chain height", str(height), "Tip height")
    card_rejected = make_card("Rejected total", str(rejected_total), "Stale work / invalid submissions")
    card_uptime = make_card("Uptime", f"{uptime_ms/1000:.1f}s", f"{uptime_ms} ms")

    # ---------------------------
    # Update dashboard-side time series (single append per tick)
    # ---------------------------
    t_rel = time.time() - DASH_START_S  # seconds since dashboard start

    global _reject_series, _accept_series
    _reject_series.append((t_rel, rejected_total))
    _accept_series.append((t_rel, blocks_accepted))

    # Keep bounded history
    if len(_reject_series) > REJECT_SERIES_MAX_POINTS:
        _reject_series = _reject_series[-REJECT_SERIES_MAX_POINTS:]
    if len(_accept_series) > ACCEPT_SERIES_MAX_POINTS:
        _accept_series = _accept_series[-ACCEPT_SERIES_MAX_POINTS:]

    # ---------------------------
    # Chain blocks and derived values
    # ---------------------------
    blocks = chain_view["blocks"]

    # --- Block time chart ---
    bt = compute_block_times(blocks)  # list of (height, delta_ms)
    fig_block_time = go.Figure()
    if bt:
        x = [h for (h, _dt) in bt]
        y = [_dt for (_h, _dt) in bt]
        fig_block_time.add_trace(go.Scatter(x=x, y=y, mode="lines+markers", name="block_time_ms"))
    fig_block_time.update_layout(
        height=360, autosize=False,
        margin=dict(l=30, r=10, t=10, b=30),
        xaxis_title="Block height",
        yaxis_title="Δ accepted_timestamp (ms)",
    )

    # --- Accepted by miner bar chart ---
    accepted_by_miner = metrics.get("accepted_by_miner", {}) or {}
    miners = list(accepted_by_miner.keys())
    counts = [int(accepted_by_miner[m]) for m in miners]

    fig_accepted = go.Figure()
    fig_accepted.add_trace(go.Bar(x=miners, y=counts, name="accepted"))
    fig_accepted.update_layout(
        height=360, autosize=False,
        margin=dict(l=30, r=10, t=10, b=30),
        xaxis_title="Miner",
        yaxis_title="Accepted blocks",
    )

    # --- Reject rate over time ---
    rate_x: List[float] = []
    rate_y: List[float] = []
    if len(_reject_series) >= 2:
        for i in range(1, len(_reject_series)):
            t0, r0 = _reject_series[i - 1]
            t1, r1 = _reject_series[i]
            dt = max(t1 - t0, 1e-6)
            dr = r1 - r0
            rate_x.append(t1)
            rate_y.append(dr / dt)  # rejects per second

    fig_reject_rate = go.Figure()
    if rate_x:
        fig_reject_rate.add_trace(go.Scatter(x=rate_x, y=rate_y, mode="lines+markers", name="reject/s"))
    fig_reject_rate.update_layout(
        height=360, autosize=False,
        margin=dict(l=30, r=10, t=10, b=30),
        xaxis_title="Time (seconds since dashboard start)",
        yaxis_title="Rejects / second",
    )

    # --- Reject ratio over time (cumulative total) ---
    ratio_x: List[float] = []
    ratio_y: List[float] = []

    n = min(len(_reject_series), len(_accept_series))
    for i in range(n):
        t, r = _reject_series[i]
        _, a = _accept_series[i]
        denom = r + a
        ratio = (r / denom) if denom > 0 else 0.0
        ratio_x.append(t)
        ratio_y.append(ratio)

    fig_reject_ratio = go.Figure()
    if ratio_x:
        fig_reject_ratio.add_trace(go.Scatter(x=ratio_x, y=ratio_y, mode="lines+markers", name="reject_ratio"))
    fig_reject_ratio.update_layout(
        height=360, autosize=False,
        margin=dict(l=30, r=10, t=10, b=30),
        xaxis_title="Time (seconds since dashboard start)",
        yaxis_title="Reject ratio (0..1)",
        yaxis=dict(range=[0, 1]),
    )

    # Compute total reject ratio for card
    total_denom = rejected_total + blocks_accepted
    total_ratio = (rejected_total / total_denom) if total_denom > 0 else 0.0
    card_ratio = make_card("Reject ratio", f"{total_ratio:.2f}", "rejected / (rejected + accepted)")

    # --- Blocks table (last blocks) ---
    blocks_sorted = sorted(blocks, key=lambda b: b["height"], reverse=True)
    table_data = []
    for b in blocks_sorted[:15]:
        table_data.append({
            "height": b["height"],
            "miner_id": b["miner_id"],
            "block_hash_short": (b["block_hash"][:16] + "...") if b.get("block_hash") else "—",
            "prev_hash_short": (b["prev_hash"][:16] + "...") if b.get("prev_hash") else "—",
            "nonce": b["nonce"],
            "accepted_timestamp_ms": b["accepted_timestamp_ms"],
        })

    # --- Status line ---
    avg_bt = float(metrics.get("avg_block_time_ms", 0.0))
    last_bt = metrics.get("last_block_time_ms", None)
    status = f"avg_block_time={avg_bt:.1f}ms | last_block_time={last_bt}ms | miners={len(miners)}"

    return (
        card_height,
        card_rejected,
        card_ratio,
        card_uptime,
        fig_block_time,
        fig_accepted,
        fig_reject_rate,
        fig_reject_ratio,
        table_data,
        status,
    )





if __name__ == "__main__":
    # Run dashboard locally. Start the coordinator first.
    app.run(host="127.0.0.1", port=8050, debug=False)

