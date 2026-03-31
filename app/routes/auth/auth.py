from flask import Blueprint, render_template, redirect, url_for, flash, request
from app import db
from flask_login import current_user, login_user, logout_user, login_required
from app.models import User
from urllib.parse import urlparse

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    # Log in logic here
    return render_template('auth/login.html', title='Sign In')

@auth_bp.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('auth.login'))

@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard.index'))
    # Registration logic here
    return render_template('auth/register.html', title='Register')
