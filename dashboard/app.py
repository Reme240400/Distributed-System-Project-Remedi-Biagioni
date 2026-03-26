import os
import time
from typing import Any, Dict, List, Tuple
from collections import defaultdict

import requests
from dash import Dash, dcc, html, dash_table
from dash.dependencies import Input, Output
import plotly.graph_objects as go


# ---------------------------
# Configuration
# ---------------------------

COORDINATOR_URL = os.getenv("COORDINATOR_URL", "http://127.0.0.1:8000")
CHAIN_LIMIT = int(os.getenv("CHAIN_LIMIT", "50"))
REFRESH_MS = int(os.getenv("REFRESH_MS", "1000"))

# Dashboard-side time series
REJECT_SERIES_MAX_POINTS = int(os.getenv("REJECT_SERIES_MAX_POINTS", "300"))
ACCEPT_SERIES_MAX_POINTS = int(os.getenv("ACCEPT_SERIES_MAX_POINTS", "300"))

_reject_series: List[Tuple[float, int]] = []
_accept_series: List[Tuple[float, int]] = []

DASH_START_S = time.time()


# ---------------------------
# UI helpers
# ---------------------------

def _card_style() -> Dict[str, Any]:
    return {
        "flex": "1 1 220px",
        "minWidth": "220px",
        "border": "1px solid #ddd",
        "borderRadius": "10px",
        "padding": "10px 12px",
        "backgroundColor": "#fafafa",
    }


def make_card(title: str, value: str, subtitle: str = "") -> html.Div:
    return html.Div(
        children=[
            html.Div(title, style={"fontSize": "12px", "color": "#555"}),
            html.Div(value, style={"fontSize": "24px", "fontWeight": "bold"}),
            html.Div(subtitle, style={"fontSize": "12px", "color": "#777"}) if subtitle else html.Div(),
        ]
    )


# ---------------------------
# HTTP helpers
# ---------------------------

def fetch_json(url: str, timeout: int = 5) -> Dict[str, Any]:
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return {}


def fetch_metrics() -> Dict[str, Any]:
    return fetch_json(f"{COORDINATOR_URL}/metrics")


def fetch_chain(limit: int) -> Dict[str, Any]:
    return fetch_json(f"{COORDINATOR_URL}/chain?limit={limit}")


def fetch_blocks(limit: int) -> List[Dict[str, Any]]:
    chain_view = fetch_json(f"{COORDINATOR_URL}/blocks?limit={limit}")
    return chain_view.get("blocks", [])


def fetch_all_blocks() -> List[Dict[str, Any]]:
    try:
        resp = requests.get(f"{COORDINATOR_URL}/all-blocks", timeout=5)
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return []


def compute_block_times(chain_blocks: List[Dict[str, Any]]) -> List[Tuple[int, int]]:
    if not chain_blocks or len(chain_blocks) < 2:
        return []

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

        dcc.Interval(id="tick", interval=REFRESH_MS, n_intervals=0),

        # Summary cards
        html.Div(
            style={"display": "flex", "gap": "12px", "flexWrap": "wrap", "marginBottom": "12px"},
            children=[
                html.Div(id="card-height", style=_card_style()),
                html.Div(id="card-difficulty", style=_card_style()),
                html.Div(id="card-next-adjustment", style=_card_style()),
                html.Div(id="card-rejected", style=_card_style()),
                html.Div(id="card-reject-ratio", style=_card_style()),
                html.Div(id="card-uptime", style=_card_style()),
                html.Div(id="card-forks", style=_card_style()),
                html.Div(id="card-orphans", style=_card_style()),
                html.Div(id="card-reorgs", style=_card_style()),
            ],
        ),

        # DAG
        html.Div(
            style={"marginBottom": "12px", "padding": "12px", "border": "1px solid #eee", "borderRadius": "8px"},
            children=[
                html.H4("Block Tree (All Blocks)", style={"marginBottom": "4px"}),
                dcc.Graph(id="graph-block-tree", config={"displayModeBar": True}, style={"height": "420px"}),
            ],
        ),

        # Charts row
        html.Div(
            style={"display": "flex", "gap": "12px", "flexWrap": "wrap"},
            children=[
                html.Div(
                    style={"flex": "1 1 580px", "minWidth": "360px"},
                    children=[
                        html.H4("Block time (main chain)", style={"marginBottom": "4px"}),
                        dcc.Graph(id="graph-block-time", config={"displayModeBar": False}, style={"height": "360px"}),
                    ],
                ),
                html.Div(
                    style={"flex": "1 1 580px", "minWidth": "360px"},
                    children=[
                        html.H4("Accepted blocks by miner", style={"marginBottom": "4px"}),
                        dcc.Graph(id="graph-accepted-by-miner", config={"displayModeBar": False}, style={"height": "360px"}),
                    ],
                ),
            ],
        ),

        html.Div(
            style={"marginTop": "12px"},
            children=[
                html.H4("Reject rate over time", style={"marginBottom": "4px"}),
                dcc.Graph(id="graph-reject-rate", config={"displayModeBar": False}, style={"height": "360px"}),
            ],
        ),

        html.H4("Last blocks", style={"marginTop": "16px", "marginBottom": "6px"}),

        dash_table.DataTable(
            id="table-blocks",
            columns=[
                {"name": "height", "id": "height"},
                {"name": "miner_id", "id": "miner_id"},
                {"name": "hash", "id": "block_hash_short"},
                {"name": "prev_hash", "id": "prev_hash_short"},
                {"name": "nonce", "id": "nonce"},
                {"name": "accepted timestamp", "id": "accepted_timestamp_ms"},
                {"name": "main?", "id": "on_main_chain"},
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

        html.Div(id="status-line", style={"marginTop": "10px", "color": "#777"}),
    ],
)


# ---------------------------
# Callbacks
# ---------------------------

@app.callback(
    Output("card-height", "children"),
    Output("card-difficulty", "children"),
    Output("card-next-adjustment", "children"),
    Output("card-rejected", "children"),
    Output("card-reject-ratio", "children"),
    Output("card-uptime", "children"),
    Output("card-forks", "children"),
    Output("card-orphans", "children"),
    Output("card-reorgs", "children"),
    Output("graph-block-time", "figure"),
    Output("graph-accepted-by-miner", "figure"),
    Output("graph-reject-rate", "figure"),
    Output("graph-block-tree", "figure"),
    Output("table-blocks", "data"),
    Output("status-line", "children"),
    Input("tick", "n_intervals"),
)
def refresh(_n: int):
    metrics = fetch_metrics()
    blocks = fetch_blocks(CHAIN_LIMIT)

    if not metrics or not blocks:
        empty = go.Figure()
        empty.update_layout(height=360, autosize=False, margin=dict(l=30, r=10, t=10, b=30))

        return (
            make_card("Chain height", "—", "Coordinator not reachable"),
            make_card("Current difficulty", "—"),
            make_card("Next difficulty step", "—"),
            make_card("Rejected total", "—"),
            make_card("Reject ratio", "—"),
            make_card("Uptime", "—"),
            make_card("Forks detected", "—"),
            make_card("Orphan blocks", "—"),
            make_card("Reorgs", "—"),
            empty,
            empty,
            empty,
            empty,
            [],
            f"Waiting for coordinator at {COORDINATOR_URL} ...",
        )

    all_blocks_tree = fetch_all_blocks()

    # Metrics
    height = int(metrics.get("height", 0))
    blocks_accepted = int(metrics.get("blocks_accepted", 0))
    rejected_total = int(metrics.get("rejected_total", 0))
    uptime_ms = int(metrics.get("uptime_ms", 0))
    forks_detected = int(metrics.get("forks_detected", 0))
    orphan_count = int(metrics.get("orphan_count", 0))
    reorg_count = int(metrics.get("reorg_count", 0))
    current_difficulty_bits = int(metrics.get("current_difficulty_bits", 0))
    blocks_to_next_adjustment = int(metrics.get("blocks_to_next_adjustment", 0))

    card_height = make_card("Chain height", str(height), "Tip height")
    card_difficulty = make_card("Current difficulty", str(current_difficulty_bits), "Leading zero bits")
    card_next_adjustment = make_card("Next difficulty step", str(blocks_to_next_adjustment), "Blocks remaining")
    card_rejected = make_card("Rejected total", str(rejected_total), "Stale work / invalid submissions")
    card_uptime = make_card("Uptime", f"{uptime_ms/1000:.1f}s", f"{uptime_ms} ms")
    card_forks = make_card("Forks detected", str(forks_detected), "Points with multiple children")
    card_orphans = make_card("Orphan blocks", str(orphan_count), "Blocks not in main chain")
    card_reorgs = make_card("Reorgs", str(reorg_count), "Chain reorganizations")

    total_denom = rejected_total + blocks_accepted
    total_ratio = (rejected_total / total_denom) if total_denom > 0 else 0.0
    card_ratio = make_card("Reject ratio", f"{total_ratio:.2f}", "rejected / (rejected + accepted)")

    # Time series
    t_rel = time.time() - DASH_START_S
    global _reject_series, _accept_series
    _reject_series.append((t_rel, rejected_total))
    _accept_series.append((t_rel, blocks_accepted))

    if len(_reject_series) > REJECT_SERIES_MAX_POINTS:
        _reject_series = _reject_series[-REJECT_SERIES_MAX_POINTS:]
    if len(_accept_series) > ACCEPT_SERIES_MAX_POINTS:
        _accept_series = _accept_series[-ACCEPT_SERIES_MAX_POINTS:]

    # ---------------------------
    # Block time chart
    # ---------------------------
    if all_blocks_tree:
        main_chain = [b for b in all_blocks_tree if b.get("on_main_chain")]
        main_chain.sort(key=lambda b: b["height"])
        chain_slice = main_chain[-CHAIN_LIMIT:]
        bt = compute_block_times(chain_slice)
    else:
        bt = compute_block_times(blocks)

    fig_block_time = go.Figure()
    if bt:
        x = [h for (h, _dt) in bt]
        y = [_dt / 1000.0 for (_h, _dt) in bt]
        fig_block_time.add_trace(go.Scatter(x=x, y=y, mode="lines+markers", name="block_time_s"))

    fig_block_time.update_layout(
        height=360,
        autosize=False,
        margin=dict(l=30, r=10, t=10, b=30),
        xaxis_title="Block height (main chain)",
        yaxis_title="Block time (seconds)",
    )

    # ---------------------------
    # Accepted by miner
    # ---------------------------
    miner_main_counts = defaultdict(int)
    miner_orphan_counts = defaultdict(int)
    all_miners = set()

    if all_blocks_tree:
        for b in all_blocks_tree:
            if b.get("height") == 0:
                continue
            mid = b.get("miner_id", "unknown")
            all_miners.add(mid)
            if b.get("on_main_chain"):
                miner_main_counts[mid] += 1
            else:
                miner_orphan_counts[mid] += 1
    else:
        raw_accepted = metrics.get("accepted_by_miner", {}) or {}
        for m, count in raw_accepted.items():
            all_miners.add(m)
            miner_main_counts[m] = int(count)

    sorted_miners = sorted(list(all_miners))
    main_vals = [miner_main_counts[m] for m in sorted_miners]
    orphan_vals = [miner_orphan_counts[m] for m in sorted_miners]

    fig_accepted = go.Figure()
    fig_accepted.add_trace(go.Bar(x=sorted_miners, y=main_vals, name="Main Chain", marker_color="green"))
    fig_accepted.add_trace(go.Bar(x=sorted_miners, y=orphan_vals, name="Stale/Orphan", marker_color="red"))

    fig_accepted.update_layout(
        height=360,
        autosize=False,
        margin=dict(l=30, r=10, t=10, b=50),
        xaxis_title="Miners",
        yaxis_title="Accepted blocks",
        barmode="group",
        bargap=0.2,
        bargroupgap=0.0,
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="right",
            x=1
        )
    )

    # ---------------------------
    # Reject rate
    # ---------------------------
    rate_x: List[float] = []
    rate_y: List[float] = []

    if len(_reject_series) >= 2:
        for i in range(1, len(_reject_series)):
            t0, r0 = _reject_series[i - 1]
            t1, r1 = _reject_series[i]
            dt = max(t1 - t0, 1e-6)
            dr = r1 - r0
            rate_x.append(t1)
            rate_y.append(dr / dt)

    fig_reject_rate = go.Figure()
    if rate_x:
        fig_reject_rate.add_trace(go.Scatter(x=rate_x, y=rate_y, mode="lines+markers", name="reject/s"))

    fig_reject_rate.update_layout(
        height=360,
        autosize=False,
        margin=dict(l=30, r=10, t=10, b=30),
        xaxis_title="Time (seconds since dashboard start)",
        yaxis_title="Rejects / second",
    )

    # ---------------------------
    # DAG visualization
    # ---------------------------
    fig_tree = go.Figure()

    if all_blocks_tree:
        by_height = defaultdict(list)
        for b in all_blocks_tree:
            by_height[b["height"]].append(b)

        layout_map = {}
        occupied = set()

        for h in sorted(by_height.keys()):
            blks = sorted(by_height[h], key=lambda b: (b.get("accepted_timestamp_ms", 0), b["block_hash"]))

            for b in blks:
                target_y = 0
                ph = b.get("prev_hash")
                if ph and ph in layout_map:
                    target_y = layout_map[ph][1]

                y = target_y
                if (h, y) in occupied:
                    offset = 1
                    base_y = target_y
                    while (h, y) in occupied:
                        delta = (offset + 1) // 2
                        if offset % 2 != 0:
                            y = base_y + delta
                        else:
                            y = base_y - delta
                        offset += 1

                layout_map[b["block_hash"]] = (h, y)
                occupied.add((h, y))

        block_by_hash = {b["block_hash"]: b for b in all_blocks_tree}

        main_edge_x = []
        main_edge_y = []
        stale_edge_x = []
        stale_edge_y = []

        for b in all_blocks_tree:
            bh = b["block_hash"]
            ph = b["prev_hash"]

            if bh not in layout_map or ph not in layout_map:
                continue

            x0, y0 = layout_map[ph]
            x1, y1 = layout_map[bh]

            parent = block_by_hash.get(ph)
            is_main_edge = (
                b.get("on_main_chain", False)
                and parent is not None
                and parent.get("on_main_chain", False)
            )

            if is_main_edge:
                main_edge_x.extend([x0, x1, None])
                main_edge_y.extend([y0, y1, None])
            else:
                stale_edge_x.extend([x0, x1, None])
                stale_edge_y.extend([y0, y1, None])

        # stale edges first
        fig_tree.add_trace(go.Scatter(
            x=stale_edge_x,
            y=stale_edge_y,
            mode="lines",
            line=dict(color="red", width=1),
            hoverinfo="none",
            name="stale-link",
        ))

        # main edges on top
        fig_tree.add_trace(go.Scatter(
            x=main_edge_x,
            y=main_edge_y,
            mode="lines",
            line=dict(color="green", width=2),
            hoverinfo="none",
            name="main-link",
        ))

        node_x = []
        node_y = []
        node_color = []
        node_text = []

        for b in all_blocks_tree:
            bh = b["block_hash"]
            if bh not in layout_map:
                continue

            x, y = layout_map[bh]
            node_x.append(x)
            node_y.append(y)
            node_color.append("green" if b.get("on_main_chain") else "red")

            miner = b.get("miner_id", "?")
            ts = b.get("accepted_timestamp_ms", 0)
            node_text.append(
                f"H={x}<br>"
                f"Miner={miner}<br>"
                f"Hash={bh[:12]}<br>"
                f"TS={ts}<br>"
                f"Main={b.get('on_main_chain', False)}"
            )

        fig_tree.add_trace(go.Scatter(
            x=node_x,
            y=node_y,
            mode="markers",
            marker=dict(symbol="circle", size=8, color=node_color),
            text=node_text,
            hoverinfo="text",
            name="block",
        ))

    fig_tree.update_layout(
        title="Block DAG (Green=Main, Red=Orphan/Stale)",
        showlegend=False,
        xaxis_title="Height",
        yaxis_title="Branch Offset",
        height=420,
        margin=dict(l=30, r=10, t=40, b=30),
    )

    # ---------------------------
    # Recent blocks table
    # ---------------------------
    block_on_main = {}
    if all_blocks_tree:
        block_on_main = {b["block_hash"]: b.get("on_main_chain", False) for b in all_blocks_tree}

    blocks_sorted = sorted(blocks, key=lambda b: (b["height"], b["accepted_timestamp_ms"]), reverse=True)
    table_data = []

    for b in blocks_sorted[:15]:
        table_data.append({
            "height": b["height"],
            "miner_id": b["miner_id"],
            "block_hash_short": (b["block_hash"][:16] + "...") if b.get("block_hash") else "—",
            "prev_hash_short": (b["prev_hash"][:16] + "...") if b.get("prev_hash") else "—",
            "nonce": b["nonce"],
            "accepted_timestamp_ms": b["accepted_timestamp_ms"],
            "on_main_chain": "yes" if block_on_main.get(b.get("block_hash"), False) else "no",
        })

    avg_bt = float(metrics.get("avg_block_time_ms", 0.0))
    last_bt = metrics.get("last_block_time_ms", None)
    status = (
        f"avg_block_time={avg_bt:.1f}ms | "
        f"last_block_time={last_bt}ms | "
        f"miners={len(sorted_miners)} | "
        f"difficulty={current_difficulty_bits} | "
        f"next_adjustment_in={blocks_to_next_adjustment}"
    )

    return (
        card_height,
        card_difficulty,
        card_next_adjustment,
        card_rejected,
        card_ratio,
        card_uptime,
        card_forks,
        card_orphans,
        card_reorgs,
        fig_block_time,
        fig_accepted,
        fig_reject_rate,
        fig_tree,
        table_data,
        status,
    )


if __name__ == "__main__":
    host = os.getenv("DASH_HOST", "127.0.0.1")
    port = int(os.getenv("DASHBOARD_PORT", "8050"))
    app.run(host=host, port=port, debug=False)