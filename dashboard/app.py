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
                html.Div(id="card-accepted", style=_card_style()),
                html.Div(id="card-rejected", style=_card_style()),
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
    Output("card-accepted", "children"),
    Output("card-rejected", "children"),
    Output("card-uptime", "children"),
    Output("graph-block-time", "figure"),
    Output("graph-accepted-by-miner", "figure"),
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

    if not metrics or not chain_view or "blocks" not in chain_view:
        return (
            make_card("Chain height", "—", "Coordinator not reachable"),
            make_card("Blocks accepted", "—"),
            make_card("Rejected total", "—"),
            make_card("Uptime", "—"),
            go.Figure(),
            go.Figure(),
            [],
            f"Waiting for coordinator at {COORDINATOR_URL} ...",
        )

    # --- Summary cards ---
    height = metrics.get("height", 0)
    blocks_accepted = metrics.get("blocks_accepted", 0)
    rejected_total = metrics.get("rejected_total", 0)
    uptime_ms = metrics.get("uptime_ms", 0)

    card_height = make_card("Chain height", str(height), "Tip height")
    card_accepted = make_card("Blocks accepted", str(blocks_accepted), "Excluding genesis")
    card_rejected = make_card("Rejected total", str(rejected_total), "Stale work / invalid submissions")
    card_uptime = make_card("Uptime", f"{uptime_ms/1000:.1f}s", f"{uptime_ms} ms")

    # --- Block time chart ---
    blocks = chain_view["blocks"]
    bt = compute_block_times(blocks)  # list of (height, delta_ms)

    fig_block_time = go.Figure()
    if bt:
        x = [h for (h, _dt) in bt]
        y = [_dt for (_h, _dt) in bt]
        fig_block_time.add_trace(go.Scatter(x=x, y=y, mode="lines+markers", name="block_time_ms"))
    fig_block_time.update_layout(
        height=360,
        autosize=False,
        margin=dict(l=30, r=10, t=10, b=30),
        xaxis_title="Block height",
        yaxis_title="Δ accepted_timestamp (ms)",
    )

    # --- Accepted by miner bar chart ---
    accepted_by_miner = metrics.get("accepted_by_miner", {})
    miners = list(accepted_by_miner.keys())
    counts = [accepted_by_miner[m] for m in miners]

    fig_accepted = go.Figure()
    fig_accepted.add_trace(go.Bar(x=miners, y=counts, name="accepted"))
    fig_accepted.update_layout(
        height=360,
        autosize=False,
        margin=dict(l=30, r=10, t=10, b=30),
        xaxis_title="Miner",
        yaxis_title="Accepted blocks",
    )

    # --- Blocks table (last blocks) ---
    # Show latest first.
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

    # --- Status line with a useful one-liner ---
    avg_bt = metrics.get("avg_block_time_ms", 0.0)
    last_bt = metrics.get("last_block_time_ms", None)
    status = f"avg_block_time={avg_bt:.1f}ms | last_block_time={last_bt}ms | miners={len(miners)}"

    return (
        card_height,
        card_accepted,
        card_rejected,
        card_uptime,
        fig_block_time,
        fig_accepted,
        table_data,
        status,
    )


if __name__ == "__main__":
    # Run dashboard locally. Start the coordinator first.
    app.run(host="127.0.0.1", port=8050, debug=False)

