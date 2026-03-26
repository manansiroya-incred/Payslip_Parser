"""
All Plotly chart functions for the Payslip Parser UI.

Each function receives data as arguments and returns a go.Figure.
No session state access — charts are pure rendering functions.
"""

import plotly.graph_objects as go
from typing import Optional


# ---------------------------------------------------------------------------
# Colour palette
# ---------------------------------------------------------------------------
EARNINGS_COLORS = {
    "basic_salary": "#4e79a7",
    "hra": "#f28e2b",
    "lta": "#e15759",
    "special_allowance": "#76b7b2",
    "overtime": "#59a14f",
    "bonus": "#edc948",
    "other": "#b07aa1",
}

# Rotating palette for other/non-standard items so each gets a unique color
OTHER_COLORS_POOL = [
    "#e74c3c", "#3498db", "#2ecc71", "#f39c12", "#9b59b6",
    "#1abc9c", "#e67e22", "#34495e", "#16a085", "#c0392b",
]

DEDUCTIONS_COLORS = {
    "tds_income_tax": "#ff9800",
    "pf_epf": "#2196f3",
    "professional_tax": "#9c27b0",
    "gratuity": "#4caf50",
    "esic": "#00bcd4",
    "loan_deduction": "#795548",
    "other": "#607d8b",
}


# ---------------------------------------------------------------------------
# Tab 1: Earnings stacked horizontal bar
# ---------------------------------------------------------------------------
def earnings_stacked_bar(earnings: dict, currency_symbol: str = "\u20b9") -> go.Figure:
    """Stacked horizontal bar showing gross salary composition."""
    components = []
    values = []
    colors = []

    # Standard fields
    for field, color in EARNINGS_COLORS.items():
        if field == "other":
            continue
        val = earnings.get(field)
        if val is not None and val > 0:
            label = field.replace("_", " ").title()
            components.append(label)
            values.append(val)
            colors.append(color)

    # Other earnings
    other = earnings.get("other_earnings", {})
    if isinstance(other, dict):
        for name, val in other.items():
            if val is not None and isinstance(val, (int, float)) and val > 0:
                components.append(name.replace("_", " ").title())
                values.append(val)
                colors.append(EARNINGS_COLORS["other"])

    if not values:
        # Fallback: if gross is known but no breakdown, show a single total bar
        gross = earnings.get("gross_salary")
        if gross is not None and isinstance(gross, (int, float)) and gross > 0:
            components = ["Total Gross"]
            values = [gross]
            colors = [EARNINGS_COLORS["basic_salary"]]
        else:
            fig = go.Figure()
            fig.add_annotation(text="No earnings data available", showarrow=False)
            return fig

    fig = go.Figure()

    cs = currency_symbol
    for comp, val, color in zip(components, values, colors):
        fig.add_trace(go.Bar(
            y=["Gross Salary"],
            x=[val],
            name=f"{comp} ({cs}{val:,.0f})",
            orientation="h",
            marker_color=color,
            text=f"{cs}{val:,.0f}",
            textposition="inside",
            hovertemplate=f"{comp}: {cs}{val:,.0f}<extra></extra>",
        ))

    fig.update_layout(
        barmode="stack",
        title="What makes up the gross salary",
        xaxis_title=f"Amount ({cs})",
        showlegend=True,
        legend=dict(orientation="h", y=-0.2),
        height=200,
        margin=dict(l=20, r=20, t=40, b=60),
    )

    return fig


# ---------------------------------------------------------------------------
# Tab 1: Deductions donut chart
# ---------------------------------------------------------------------------
def deductions_donut(deductions: dict, total_deductions: Optional[float] = None, currency_symbol: str = "\u20b9") -> go.Figure:
    """Donut chart showing deduction proportions."""
    cs = currency_symbol
    labels = []
    values = []
    colors = []

    for field, color in DEDUCTIONS_COLORS.items():
        if field == "other":
            continue
        val = deductions.get(field)
        if val is not None and isinstance(val, (int, float)) and val > 0:
            labels.append(field.replace("_", " ").title())
            values.append(val)
            colors.append(color)

    # Other deductions — each gets a unique color from the pool
    other = deductions.get("other_deductions", {})
    other_idx = 0
    if isinstance(other, dict):
        for name, val in other.items():
            if val is not None and isinstance(val, (int, float)) and val > 0:
                labels.append(name.replace("_", " ").title())
                values.append(val)
                colors.append(OTHER_COLORS_POOL[other_idx % len(OTHER_COLORS_POOL)])
                other_idx += 1

    if not values:
        fig = go.Figure()
        fig.add_annotation(text="No deduction data available", showarrow=False)
        return fig

    total = total_deductions or sum(values)

    fig = go.Figure(data=[go.Pie(
        labels=labels,
        values=values,
        hole=0.55,
        marker_colors=colors,
        textinfo="label+percent",
        textposition="outside",
        hovertemplate=f"%{{label}}: {cs}%{{value:,.0f}} (%{{percent}})<extra></extra>",
    )])

    fig.add_annotation(
        text=f"{cs}{total:,.0f}",
        x=0.5, y=0.5,
        font_size=18, font_weight="bold",
        showarrow=False,
    )

    fig.update_layout(
        title="Where the deductions go",
        showlegend=True,
        legend=dict(orientation="h", y=-0.1),
        height=350,
        margin=dict(l=20, r=20, t=40, b=40),
    )

    return fig


# ---------------------------------------------------------------------------
# Tab 2: Salary trend line chart
# ---------------------------------------------------------------------------
def salary_trend_line(payslips: list[dict], projection: dict = None) -> go.Figure:
    """
    Line chart: Gross (dashed), Net (solid), Deductions (thin) over time.
    Includes reference line at average net and shaded consistency band.
    If projection is provided, extends the Net line with a dotted projection.
    """
    months = []
    gross_vals = []
    net_vals = []
    ded_vals = []

    for p in payslips:
        label = (
            p.get("document_meta", {}).get("pay_period_label")
            or p.get("document_meta", {}).get("pay_period_start")
            or p.get("_source_file", "Unknown")
        )
        months.append(label)
        gross_vals.append(p.get("earnings", {}).get("gross_salary") or 0)
        net_vals.append(p.get("net_pay", {}).get("net_salary") or 0)
        ded_vals.append(p.get("deductions", {}).get("total_deductions") or 0)

    avg_net = sum(net_vals) / len(net_vals) if net_vals else 0

    fig = go.Figure()

    # Consistency band (±5% around average)
    if avg_net > 0:
        upper = [avg_net * 1.05] * len(months)
        lower = [avg_net * 0.95] * len(months)
        fig.add_trace(go.Scatter(
            x=months, y=upper,
            mode="lines", line=dict(width=0),
            showlegend=False, hoverinfo="skip",
        ))
        fig.add_trace(go.Scatter(
            x=months, y=lower,
            mode="lines", line=dict(width=0),
            fill="tonexty", fillcolor="rgba(76, 175, 80, 0.1)",
            showlegend=False, hoverinfo="skip",
        ))

    # Gross line (dashed)
    fig.add_trace(go.Scatter(
        x=months, y=gross_vals,
        mode="lines+markers+text",
        name="Gross",
        line=dict(dash="dash", color="#4e79a7", width=2),
        text=[f"₹{v:,.0f}" for v in gross_vals],
        textposition="top center",
        textfont=dict(size=10),
    ))

    # Net line (solid, prominent)
    fig.add_trace(go.Scatter(
        x=months, y=net_vals,
        mode="lines+markers+text",
        name="Net",
        line=dict(color="#28a745", width=3),
        text=[f"₹{v:,.0f}" for v in net_vals],
        textposition="bottom center",
        textfont=dict(size=10),
    ))

    # Deductions line (thin)
    fig.add_trace(go.Scatter(
        x=months, y=ded_vals,
        mode="lines+markers",
        name="Deductions",
        line=dict(color="#dc3545", width=1),
    ))

    # Average reference line
    if avg_net > 0:
        fig.add_hline(
            y=avg_net,
            line_dash="dot",
            line_color="gray",
            annotation_text=f"Avg Net: ₹{avg_net:,.0f}",
            annotation_position="bottom right",
        )

    # Income projection (dotted extension from last actual data point)
    if projection and projection.get("projected_values") and months:
        proj_labels = projection.get("projected_labels", [])
        proj_vals = projection["projected_values"]
        # Connect from last actual point to projection
        proj_x = [months[-1]] + proj_labels
        proj_y = [net_vals[-1]] + proj_vals
        fig.add_trace(go.Scatter(
            x=proj_x, y=proj_y,
            mode="lines",
            name="Net (Projected)",
            line=dict(dash="dot", color="#28a745", width=2),
            opacity=0.6,
        ))

    fig.update_layout(
        title="Salary Trend",
        xaxis_title="Pay Period",
        yaxis_title="Amount (₹)",
        height=400,
        margin=dict(l=20, r=20, t=40, b=40),
        legend=dict(orientation="h", y=-0.15),
    )

    return fig
