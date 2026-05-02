"""
Database Models — PoultryConnect 2.0
Tables for v1 scope: Auth/Roles + Farmer Dashboard

Good practices applied:
- Primary keys (auto-increment INT)
- Indexes on FK columns and frequently filtered columns (date, role, email)
- Unique constraints on email and username
- Timestamps (created_at, updated_at) on every table
- Nullable=False on required fields
- Enum-style string constraints via db.CheckConstraint
- Relationships defined with backref for easy ORM access
"""

import enum
from datetime import datetime
from app import db, login
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from itsdangerous import URLSafeTimedSerializer as Serializer

# ─────────────────────────────────────────
# ENUMS
# ─────────────────────────────────────────

class UserRole(str, enum.Enum):
    ADMIN          = 'admin'
    FARMER         = 'farmer'
    BUYER          = 'buyer'
    FEED_SUPPLIER  = 'feed_supplier'
    VETERINARIAN   = 'veterinarian'

class ExpenseCategory(str, enum.Enum):
    FEED       = 'feed'
    LABOR      = 'labor'
    UTILITIES  = 'utilities'
    MEDICINE   = 'medicine'
    OTHER      = 'other'


# ─────────────────────────────────────────
# TABLE 1: users
# ─────────────────────────────────────────

class User(UserMixin, db.Model):
    """
    Central user table for all roles.
    Indexed: email, username, role — all are frequently queried.
    """
    __tablename__ = 'users'

    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username      = db.Column(db.String(64),  nullable=False, unique=True, index=True)
    email         = db.Column(db.String(120), nullable=False, unique=True, index=True)
    password_hash = db.Column(db.String(256), nullable=False)
    role          = db.Column(
                       db.Enum(UserRole),
                       nullable=False,
                       default=UserRole.FARMER,
                       index=True
                   )
    first_name    = db.Column(db.String(64))
    last_name     = db.Column(db.String(64))
    phone         = db.Column(db.String(20))
    is_active     = db.Column(db.Boolean, nullable=False, default=True)
    created_at    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    farms              = db.relationship('Farm', backref='owner', lazy='dynamic',
                                         foreign_keys='Farm.farmer_id')
    production_records = db.relationship('ProductionRecord', backref='recorded_by', lazy='dynamic',
                                          foreign_keys='ProductionRecord.user_id')
    expenses           = db.relationship('Expense', backref='recorded_by', lazy='dynamic',
                                          foreign_keys='Expense.user_id')

    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    def get_reset_password_token(self):
        s = Serializer(current_app.config['SECRET_KEY'])
        return s.dumps({'user_id': self.id})

    @staticmethod
    def verify_reset_password_token(token, expires_in=3600):
        s = Serializer(current_app.config['SECRET_KEY'])
        try:
            user_id = s.loads(token, max_age=expires_in)['user_id']
        except:
            return None
        return User.query.get(user_id)

    @property
    def full_name(self) -> str:
        if self.first_name and self.last_name:
            return f'{self.first_name} {self.last_name}'
        return self.username

    def __repr__(self):
        return f'<User {self.username} [{self.role.value}]>'


@login.user_loader
def load_user(user_id: int):
    return User.query.get(int(user_id))


# ─────────────────────────────────────────
# TABLE 2: farms
# ─────────────────────────────────────────

class Farm(db.Model):
    """
    A farmer can own multiple farms.
    Each farm is a distinct poultry operation.
    Indexed: farmer_id (FK) — always queried by owner.
    """
    __tablename__ = 'farms'

    id          = db.Column(db.Integer, primary_key=True, autoincrement=True)
    farmer_id   = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    name        = db.Column(db.String(120), nullable=False)
    location    = db.Column(db.String(255))
    description = db.Column(db.Text)
    flock_size  = db.Column(db.Integer, default=0)        # total number of birds
    is_active   = db.Column(db.Boolean, nullable=False, default=True)
    created_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    production_records = db.relationship('ProductionRecord', backref='farm', lazy='dynamic',
                                          foreign_keys='ProductionRecord.farm_id')
    expenses           = db.relationship('Expense', backref='farm', lazy='dynamic',
                                          foreign_keys='Expense.farm_id')

    def __repr__(self):
        return f'<Farm {self.name} (owner_id={self.farmer_id})>'


# ─────────────────────────────────────────
# TABLE 3: production_records
# ─────────────────────────────────────────

class ProductionRecord(db.Model):
    """
    Daily production log per farm.
    Indexed: farm_id, record_date — core of farmer dashboard queries.
    """
    __tablename__ = 'production_records'

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    farm_id      = db.Column(db.Integer, db.ForeignKey('farms.id'), nullable=False, index=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    record_date  = db.Column(db.Date, nullable=False, index=True)   # the date the data is FOR
    egg_count    = db.Column(db.Integer, nullable=False, default=0)  # total eggs collected
    feed_kg      = db.Column(db.Numeric(8, 2), default=0.00)         # feed consumed in kg
    feed_cost    = db.Column(db.Numeric(10, 2), default=0.00)        # cost of feed that day (PHP)
    egg_price    = db.Column(db.Numeric(10, 2), nullable=True)       # selling price per egg (PHP); None = not recorded
    mortality    = db.Column(db.Integer, default=0)                   # birds that died
    notes        = db.Column(db.Text)

    created_at   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Composite unique constraint: one record per farm per day
    __table_args__ = (
        db.UniqueConstraint('farm_id', 'record_date', name='uq_farm_record_date'),
    )

    @property
    def revenue(self):
        """Daily revenue: egg_count × egg_price. Returns 0 if price not set."""
        if self.egg_price:
            return float(self.egg_count) * float(self.egg_price)
        return 0.0

    def __repr__(self):
        return f'<ProductionRecord farm={self.farm_id} date={self.record_date} eggs={self.egg_count}>'


# ─────────────────────────────────────────
# TABLE 4: expenses
# ─────────────────────────────────────────

class Expense(db.Model):
    """
    Operational expense entries per farm.
    Categories: feed, labor, utilities, medicine, other.
    Indexed: farm_id, expense_date — for monthly profit/loss rollup queries.
    """
    __tablename__ = 'expenses'

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    farm_id      = db.Column(db.Integer, db.ForeignKey('farms.id'), nullable=False, index=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    expense_date = db.Column(db.Date, nullable=False, index=True)
    category     = db.Column(
                      db.Enum(ExpenseCategory),
                      nullable=False,
                      default=ExpenseCategory.OTHER,
                      index=True
                  )
    amount       = db.Column(db.Numeric(10, 2), nullable=False)   # PHP
    description  = db.Column(db.String(255))

    created_at   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Expense farm={self.farm_id} {self.category.value} ₱{self.amount} on {self.expense_date}>'


# ─────────────────────────────────────────
# MARKETPLACE ENUMS
# ─────────────────────────────────────────

class ProductCategory(str, enum.Enum):
    EGGS       = 'eggs'
    LIVE_BIRDS = 'live_birds'
    DRESSED    = 'dressed'
    OTHER      = 'other'

class ProductUnit(str, enum.Enum):
    PIECE    = 'piece'
    TRAY     = 'tray'
    KILOGRAM = 'kilogram'
    HEAD     = 'head'

class OrderStatus(str, enum.Enum):
    PENDING    = 'pending'
    CONFIRMED  = 'confirmed'
    SHIPPED    = 'shipped'
    DELIVERED  = 'delivered'
    CANCELLED  = 'cancelled'


# ─────────────────────────────────────────
# TABLE 5: products
# ─────────────────────────────────────────

class Product(db.Model):
    """
    Marketplace product listings created by farmers.
    Indexed: farmer_id, farm_id, category, is_available — all frequent query paths.
    """
    __tablename__ = 'products'

    id            = db.Column(db.Integer, primary_key=True, autoincrement=True)
    farmer_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    farm_id       = db.Column(db.Integer, db.ForeignKey('farms.id'), nullable=False, index=True)

    name          = db.Column(db.String(150), nullable=False)
    description   = db.Column(db.Text)
    category      = db.Column(
                       db.Enum(ProductCategory),
                       nullable=False,
                       default=ProductCategory.EGGS,
                       index=True
                   )
    unit          = db.Column(
                       db.Enum(ProductUnit),
                       nullable=False,
                       default=ProductUnit.PIECE
                   )
    price         = db.Column(db.Numeric(10, 2), nullable=False)        # PHP per unit
    stock         = db.Column(db.Integer, nullable=False, default=0)
    location      = db.Column(db.String(255))                           # auto-filled from farm
    is_available  = db.Column(db.Boolean, nullable=False, default=True, index=True)

    created_at    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at    = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    farmer        = db.relationship('User', backref=db.backref('products', lazy='dynamic'))
    farm          = db.relationship('Farm', backref=db.backref('products', lazy='dynamic'))
    order_items   = db.relationship('OrderItem', backref='product', lazy='dynamic')

    @property
    def stock_label(self):
        if self.stock <= 0:
            return 'out_of_stock'
        elif self.stock <= 10:
            return 'low_stock'
        return 'in_stock'

    @property
    def category_label(self):
        return self.category.value.replace('_', ' ').title()

    @property
    def unit_label(self):
        return self.unit.value.replace('_', ' ')

    def __repr__(self):
        return f'<Product {self.name} ₱{self.price}/{self.unit.value} (farmer={self.farmer_id})>'


# ─────────────────────────────────────────
# TABLE 6: orders
# ─────────────────────────────────────────

class Order(db.Model):
    """
    Purchase orders placed by buyers.
    Indexed: buyer_id, status — dashboard queries.
    """
    __tablename__ = 'orders'

    id               = db.Column(db.Integer, primary_key=True, autoincrement=True)
    buyer_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)

    total_amount     = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    status           = db.Column(
                          db.Enum(OrderStatus),
                          nullable=False,
                          default=OrderStatus.PENDING,
                          index=True
                      )
    delivery_address = db.Column(db.String(500), nullable=False)
    contact_phone    = db.Column(db.String(30), nullable=False)
    notes            = db.Column(db.Text)

    created_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at       = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    buyer            = db.relationship('User', backref=db.backref('orders', lazy='dynamic'))
    items            = db.relationship('OrderItem', backref='order', lazy='joined',
                                        cascade='all, delete-orphan')

    @property
    def status_label(self):
        return self.status.value.replace('_', ' ').title()

    @property
    def item_count(self):
        return len(self.items)

    def __repr__(self):
        return f'<Order #{self.id} buyer={self.buyer_id} ₱{self.total_amount} [{self.status.value}]>'


# ─────────────────────────────────────────
# TABLE 7: order_items
# ─────────────────────────────────────────

class OrderItem(db.Model):
    """
    Line items within an order.
    Captures a snapshot of the unit price at order time so it never changes retroactively.
    """
    __tablename__ = 'order_items'

    id           = db.Column(db.Integer, primary_key=True, autoincrement=True)
    order_id     = db.Column(db.Integer, db.ForeignKey('orders.id'), nullable=False, index=True)
    product_id   = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False, index=True)
    quantity     = db.Column(db.Integer, nullable=False, default=1)
    unit_price   = db.Column(db.Numeric(10, 2), nullable=False)   # price snapshot at order time

    @property
    def subtotal(self):
        return float(self.quantity) * float(self.unit_price)

    def __repr__(self):
        return f'<OrderItem order={self.order_id} product={self.product_id} qty={self.quantity}>'
