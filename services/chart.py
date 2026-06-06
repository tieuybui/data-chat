"""
Plotly chart builder — converts a DataFrame + AI chart config into a Plotly figure.
"""

from __future__ import annotations

import pandas as pd


_LAYOUT = dict(
    plot_bgcolor="rgba(0,0,0,0)",
    paper_bgcolor="rgba(0,0,0,0)",
    font=dict(color="#e2e8f0", size=13),
    margin=dict(l=16, r=16, t=48, b=32),
    legend=dict(bgcolor="rgba(0,0,0,0)"),
)

_COLORS = [
    "#6366f1", "#22d3ee", "#f59e0b", "#10b981",
    "#f43f5e", "#a78bfa", "#34d399", "#fb923c",
]


def build_chart(df: pd.DataFrame, chart_type: str, config: dict):
    """Return a Plotly Figure or None if chart_type is 'none'/'table' or data unsuitable."""
    if not chart_type or chart_type in ("none", "table") or df.empty:
        return None

    try:
        import plotly.express as px
    except ImportError:
        return None

    x = _resolve_col(df, config.get("x"))
    y = _resolve_col(df, config.get("y"))
    color = _resolve_col(df, config.get("color"))
    title = config.get("title", "")

    if chart_type == "histogram":
        col = x or y or _first_numeric(df)
        if not col:
            return None
        fig = px.histogram(df, x=col, title=title, color_discrete_sequence=_COLORS)

    elif chart_type == "pie":
        names = x or _first_string(df)
        values = y or _first_numeric(df)
        if not names or not values:
            return None
        fig = px.pie(df, names=names, values=values, title=title, color_discrete_sequence=_COLORS)

    else:
        # bar / line / area / scatter all need x + y
        if not x or not y:
            x, y = _auto_detect_xy(df)
        if not x or not y:
            return None

        kwargs = dict(x=x, y=y, title=title, color_discrete_sequence=_COLORS)
        if color:
            kwargs["color"] = color

        if chart_type == "bar":
            fig = px.bar(df, **kwargs)
        elif chart_type == "line":
            fig = px.line(df, markers=True, **kwargs)
        elif chart_type == "area":
            fig = px.area(df, **kwargs)
        elif chart_type == "scatter":
            fig = px.scatter(df, **kwargs)
        else:
            return None

    fig.update_layout(**_LAYOUT)
    fig.update_traces(marker_line_width=0)
    return fig


# ── Helpers ──────────────────────────────────────────────────────────


def _resolve_col(df: pd.DataFrame, name) -> str | None:
    """Return the column name if it exists in the DataFrame, else None."""
    if name and str(name) in df.columns:
        return str(name)
    return None


def _first_numeric(df: pd.DataFrame) -> str | None:
    cols = df.select_dtypes(include="number").columns.tolist()
    return cols[0] if cols else None


def _first_string(df: pd.DataFrame) -> str | None:
    cols = df.select_dtypes(include=["object", "string", "category"]).columns.tolist()
    return cols[0] if cols else None


def _first_datetime(df: pd.DataFrame) -> str | None:
    cols = df.select_dtypes(include=["datetime", "datetimetz"]).columns.tolist()
    return cols[0] if cols else None


def _auto_detect_xy(df: pd.DataFrame) -> tuple[str | None, str | None]:
    """Best-guess x and y columns from data types."""
    num = df.select_dtypes(include="number").columns.tolist()
    dt = df.select_dtypes(include=["datetime", "datetimetz"]).columns.tolist()
    cat = df.select_dtypes(include=["object", "string", "category"]).columns.tolist()

    if dt and num:
        return dt[0], num[0]
    if cat and num:
        return cat[0], num[0]
    if len(num) >= 2:
        return num[0], num[1]
    return None, None
