from flask import Blueprint, render_template, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import UserRole, Farm, ProductionRecord, Expense
from datetime import date, timedelta
from sqlalchemy import func

dashboard_bp = Blueprint('dashboard', __name__)


def _build_market_intelligence(recent_records, monthly_expenses, farm_count, today):
    """Build profit guidance and demand forecast with visualization data from real database records."""
    records = list(recent_records or [])
    eggs = [int(getattr(record, 'egg_count', 0) or 0) for record in records]
    prices = [float(record.egg_price) for record in records if getattr(record, 'egg_price', None)]
    feed_costs = [float(record.feed_cost) for record in records if getattr(record, 'feed_cost', None)]
    dates = [record.record_date for record in records if getattr(record, 'record_date', None)]

    avg_daily_eggs = round(sum(eggs) / len(eggs), 1) if eggs else 0
    avg_selling_price = round(sum(prices) / len(prices), 2) if prices else 7.5
    avg_feed_cost = round(sum(feed_costs) / len(feed_costs), 2) if feed_costs else 0.0
    base_cost_per_egg = round((avg_feed_cost / avg_daily_eggs) if avg_daily_eggs else 1.8, 2)

    # Build price trend chart data (last 7 days from records)
    price_trend_labels = [d.strftime('%a') for d in sorted(dates[-7:])]
    price_trend_data = sorted(prices[-7:]) if prices else []
    
    # Calculate profit margins
    margins = []
    for price in prices:
        margin = round(((price - base_cost_per_egg) / price * 100) if price > 0 else 0, 1)
        margins.append(margin)
    avg_margin = round(sum(margins) / len(margins), 1) if margins else 0

    seasonal_factors = {
        1: 0.95, 2: 0.93, 3: 0.97, 4: 1.02, 5: 1.06, 6: 1.11,
        7: 1.14, 8: 1.1, 9: 1.05, 10: 1.01, 11: 1.0, 12: 1.08,
    }
    season_factor = seasonal_factors.get(today.month, 1.0)
    demand_forecast = round(avg_daily_eggs * season_factor, 1)

    recommended_price = round(max(avg_selling_price * 1.06, base_cost_per_egg * 1.7, 7.2), 2)
    projected_eggs = round(avg_daily_eggs * 7 * season_factor, 0)
    estimated_revenue = round(projected_eggs * recommended_price, 2)
    estimated_cost = round((projected_eggs * max(base_cost_per_egg, 1.5)) + (monthly_expenses / 4), 2)
    projected_profit = round(estimated_revenue - estimated_cost, 2)

    # Build forecast comparison data
    forecast_weeks = ['Week 1', 'Week 2', 'Week 3', 'Week 4']
    actual_data = [avg_daily_eggs * 7] * 4
    forecast_data = [round(avg_daily_eggs * 7 * season_factor * (1 + i*0.05), 0) for i in range(4)]

    if projected_profit > 0:
        sell_window = 'this week'
        guidance = 'Pricing slightly above the recent average can lift margin without slowing movement.'
    else:
        sell_window = 'within two days'
        guidance = 'Keep pricing competitive and move smaller batches quickly to protect cash flow.'

    if demand_forecast > avg_daily_eggs * 1.05:
        demand_signal = 'High demand expected'
        forecast_summary = 'Demand is trending up, so prepare for stronger order volume in the next week.'
        production_plan = 'Increase prep for the coming week and schedule pickups earlier in the cycle.'
        allocation = 'Reserve 60% of output for regular buyers and 40% for flexible channels.'
    elif demand_forecast < avg_daily_eggs * 0.95:
        demand_signal = 'Steady demand'
        forecast_summary = 'Demand is stable, so it is better to keep output measured and avoid overstock.'
        production_plan = 'Hold output steady and prioritize smaller, more frequent dispatches.'
        allocation = 'Keep 70% for direct buyers and 30% for quick-turnover sales.'
    else:
        demand_signal = 'Balanced demand'
        forecast_summary = 'The short-term outlook is balanced, so keep production steady and review again midweek.'
        production_plan = 'Maintain current output and adjust only if orders change.'
        allocation = 'Split volume evenly between dependable buyers and flexible channels.'

    buyer_leads = [
        {'name': 'Neighborhood groceries', 'note': 'Reliable weekly volumes for consistent supply', 'channel': 'Daily buyers'},
        {'name': 'School canteens', 'note': 'Good fit for medium-sized batches', 'channel': 'Institutional'},
        {'name': 'Restaurants', 'note': 'Higher value when supply stays fresh and regular', 'channel': 'Premium outlets'},
    ]

    return {
        'sell_window': sell_window,
        'guidance': guidance,
        'recommended_price': recommended_price,
        'projected_profit': projected_profit,
        'demand_forecast': demand_forecast,
        'demand_signal': demand_signal,
        'forecast_summary': forecast_summary,
        'production_plan': production_plan,
        'allocation': allocation,
        'buyer_leads': buyer_leads,
        'farm_count': farm_count,
        'price_trend_labels': price_trend_labels,
        'price_trend_data': price_trend_data,
        'avg_margin': avg_margin,
        'forecast_weeks': forecast_weeks,
        'actual_data': actual_data,
        'forecast_data': forecast_data,
        'base_cost_per_egg': base_cost_per_egg,
        'avg_selling_price': avg_selling_price,
    }


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
    market_intelligence = _build_market_intelligence(
        recent_records,
        expenses_this_month,
        len(farms),
        today,
    )

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
        market_intelligence=market_intelligence,
        today=today,
    )
