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
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash


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
    mortality    = db.Column(db.Integer, default=0)                   # birds that died
    notes        = db.Column(db.Text)

    created_at   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Composite unique constraint: one record per farm per day
    __table_args__ = (
        db.UniqueConstraint('farm_id', 'record_date', name='uq_farm_record_date'),
    )

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
