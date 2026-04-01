"""
Analytics Blueprint — PoultryConnect 2.0
Computes and presents the farmer's profitability analytics.

Features:
  - Monthly P&L overview  (revenue vs. expenses → profit / loss)
  - 6-month trend chart   (monthly revenue + expenses over time)
  - Expense breakdown     (by category, for the selected month)
  - 30-day production     (daily egg counts)
  - Price recommendation  (break-even + suggested price with configurable margin)
  - Month selector        (?year=YYYY&month=MM query params, validated)

Security:
  - @login_required on every route
  - Role guard: only FARMER
  - All DB queries are scoped to current_user's own farm IDs — no cross-user leakage
  - Query params (year, month) are strictly validated as integers in valid ranges
  - No raw SQL — all via SQLAlchemy ORM aggregation
"""

from flask import Blueprint, render_template, request, abort, redirect, url_for
from flask_login import login_required, current_user
from sqlalchemy import func, extract
from datetime import date, timedelta
from decimal import Decimal
from calendar import monthrange

from app import db
from app.models import Farm, ProductionRecord, Expense, UserRole, ExpenseCategory

analytics_bp = Blueprint('analytics', __name__)

# Target gross margin for the recommendation engine (20%)
RECOMMENDED_MARGIN = Decimal('0.20')


# ─── helpers ────────────────────────────────────────────────────────────────

def _require_farmer():
    if current_user.role != UserRole.FARMER:
        abort(403)


def _get_farm_ids() -> list[int]:
    farms = Farm.query.filter_by(
        farmer_id=current_user.id, is_active=True
    ).with_entities(Farm.id).all()
    return [f.id for f in farms]


def _validate_month_params(year_str, month_str):
    """
    Validate and return (year, month) ints from query params.
    Falls back to current month on invalid input.
    """
    today = date.today()
    try:
        year  = int(year_str)
        month = int(month_str)
        if not (2000 <= year <= 2100 and 1 <= month <= 12):
            raise ValueError
    except (TypeError, ValueError):
        year, month = today.year, today.month
    return year, month


def _month_bounds(year: int, month: int):
    """Return (first_day, last_day) date objects for the given month."""
    _, last_day = monthrange(year, month)
    return date(year, month, 1), date(year, month, last_day)


# ─── main analytics view ────────────────────────────────────────────────────

@analytics_bp.route('/')
@login_required
def index():
    _require_farmer()
    farm_ids = _get_farm_ids()

    # ── month selector ────────────────────────────────────────────────────
    today    = date.today()
    year, month = _validate_month_params(
        request.args.get('year'),
        request.args.get('month'),
    )
    month_start, month_end = _month_bounds(year, month)

    # Build prev / next month links
    prev_month_date = date(year, month, 1) - timedelta(days=1)
    next_month_date = date(year, month, 28) + timedelta(days=4)
    next_month_date = next_month_date.replace(day=1)

    prev_link = url_for('analytics.index', year=prev_month_date.year, month=prev_month_date.month)
    next_link = url_for('analytics.index', year=next_month_date.year, month=next_month_date.month)
    is_current_month = (year == today.year and month == today.month)

    # ── monthly revenue (egg_count × egg_price) ───────────────────────────
    monthly_revenue = Decimal('0.00')
    if farm_ids:
        rows = db.session.query(
            ProductionRecord.egg_count,
            ProductionRecord.egg_price,
        ).filter(
            ProductionRecord.farm_id.in_(farm_ids),
            ProductionRecord.record_date >= month_start,
            ProductionRecord.record_date <= month_end,
            ProductionRecord.egg_price.isnot(None),
        ).all()
        for egg_count, egg_price in rows:
            monthly_revenue += Decimal(str(egg_count)) * Decimal(str(egg_price))

    # ── monthly expenses total ────────────────────────────────────────────
    monthly_expenses = Decimal('0.00')
    if farm_ids:
        result = db.session.query(func.sum(Expense.amount)).filter(
            Expense.farm_id.in_(farm_ids),
            Expense.expense_date >= month_start,
            Expense.expense_date <= month_end,
        ).scalar()
        monthly_expenses = Decimal(str(result or 0))

    monthly_profit = monthly_revenue - monthly_expenses

    # ── expense breakdown by category ─────────────────────────────────────
    expense_by_category = []
    if farm_ids:
        rows = db.session.query(
            Expense.category,
            func.sum(Expense.amount).label('total'),
        ).filter(
            Expense.farm_id.in_(farm_ids),
            Expense.expense_date >= month_start,
            Expense.expense_date <= month_end,
        ).group_by(Expense.category).all()
        expense_by_category = [
            {'label': r.category.value.replace('_', ' ').title(), 'amount': float(r.total)}
            for r in rows
        ]
    category_labels = [r['label'] for r in expense_by_category]
    category_data   = [r['amount'] for r in expense_by_category]

    # ── monthly egg totals + feed totals ───────────────────────────────────
    monthly_eggs = 0
    if farm_ids:
        result = db.session.query(func.sum(ProductionRecord.egg_count)).filter(
            ProductionRecord.farm_id.in_(farm_ids),
            ProductionRecord.record_date >= month_start,
            ProductionRecord.record_date <= month_end,
        ).scalar()
        monthly_eggs = int(result or 0)

    # ── price recommendation ───────────────────────────────────────────────
    # Breakeven = total monthly expenses / eggs produced
    # Recommended = breakeven × (1 + margin)
    breakeven_price    = None
    recommended_price  = None
    current_avg_price  = None

    if monthly_eggs > 0 and monthly_expenses > 0:
        breakeven_price   = monthly_expenses / Decimal(str(monthly_eggs))
        recommended_price = breakeven_price * (1 + RECOMMENDED_MARGIN)

    if monthly_eggs > 0:
        # Average price farmer recorded this month
        result = db.session.query(
            func.sum(ProductionRecord.egg_count * ProductionRecord.egg_price),
            func.sum(
                db.case(
                    (ProductionRecord.egg_price.isnot(None), ProductionRecord.egg_count),
                    else_=0
                )
            )
        ).filter(
            ProductionRecord.farm_id.in_(farm_ids),
            ProductionRecord.record_date >= month_start,
            ProductionRecord.record_date <= month_end,
            ProductionRecord.egg_price.isnot(None),
        ).first()
        if result and result[0] and result[1]:
            current_avg_price = Decimal(str(result[0])) / Decimal(str(result[1]))

    # ── 6-month trend (revenue + expenses per month) ───────────────────────
    trend_labels   = []
    trend_revenue  = []
    trend_expenses = []

    for i in range(5, -1, -1):
        # Walk back i months from the selected month
        ref = date(year, month, 1)
        # subtract i months
        m = ref.month - i
        y = ref.year
        while m <= 0:
            m += 12
            y -= 1
        t_start, t_end = _month_bounds(y, m)
        label = date(y, m, 1).strftime('%b %Y')
        trend_labels.append(label)

        rev = Decimal('0.00')
        if farm_ids:
            rows = db.session.query(
                ProductionRecord.egg_count,
                ProductionRecord.egg_price,
            ).filter(
                ProductionRecord.farm_id.in_(farm_ids),
                ProductionRecord.record_date >= t_start,
                ProductionRecord.record_date <= t_end,
                ProductionRecord.egg_price.isnot(None),
            ).all()
            for egg_count, egg_price in rows:
                rev += Decimal(str(egg_count)) * Decimal(str(egg_price))

        exp = Decimal('0.00')
        if farm_ids:
            result = db.session.query(func.sum(Expense.amount)).filter(
                Expense.farm_id.in_(farm_ids),
                Expense.expense_date >= t_start,
                Expense.expense_date <= t_end,
            ).scalar()
            exp = Decimal(str(result or 0))

        trend_revenue.append(float(rev))
        trend_expenses.append(float(exp))

    # ── 30-day daily egg production chart ─────────────────────────────────
    prod_labels = []
    prod_data   = []
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        prod_labels.append(day.strftime('%b %d'))
        if farm_ids:
            result = db.session.query(func.sum(ProductionRecord.egg_count)).filter(
                ProductionRecord.farm_id.in_(farm_ids),
                ProductionRecord.record_date == day,
            ).scalar()
            prod_data.append(int(result or 0))
        else:
            prod_data.append(0)

    # ── farms quick summary ────────────────────────────────────────────────
    farms = Farm.query.filter_by(farmer_id=current_user.id, is_active=True).all()

    return render_template(
        'analytics/analytics.html',
        title='Analytics',

        # month selector
        year=year, month=month,
        month_label=date(year, month, 1).strftime('%B %Y'),
        prev_link=prev_link,
        next_link=next_link,
        is_current_month=is_current_month,

        # KPIs
        monthly_revenue=monthly_revenue,
        monthly_expenses=monthly_expenses,
        monthly_profit=monthly_profit,
        monthly_eggs=monthly_eggs,

        # price engine
        breakeven_price=breakeven_price,
        recommended_price=recommended_price,
        current_avg_price=current_avg_price,
        margin_pct=int(RECOMMENDED_MARGIN * 100),

        # chart data
        trend_labels=trend_labels,
        trend_revenue=trend_revenue,
        trend_expenses=trend_expenses,
        prod_labels=prod_labels,
        prod_data=prod_data,
        category_labels=category_labels,
        category_data=category_data,

        farms=farms,
        today=today,
    )
