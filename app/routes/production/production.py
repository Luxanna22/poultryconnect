"""
Production Blueprint — PoultryConnect 2.0
Handles:
  - Farm registration and management  (GET/POST /production/farms)
  - Daily production log              (GET/POST /production/log)
  - Expense log                       (GET/POST /production/expenses)

Security practices:
  - @login_required on every route
  - Role guard: only FARMER can access
  - Ownership check: farmer can only see/edit their own farms & records
  - farm_id from POST is always re-validated against current_user
  - Input sanitised and typed before DB write
  - IntegrityError (duplicate production date) caught gracefully
  - No raw SQL — all via SQLAlchemy ORM
"""

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort
)
from flask_login import login_required, current_user
from sqlalchemy.exc import IntegrityError
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from app import db
from app.models import Farm, ProductionRecord, Expense, UserRole, ExpenseCategory

production_bp = Blueprint('production', __name__)


# ─── helpers ────────────────────────────────────────────────────────────────

def _require_farmer():
    """Abort with 403 if the current user is not a farmer."""
    if current_user.role != UserRole.FARMER:
        abort(403)


def _get_own_farm_or_404(farm_id: int) -> Farm:
    """
    Return the farm only if it belongs to current_user.
    Raises 404 if not found, 403 if wrong owner.
    """
    farm = Farm.query.get_or_404(farm_id)
    if farm.farmer_id != current_user.id:
        abort(403)
    return farm


def _safe_int(val, default=0) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return default


def _safe_decimal(val, default=Decimal('0.00')) -> Decimal:
    try:
        return Decimal(str(val)).quantize(Decimal('0.01'))
    except (InvalidOperation, TypeError):
        return default


def _parse_date(val) -> date | None:
    """Parse ISO date string; return None on failure."""
    try:
        return datetime.strptime(val, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        return None


def _get_my_farms():
    """Return all active farms for the current farmer."""
    return Farm.query.filter_by(
        farmer_id=current_user.id, is_active=True
    ).order_by(Farm.name).all()


# ════════════════════════════════════════════════════════════════════════════
# FARM MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════

@production_bp.route('/farms')
@login_required
def farms():
    """List all farms belonging to this farmer."""
    _require_farmer()
    my_farms = Farm.query.filter_by(
        farmer_id=current_user.id
    ).order_by(Farm.created_at.desc()).all()
    return render_template(
        'production/farms.html',
        title='My Farms',
        farms=my_farms,
    )


@production_bp.route('/farms/add', methods=['GET', 'POST'])
@login_required
def farm_add():
    """Register a new farm."""
    _require_farmer()

    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        location    = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()
        flock_size  = _safe_int(request.form.get('flock_size'), default=0)

        errors = []
        if not name:
            errors.append('Farm name is required.')
        if len(name) > 120:
            errors.append('Farm name must be 120 characters or fewer.')
        if flock_size < 0:
            errors.append('Flock size cannot be negative.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template(
                'production/farm_form.html',
                title='Add Farm', action='add',
                form_data=request.form,
            )

        farm = Farm(
            farmer_id=current_user.id,
            name=name,
            location=location or None,
            description=description or None,
            flock_size=flock_size,
            is_active=True,
        )
        db.session.add(farm)
        db.session.commit()
        flash(f'Farm "{farm.name}" registered successfully.', 'success')
        return redirect(url_for('production.farms'))

    return render_template(
        'production/farm_form.html',
        title='Add Farm', action='add',
        form_data={},
    )


@production_bp.route('/farms/<int:farm_id>/edit', methods=['GET', 'POST'])
@login_required
def farm_edit(farm_id: int):
    """Edit an existing farm."""
    _require_farmer()
    farm = _get_own_farm_or_404(farm_id)

    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        location    = request.form.get('location', '').strip()
        description = request.form.get('description', '').strip()
        flock_size  = _safe_int(request.form.get('flock_size'), default=farm.flock_size)

        errors = []
        if not name:
            errors.append('Farm name is required.')
        if len(name) > 120:
            errors.append('Farm name must be 120 characters or fewer.')
        if flock_size < 0:
            errors.append('Flock size cannot be negative.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template(
                'production/farm_form.html',
                title='Edit Farm', action='edit',
                farm=farm, form_data=request.form,
            )

        farm.name        = name
        farm.location    = location or None
        farm.description = description or None
        farm.flock_size  = flock_size
        db.session.commit()
        flash(f'Farm "{farm.name}" updated.', 'success')
        return redirect(url_for('production.farms'))

    return render_template(
        'production/farm_form.html',
        title='Edit Farm', action='edit',
        farm=farm, form_data={},
    )


@production_bp.route('/farms/<int:farm_id>/deactivate', methods=['POST'])
@login_required
def farm_deactivate(farm_id: int):
    """Soft-delete: mark farm as inactive."""
    _require_farmer()
    farm = _get_own_farm_or_404(farm_id)
    farm.is_active = False
    db.session.commit()
    flash(f'Farm "{farm.name}" has been deactivated.', 'success')
    return redirect(url_for('production.farms'))


# ════════════════════════════════════════════════════════════════════════════
# PRODUCTION LOG
# ════════════════════════════════════════════════════════════════════════════

@production_bp.route('/log')
@login_required
def log():
    """View all production records for this farmer."""
    _require_farmer()
    farms = _get_my_farms()
    farm_ids = [f.id for f in farms]
    farm_map = {f.id: f.name for f in farms}

    # Filter by farm if ?farm_id= provided
    selected_farm_id = _safe_int(request.args.get('farm_id'), default=0)
    query = ProductionRecord.query.filter(
        ProductionRecord.farm_id.in_(farm_ids)
    )
    if selected_farm_id and selected_farm_id in farm_ids:
        query = query.filter(ProductionRecord.farm_id == selected_farm_id)

    records = query.order_by(ProductionRecord.record_date.desc()).limit(60).all()

    return render_template(
        'production/log.html',
        title='Production Log',
        farms=farms,
        farm_map=farm_map,
        records=records,
        selected_farm_id=selected_farm_id,
        today=date.today(),
    )


@production_bp.route('/log/add', methods=['GET', 'POST'])
@login_required
def log_add():
    """Add a daily production record."""
    _require_farmer()
    farms = _get_my_farms()

    if not farms:
        flash('You need to register a farm before logging production data.', 'error')
        return redirect(url_for('production.farm_add'))

    if request.method == 'POST':
        farm_id     = _safe_int(request.form.get('farm_id'))
        record_date = _parse_date(request.form.get('record_date'))
        egg_count   = _safe_int(request.form.get('egg_count'), default=0)
        feed_kg     = _safe_decimal(request.form.get('feed_kg'))
        feed_cost   = _safe_decimal(request.form.get('feed_cost'))
        egg_price_raw = request.form.get('egg_price', '').strip()
        egg_price   = _safe_decimal(egg_price_raw) if egg_price_raw else None
        mortality   = _safe_int(request.form.get('mortality'), default=0)
        notes       = request.form.get('notes', '').strip()

        # ── validation ──────────────────────────────────────────────────
        errors = []
        farm_ids = [f.id for f in farms]

        if farm_id not in farm_ids:
            errors.append('Invalid farm selected.')
        if not record_date:
            errors.append('A valid date is required.')
        elif record_date > date.today():
            errors.append('Production date cannot be in the future.')
        if egg_count < 0:
            errors.append('Egg count cannot be negative.')
        if feed_kg < 0:
            errors.append('Feed consumption cannot be negative.')
        if feed_cost < 0:
            errors.append('Feed cost cannot be negative.')
        if mortality < 0:
            errors.append('Mortality count cannot be negative.')
        if egg_price is not None and egg_price < 0:
            errors.append('Egg selling price cannot be negative.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template(
                'production/log_form.html',
                title='Log Production', action='add',
                farms=farms, form_data=request.form,
                today=date.today(),
            )

        record = ProductionRecord(
            farm_id=farm_id,
            user_id=current_user.id,
            record_date=record_date,
            egg_count=egg_count,
            feed_kg=feed_kg,
            feed_cost=feed_cost,
            egg_price=egg_price,
            mortality=mortality,
            notes=notes or None,
        )
        db.session.add(record)
        try:
            db.session.commit()
            flash('Production record saved.', 'success')
            return redirect(url_for('production.log'))
        except IntegrityError:
            db.session.rollback()
            flash(
                'A production record for that farm on that date already exists. '
                'Please edit the existing record instead.',
                'error'
            )
            return render_template(
                'production/log_form.html',
                title='Log Production', action='add',
                farms=farms, form_data=request.form,
                today=date.today(),
            )

    return render_template(
        'production/log_form.html',
        title='Log Production', action='add',
        farms=farms, form_data={'record_date': date.today().isoformat()},
        today=date.today(),
    )


@production_bp.route('/log/<int:record_id>/edit', methods=['GET', 'POST'])
@login_required
def log_edit(record_id: int):
    """Edit an existing production record."""
    _require_farmer()
    record = ProductionRecord.query.get_or_404(record_id)

    # Ownership check via farm
    farm = _get_own_farm_or_404(record.farm_id)
    farms = _get_my_farms()

    if request.method == 'POST':
        egg_count = _safe_int(request.form.get('egg_count'), default=record.egg_count)
        feed_kg   = _safe_decimal(request.form.get('feed_kg'))
        feed_cost = _safe_decimal(request.form.get('feed_cost'))
        egg_price_raw = request.form.get('egg_price', '').strip()
        egg_price = _safe_decimal(egg_price_raw) if egg_price_raw else None
        mortality = _safe_int(request.form.get('mortality'), default=record.mortality)
        notes     = request.form.get('notes', '').strip()

        errors = []
        if egg_count < 0:
            errors.append('Egg count cannot be negative.')
        if feed_kg < 0:
            errors.append('Feed consumption cannot be negative.')
        if feed_cost < 0:
            errors.append('Feed cost cannot be negative.')
        if mortality < 0:
            errors.append('Mortality count cannot be negative.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template(
                'production/log_form.html',
                title='Edit Record', action='edit',
                farms=farms, record=record, form_data=request.form,
                today=date.today(),
            )

        record.egg_count = egg_count
        record.feed_kg   = feed_kg
        record.feed_cost = feed_cost
        record.egg_price = egg_price
        record.mortality = mortality
        record.notes     = notes or None
        db.session.commit()
        flash('Production record updated.', 'success')
        return redirect(url_for('production.log'))

    return render_template(
        'production/log_form.html',
        title='Edit Record', action='edit',
        farms=farms, record=record, form_data={},
        today=date.today(),
    )


@production_bp.route('/log/<int:record_id>/delete', methods=['POST'])
@login_required
def log_delete(record_id: int):
    """Delete a production record."""
    _require_farmer()
    record = ProductionRecord.query.get_or_404(record_id)
    _get_own_farm_or_404(record.farm_id)  # ownership check

    db.session.delete(record)
    db.session.commit()
    flash('Production record deleted.', 'success')
    return redirect(url_for('production.log'))


# ════════════════════════════════════════════════════════════════════════════
# EXPENSE LOG
# ════════════════════════════════════════════════════════════════════════════

@production_bp.route('/expenses')
@login_required
def expenses():
    """View all expense records for this farmer."""
    _require_farmer()
    farms = _get_my_farms()
    farm_ids = [f.id for f in farms]
    farm_map = {f.id: f.name for f in farms}

    selected_farm_id = _safe_int(request.args.get('farm_id'), default=0)
    query = Expense.query.filter(Expense.farm_id.in_(farm_ids))
    if selected_farm_id and selected_farm_id in farm_ids:
        query = query.filter(Expense.farm_id == selected_farm_id)

    expense_records = query.order_by(Expense.expense_date.desc()).limit(60).all()

    return render_template(
        'production/expenses.html',
        title='Expense Log',
        farms=farms,
        farm_map=farm_map,
        expenses=expense_records,
        selected_farm_id=selected_farm_id,
        categories=ExpenseCategory,
        today=date.today(),
    )


@production_bp.route('/expenses/add', methods=['GET', 'POST'])
@login_required
def expense_add():
    """Log a new expense."""
    _require_farmer()
    farms = _get_my_farms()

    if not farms:
        flash('You need to register a farm before logging expenses.', 'error')
        return redirect(url_for('production.farm_add'))

    if request.method == 'POST':
        farm_id      = _safe_int(request.form.get('farm_id'))
        expense_date = _parse_date(request.form.get('expense_date'))
        category_str = request.form.get('category', '').strip().lower()
        amount       = _safe_decimal(request.form.get('amount'))
        description  = request.form.get('description', '').strip()

        errors = []
        farm_ids = [f.id for f in farms]
        valid_categories = {e.value for e in ExpenseCategory}

        if farm_id not in farm_ids:
            errors.append('Invalid farm selected.')
        if not expense_date:
            errors.append('A valid date is required.')
        elif expense_date > date.today():
            errors.append('Expense date cannot be in the future.')
        if category_str not in valid_categories:
            errors.append('Please select a valid expense category.')
        if amount <= 0:
            errors.append('Amount must be greater than zero.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template(
                'production/expense_form.html',
                title='Log Expense', action='add',
                farms=farms, form_data=request.form,
                categories=ExpenseCategory, today=date.today(),
            )

        expense = Expense(
            farm_id=farm_id,
            user_id=current_user.id,
            expense_date=expense_date,
            category=ExpenseCategory(category_str),
            amount=amount,
            description=description or None,
        )
        db.session.add(expense)
        db.session.commit()
        flash('Expense recorded.', 'success')
        return redirect(url_for('production.expenses'))

    return render_template(
        'production/expense_form.html',
        title='Log Expense', action='add',
        farms=farms, form_data={'expense_date': date.today().isoformat()},
        categories=ExpenseCategory, today=date.today(),
    )


@production_bp.route('/expenses/<int:expense_id>/edit', methods=['GET', 'POST'])
@login_required
def expense_edit(expense_id: int):
    """Edit an existing expense."""
    _require_farmer()
    expense = Expense.query.get_or_404(expense_id)
    _get_own_farm_or_404(expense.farm_id)  # ownership
    farms = _get_my_farms()
    valid_categories = {e.value for e in ExpenseCategory}

    if request.method == 'POST':
        category_str = request.form.get('category', '').strip().lower()
        amount       = _safe_decimal(request.form.get('amount'))
        description  = request.form.get('description', '').strip()

        errors = []
        if category_str not in valid_categories:
            errors.append('Please select a valid expense category.')
        if amount <= 0:
            errors.append('Amount must be greater than zero.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template(
                'production/expense_form.html',
                title='Edit Expense', action='edit',
                farms=farms, expense=expense, form_data=request.form,
                categories=ExpenseCategory, today=date.today(),
            )

        expense.category    = ExpenseCategory(category_str)
        expense.amount      = amount
        expense.description = description or None
        db.session.commit()
        flash('Expense updated.', 'success')
        return redirect(url_for('production.expenses'))

    return render_template(
        'production/expense_form.html',
        title='Edit Expense', action='edit',
        farms=farms, expense=expense, form_data={},
        farm_map={f.id: f.name for f in farms},
        categories=ExpenseCategory, today=date.today(),
    )


@production_bp.route('/expenses/<int:expense_id>/delete', methods=['POST'])
@login_required
def expense_delete(expense_id: int):
    """Delete an expense record."""
    _require_farmer()
    expense = Expense.query.get_or_404(expense_id)
    _get_own_farm_or_404(expense.farm_id)  # ownership

    db.session.delete(expense)
    db.session.commit()
    flash('Expense deleted.', 'success')
    return redirect(url_for('production.expenses'))


# ════════════════════════════════════════════════════════════════════════════
# Quick-log from Dashboard (POST from dashboard widget)
# ════════════════════════════════════════════════════════════════════════════

@production_bp.route('/quick-log', methods=['POST'])
@login_required
def quick_log():
    """
    Receives the quick-log form submitted from the farmer dashboard widget.
    Redirects back to dashboard with a flash message.
    """
    _require_farmer()
    farms = _get_my_farms()
    farm_ids = [f.id for f in farms]

    farm_id     = _safe_int(request.form.get('farm_id'))
    record_date = _parse_date(request.form.get('record_date'))
    egg_count   = _safe_int(request.form.get('egg_count'), default=0)
    feed_kg     = _safe_decimal(request.form.get('feed_kg'))
    mortality   = _safe_int(request.form.get('mortality'), default=0)

    # Basic validation
    if farm_id not in farm_ids:
        flash('Invalid farm selected.', 'error')
        return redirect(url_for('dashboard.farmer'))
    if not record_date or record_date > date.today():
        flash('Invalid production date.', 'error')
        return redirect(url_for('dashboard.farmer'))
    if egg_count < 0 or mortality < 0 or feed_kg < 0:
        flash('Values cannot be negative.', 'error')
        return redirect(url_for('dashboard.farmer'))

    record = ProductionRecord(
        farm_id=farm_id,
        user_id=current_user.id,
        record_date=record_date,
        egg_count=egg_count,
        feed_kg=feed_kg,
        feed_cost=Decimal('0.00'),
        mortality=mortality,
    )
    db.session.add(record)
    try:
        db.session.commit()
        flash('Daily log saved successfully.', 'success')
    except IntegrityError:
        db.session.rollback()
        flash(
            'A record for that farm on that date already exists. '
            'Visit the Production Log to edit it.',
            'error'
        )
    return redirect(url_for('dashboard.farmer'))
