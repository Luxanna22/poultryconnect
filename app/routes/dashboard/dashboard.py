from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import UserRole, Farm, ProductionRecord, Expense
from datetime import date, timedelta
from sqlalchemy import func

dashboard_bp = Blueprint('dashboard', __name__)


def _require_role(*roles):
    """Decorator-style helper — returns a redirect if current_user's role not in roles."""
    if current_user.role not in roles:
        flash('You do not have permission to access that page.', 'error')
        return redirect(url_for('index'))
    return None


@dashboard_bp.route('/')
@dashboard_bp.route('/index')
@login_required
def index():
    """Generic dashboard router — sends users to their role-specific dashboard."""
    if current_user.role == UserRole.FARMER:
        return redirect(url_for('dashboard.farmer'))
    elif current_user.role == UserRole.ADMIN:
        return redirect(url_for('admin.index'))
    else:
        # Buyer, feed_supplier, veterinarian — placeholder for now
        return redirect(url_for('index'))


@dashboard_bp.route('/farmer')
@login_required
def farmer():
    """Farmer Dashboard — full farm overview with KPIs and activity."""
    guard = _require_role(UserRole.FARMER)
    if guard:
        return guard

    today = date.today()
    month_start = today.replace(day=1)
    week_ago = today - timedelta(days=6)

    # Fetch farmer's farms
    farms = Farm.query.filter_by(farmer_id=current_user.id, is_active=True).all()
    farm_ids = [f.id for f in farms]

    # ── KPI: Total eggs this month ────────────────────────────────────────────
    eggs_this_month = 0
    if farm_ids:
        result = ProductionRecord.query.with_entities(
            func.sum(ProductionRecord.egg_count)
        ).filter(
            ProductionRecord.farm_id.in_(farm_ids),
            ProductionRecord.record_date >= month_start,
            ProductionRecord.record_date <= today,
        ).scalar()
        eggs_this_month = result or 0

    # ── KPI: Total expenses this month ───────────────────────────────────────
    expenses_this_month = 0
    if farm_ids:
        result = Expense.query.with_entities(
            func.sum(Expense.amount)
        ).filter(
            Expense.farm_id.in_(farm_ids),
            Expense.expense_date >= month_start,
            Expense.expense_date <= today,
        ).scalar()
        expenses_this_month = float(result or 0)

    # ── Chart: 7-day daily egg production ────────────────────────────────────
    chart_labels = []
    chart_data = []
    for i in range(6, -1, -1):
        day = today - timedelta(days=i)
        chart_labels.append(day.strftime('%b %d'))
        if farm_ids:
            day_eggs = ProductionRecord.query.with_entities(
                func.sum(ProductionRecord.egg_count)
            ).filter(
                ProductionRecord.farm_id.in_(farm_ids),
                ProductionRecord.record_date == day,
            ).scalar()
            chart_data.append(int(day_eggs or 0))
        else:
            chart_data.append(0)

    # ── Recent production records (last 5) ───────────────────────────────────
    recent_records = []
    if farm_ids:
        recent_records = ProductionRecord.query.filter(
            ProductionRecord.farm_id.in_(farm_ids)
        ).order_by(ProductionRecord.record_date.desc()).limit(5).all()

    # Build farm lookup for display
    farm_map = {f.id: f.name for f in farms}

    return render_template(
        'dashboard/farmer_dashboard.html',
        title='Farmer Dashboard',
        farms=farms,
        farms_count=len(farms),
        eggs_this_month=eggs_this_month,
        expenses_this_month=expenses_this_month,
        chart_labels=chart_labels,
        chart_data=chart_data,
        recent_records=recent_records,
        farm_map=farm_map,
        today=today,
    )
