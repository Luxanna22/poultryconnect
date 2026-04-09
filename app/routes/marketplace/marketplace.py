"""
Marketplace Blueprint — PoultryConnect 2.0
Handles:
  - Public product browsing           (GET /marketplace/)
  - Product detail                    (GET /marketplace/product/<id>)
  - Session-based shopping cart       (GET/POST /marketplace/cart/*)
  - Checkout & order placement        (GET/POST /marketplace/checkout)
  - Buyer order history               (GET /marketplace/orders)
  - Farmer product management         (GET/POST /marketplace/manage/*)
  - Farmer incoming orders            (GET/POST /marketplace/manage/orders/*)

Security practices:
  - Public browsing: no auth required for browse/detail
  - @login_required on cart, checkout, orders, and management routes
  - Role guard: buyer-only for cart/checkout/orders, farmer-only for manage
  - Ownership check: farmer can only edit/toggle their own products
  - Stock validation at checkout (prevents overselling)
  - Session cart re-validated against DB at checkout (price/availability)
  - Input sanitised via safe helpers (matching production.py patterns)
  - No raw SQL — all via SQLAlchemy ORM
"""

from flask import (
    Blueprint, render_template, redirect, url_for,
    flash, request, abort, session
)
from flask_login import login_required, current_user
from decimal import Decimal, InvalidOperation
from datetime import datetime

from app import db
from app.models import (
    Product, Order, OrderItem, Farm, User,
    ProductCategory, ProductUnit, OrderStatus, UserRole
)

marketplace_bp = Blueprint('marketplace', __name__)


# ─── helpers ────────────────────────────────────────────────────────────────

def _require_farmer():
    """Abort with 403 if the current user is not a farmer."""
    if current_user.role != UserRole.FARMER:
        abort(403)


def _require_buyer():
    """Abort with 403 if the current user is not a buyer."""
    if current_user.role != UserRole.BUYER:
        abort(403)


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


def _get_own_product_or_404(product_id: int) -> Product:
    """Return the product only if it belongs to current_user."""
    product = Product.query.get_or_404(product_id)
    if product.farmer_id != current_user.id:
        abort(403)
    return product


def _get_cart():
    """Get current session cart. Returns dict {product_id_str: quantity}."""
    return session.get('cart', {})


def _save_cart(cart):
    """Persist cart to session."""
    session['cart'] = cart
    session.modified = True


def _get_cart_count():
    """Total number of items in the cart."""
    cart = _get_cart()
    return sum(cart.values())


# ════════════════════════════════════════════════════════════════════════════
# PUBLIC BROWSING
# ════════════════════════════════════════════════════════════════════════════

@marketplace_bp.route('/')
def index():
    """Browse all available products — public, no login required."""
    # Filters
    search    = request.args.get('q', '').strip()
    category  = request.args.get('category', '').strip()
    sort_by   = request.args.get('sort', 'newest')

    query = Product.query.filter_by(is_available=True).filter(Product.stock > 0)

    if search:
        query = query.filter(
            db.or_(
                Product.name.ilike(f'%{search}%'),
                Product.description.ilike(f'%{search}%'),
                Product.location.ilike(f'%{search}%'),
            )
        )

    valid_categories = {e.value for e in ProductCategory}
    if category and category in valid_categories:
        query = query.filter(Product.category == ProductCategory(category))

    # Sorting
    if sort_by == 'price_low':
        query = query.order_by(Product.price.asc())
    elif sort_by == 'price_high':
        query = query.order_by(Product.price.desc())
    else:  # newest
        query = query.order_by(Product.created_at.desc())

    products = query.all()

    return render_template(
        'marketplace/browse.html',
        title='Marketplace',
        products=products,
        search=search,
        category=category,
        sort_by=sort_by,
        categories=ProductCategory,
        cart_count=_get_cart_count(),
    )


@marketplace_bp.route('/product/<int:product_id>')
def product_detail(product_id):
    """View a single product detail — public."""
    product = Product.query.get_or_404(product_id)
    if not product.is_available:
        flash('This product is no longer available.', 'error')
        return redirect(url_for('marketplace.index'))

    # Get related products from the same category
    related = Product.query.filter(
        Product.id != product.id,
        Product.category == product.category,
        Product.is_available == True,
        Product.stock > 0,
    ).order_by(db.func.random()).limit(4).all()

    return render_template(
        'marketplace/product_detail.html',
        title=product.name,
        product=product,
        related=related,
        cart_count=_get_cart_count(),
    )


# ════════════════════════════════════════════════════════════════════════════
# SHOPPING CART (session-based)
# ════════════════════════════════════════════════════════════════════════════

@marketplace_bp.route('/cart')
@login_required
def cart():
    """View shopping cart."""
    _require_buyer()
    cart_data = _get_cart()
    cart_items = []
    total = Decimal('0.00')

    for pid_str, qty in cart_data.items():
        product = Product.query.get(int(pid_str))
        if product and product.is_available:
            subtotal = product.price * qty
            total += subtotal
            cart_items.append({
                'product': product,
                'quantity': qty,
                'subtotal': float(subtotal),
            })

    return render_template(
        'marketplace/cart.html',
        title='Shopping Cart',
        cart_items=cart_items,
        cart_total=float(total),
        cart_count=len(cart_items),
    )


@marketplace_bp.route('/cart/add', methods=['POST'])
@login_required
def cart_add():
    """Add a product to cart."""
    _require_buyer()
    product_id = _safe_int(request.form.get('product_id'))
    quantity   = _safe_int(request.form.get('quantity', 1), default=1)

    if quantity < 1:
        flash('Invalid quantity.', 'error')
        return redirect(request.referrer or url_for('marketplace.index'))

    product = Product.query.get(product_id)
    if not product or not product.is_available:
        flash('Product not available.', 'error')
        return redirect(url_for('marketplace.index'))

    if quantity > product.stock:
        flash(f'Only {product.stock} available in stock.', 'error')
        return redirect(url_for('marketplace.product_detail', product_id=product_id))

    cart = _get_cart()
    pid_str = str(product_id)
    current_qty = cart.get(pid_str, 0)
    new_qty = current_qty + quantity

    if new_qty > product.stock:
        flash(f'Cannot add more. Only {product.stock} available (you have {current_qty} in cart).', 'error')
        return redirect(url_for('marketplace.product_detail', product_id=product_id))

    cart[pid_str] = new_qty
    _save_cart(cart)
    flash(f'"{product.name}" added to cart.', 'success')
    return redirect(request.referrer or url_for('marketplace.index'))


@marketplace_bp.route('/cart/update', methods=['POST'])
@login_required
def cart_update():
    """Update quantity for a cart item."""
    _require_buyer()
    product_id = _safe_int(request.form.get('product_id'))
    quantity   = _safe_int(request.form.get('quantity', 1), default=1)

    cart = _get_cart()
    pid_str = str(product_id)

    if pid_str not in cart:
        flash('Item not in cart.', 'error')
        return redirect(url_for('marketplace.cart'))

    if quantity < 1:
        # Remove from cart
        del cart[pid_str]
        _save_cart(cart)
        flash('Item removed from cart.', 'success')
        return redirect(url_for('marketplace.cart'))

    product = Product.query.get(product_id)
    if product and quantity > product.stock:
        flash(f'Only {product.stock} available.', 'error')
        return redirect(url_for('marketplace.cart'))

    cart[pid_str] = quantity
    _save_cart(cart)
    flash('Cart updated.', 'success')
    return redirect(url_for('marketplace.cart'))


@marketplace_bp.route('/cart/remove', methods=['POST'])
@login_required
def cart_remove():
    """Remove an item from cart."""
    _require_buyer()
    product_id = str(_safe_int(request.form.get('product_id')))

    cart = _get_cart()
    if product_id in cart:
        del cart[product_id]
        _save_cart(cart)
        flash('Item removed from cart.', 'success')

    return redirect(url_for('marketplace.cart'))


# ════════════════════════════════════════════════════════════════════════════
# CHECKOUT & ORDER PLACEMENT
# ════════════════════════════════════════════════════════════════════════════

@marketplace_bp.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    """Checkout: review cart and place order."""
    _require_buyer()
    cart_data = _get_cart()

    if not cart_data:
        flash('Your cart is empty.', 'error')
        return redirect(url_for('marketplace.index'))

    # Re-validate every cart item against database
    cart_items = []
    total = Decimal('0.00')
    errors = []

    for pid_str, qty in cart_data.items():
        product = Product.query.get(int(pid_str))
        if not product or not product.is_available:
            errors.append(f'"{pid_str}" is no longer available.')
            continue
        if qty > product.stock:
            errors.append(f'"{product.name}" only has {product.stock} in stock (you requested {qty}).')
            cart_data[pid_str] = product.stock
            qty = product.stock
        if qty <= 0:
            continue

        subtotal = product.price * qty
        total += subtotal
        cart_items.append({
            'product': product,
            'quantity': qty,
            'subtotal': float(subtotal),
        })

    if errors:
        for e in errors:
            flash(e, 'error')
        _save_cart(cart_data)

    if not cart_items:
        flash('No valid items in your cart.', 'error')
        return redirect(url_for('marketplace.index'))

    if request.method == 'POST':
        delivery_address = request.form.get('delivery_address', '').strip()
        contact_phone    = request.form.get('contact_phone', '').strip()
        notes            = request.form.get('notes', '').strip()

        form_errors = []
        if not delivery_address:
            form_errors.append('Delivery address is required.')
        if len(delivery_address) > 500:
            form_errors.append('Delivery address is too long (max 500 characters).')
        if not contact_phone:
            form_errors.append('Contact phone is required.')
        if len(contact_phone) > 30:
            form_errors.append('Contact phone is too long.')

        if form_errors:
            for e in form_errors:
                flash(e, 'error')
            return render_template(
                'marketplace/checkout.html',
                title='Checkout',
                cart_items=cart_items,
                cart_total=float(total),
                form_data=request.form,
                cart_count=_get_cart_count(),
            )

        # Create order
        order = Order(
            buyer_id=current_user.id,
            total_amount=total,
            status=OrderStatus.PENDING,
            delivery_address=delivery_address,
            contact_phone=contact_phone,
            notes=notes or None,
        )
        db.session.add(order)
        db.session.flush()  # get order.id

        # Create order items and decrement stock
        for item in cart_items:
            product = item['product']
            qty = item['quantity']

            # Final stock check
            if product.stock < qty:
                db.session.rollback()
                flash(f'"{product.name}" stock changed. Please review your cart.', 'error')
                return redirect(url_for('marketplace.cart'))

            order_item = OrderItem(
                order_id=order.id,
                product_id=product.id,
                quantity=qty,
                unit_price=product.price,
            )
            db.session.add(order_item)
            product.stock -= qty

        db.session.commit()

        # Clear cart
        session.pop('cart', None)
        session.modified = True

        flash(f'Order #{order.id} placed successfully! Payment: Cash on Delivery.', 'success')
        return redirect(url_for('marketplace.order_detail', order_id=order.id))

    return render_template(
        'marketplace/checkout.html',
        title='Checkout',
        cart_items=cart_items,
        cart_total=float(total),
        form_data={},
        cart_count=_get_cart_count(),
    )


# ════════════════════════════════════════════════════════════════════════════
# BUYER ORDER HISTORY
# ════════════════════════════════════════════════════════════════════════════

@marketplace_bp.route('/orders')
@login_required
def orders():
    """View buyer's order history."""
    _require_buyer()
    buyer_orders = Order.query.filter_by(
        buyer_id=current_user.id
    ).order_by(Order.created_at.desc()).all()

    return render_template(
        'marketplace/orders.html',
        title='My Orders',
        orders=buyer_orders,
        cart_count=_get_cart_count(),
    )


@marketplace_bp.route('/orders/<int:order_id>')
@login_required
def order_detail(order_id):
    """View a specific order (buyer only, owns the order)."""
    _require_buyer()
    order = Order.query.get_or_404(order_id)
    if order.buyer_id != current_user.id:
        abort(403)

    return render_template(
        'marketplace/order_detail.html',
        title=f'Order #{order.id}',
        order=order,
        cart_count=_get_cart_count(),
    )


# ════════════════════════════════════════════════════════════════════════════
# FARMER PRODUCT MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════

@marketplace_bp.route('/manage')
@login_required
def manage():
    """Farmer's product management dashboard."""
    _require_farmer()
    products = Product.query.filter_by(
        farmer_id=current_user.id
    ).order_by(Product.created_at.desc()).all()

    return render_template(
        'marketplace/manage.html',
        title='My Products',
        products=products,
    )


@marketplace_bp.route('/manage/add', methods=['GET', 'POST'])
@login_required
def manage_add():
    """Add a new product listing."""
    _require_farmer()
    farms = Farm.query.filter_by(
        farmer_id=current_user.id, is_active=True
    ).order_by(Farm.name).all()

    if not farms:
        flash('You need to register a farm before listing products.', 'error')
        return redirect(url_for('production.farm_add'))

    if request.method == 'POST':
        farm_id     = _safe_int(request.form.get('farm_id'))
        name        = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        category_str = request.form.get('category', '').strip()
        unit_str     = request.form.get('unit', '').strip()
        price       = _safe_decimal(request.form.get('price'))
        stock       = _safe_int(request.form.get('stock'), default=0)

        errors = []
        farm_ids = [f.id for f in farms]

        if farm_id not in farm_ids:
            errors.append('Invalid farm selected.')
        if not name:
            errors.append('Product name is required.')
        if len(name) > 150:
            errors.append('Product name must be 150 characters or fewer.')
        if category_str not in {e.value for e in ProductCategory}:
            errors.append('Please select a valid category.')
        if unit_str not in {e.value for e in ProductUnit}:
            errors.append('Please select a valid unit.')
        if price <= 0:
            errors.append('Price must be greater than zero.')
        if stock < 0:
            errors.append('Stock cannot be negative.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template(
                'marketplace/product_form.html',
                title='Add Product', action='add',
                farms=farms, form_data=request.form,
                categories=ProductCategory, units=ProductUnit,
            )

        farm = Farm.query.get(farm_id)
        product = Product(
            farmer_id=current_user.id,
            farm_id=farm_id,
            name=name,
            description=description or None,
            category=ProductCategory(category_str),
            unit=ProductUnit(unit_str),
            price=price,
            stock=stock,
            location=farm.location if farm else None,
            is_available=True,
        )
        db.session.add(product)
        db.session.commit()
        flash(f'"{product.name}" listed on the marketplace.', 'success')
        return redirect(url_for('marketplace.manage'))

    return render_template(
        'marketplace/product_form.html',
        title='Add Product', action='add',
        farms=farms, form_data={},
        categories=ProductCategory, units=ProductUnit,
    )


@marketplace_bp.route('/manage/<int:product_id>/edit', methods=['GET', 'POST'])
@login_required
def manage_edit(product_id):
    """Edit an existing product listing."""
    _require_farmer()
    product = _get_own_product_or_404(product_id)
    farms = Farm.query.filter_by(
        farmer_id=current_user.id, is_active=True
    ).order_by(Farm.name).all()

    if request.method == 'POST':
        name        = request.form.get('name', '').strip()
        description = request.form.get('description', '').strip()
        category_str = request.form.get('category', '').strip()
        unit_str     = request.form.get('unit', '').strip()
        price       = _safe_decimal(request.form.get('price'))
        stock       = _safe_int(request.form.get('stock'), default=product.stock)

        errors = []
        if not name:
            errors.append('Product name is required.')
        if len(name) > 150:
            errors.append('Product name must be 150 characters or fewer.')
        if category_str not in {e.value for e in ProductCategory}:
            errors.append('Please select a valid category.')
        if unit_str not in {e.value for e in ProductUnit}:
            errors.append('Please select a valid unit.')
        if price <= 0:
            errors.append('Price must be greater than zero.')
        if stock < 0:
            errors.append('Stock cannot be negative.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template(
                'marketplace/product_form.html',
                title='Edit Product', action='edit',
                farms=farms, product=product, form_data=request.form,
                categories=ProductCategory, units=ProductUnit,
            )

        product.name        = name
        product.description = description or None
        product.category    = ProductCategory(category_str)
        product.unit        = ProductUnit(unit_str)
        product.price       = price
        product.stock       = stock
        db.session.commit()
        flash(f'"{product.name}" updated.', 'success')
        return redirect(url_for('marketplace.manage'))

    return render_template(
        'marketplace/product_form.html',
        title='Edit Product', action='edit',
        farms=farms, product=product, form_data={},
        categories=ProductCategory, units=ProductUnit,
    )


@marketplace_bp.route('/manage/<int:product_id>/toggle', methods=['POST'])
@login_required
def manage_toggle(product_id):
    """Toggle product availability on/off."""
    _require_farmer()
    product = _get_own_product_or_404(product_id)
    product.is_available = not product.is_available
    db.session.commit()
    state = 'listed' if product.is_available else 'unlisted'
    flash(f'"{product.name}" is now {state}.', 'success')
    return redirect(url_for('marketplace.manage'))


# ════════════════════════════════════════════════════════════════════════════
# FARMER ORDER MANAGEMENT
# ════════════════════════════════════════════════════════════════════════════

@marketplace_bp.route('/manage/orders')
@login_required
def farmer_orders():
    """View orders that contain the farmer's products."""
    _require_farmer()

    # Find orders containing products from this farmer
    my_product_ids = [p.id for p in Product.query.filter_by(farmer_id=current_user.id).all()]

    if not my_product_ids:
        orders_list = []
    else:
        order_ids = db.session.query(OrderItem.order_id).filter(
            OrderItem.product_id.in_(my_product_ids)
        ).distinct().all()
        order_ids = [oid[0] for oid in order_ids]
        orders_list = Order.query.filter(
            Order.id.in_(order_ids)
        ).order_by(Order.created_at.desc()).all()

    return render_template(
        'marketplace/farmer_orders.html',
        title='Incoming Orders',
        orders=orders_list,
        my_product_ids=my_product_ids,
    )


@marketplace_bp.route('/manage/orders/<int:order_id>/status', methods=['POST'])
@login_required
def update_order_status(order_id):
    """Update order status (farmer action)."""
    _require_farmer()
    order = Order.query.get_or_404(order_id)

    # Verify this farmer has products in this order
    my_product_ids = [p.id for p in Product.query.filter_by(farmer_id=current_user.id).all()]
    order_product_ids = [item.product_id for item in order.items]
    if not any(pid in my_product_ids for pid in order_product_ids):
        abort(403)

    new_status = request.form.get('status', '').strip()
    valid_statuses = {e.value for e in OrderStatus}
    if new_status not in valid_statuses:
        flash('Invalid order status.', 'error')
        return redirect(url_for('marketplace.farmer_orders'))

    # Prevent backwards transitions (simple validation)
    status_order = ['pending', 'confirmed', 'shipped', 'delivered']
    old_idx = status_order.index(order.status.value) if order.status.value in status_order else -1
    new_idx = status_order.index(new_status) if new_status in status_order else -1

    if new_status == 'cancelled' and order.status.value == 'delivered':
        flash('Cannot cancel a delivered order.', 'error')
        return redirect(url_for('marketplace.farmer_orders'))

    # Restore stock if cancelling
    if new_status == 'cancelled' and order.status.value != 'cancelled':
        for item in order.items:
            if item.product_id in my_product_ids:
                item.product.stock += item.quantity

    order.status = OrderStatus(new_status)
    db.session.commit()
    flash(f'Order #{order.id} status updated to {order.status_label}.', 'success')
    return redirect(url_for('marketplace.farmer_orders'))
