from flask import Blueprint, render_template, redirect, url_for, flash, request
from app import db
from flask_login import current_user, login_user, logout_user, login_required
from app.models import User, UserRole
from app.email import send_password_reset_email
from urllib.parse import urlparse

auth_bp = Blueprint('auth', __name__)


def _role_redirect(user):
    """Return the appropriate dashboard URL for a given user role."""
    role = user.role
    if role == UserRole.FARMER:
        return url_for('dashboard.farmer')
    elif role == UserRole.ADMIN:
        return url_for('admin.index')
    else:
        # buyer, feed_supplier, veterinarian — generic landing for now
        return url_for('index')


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_role_redirect(current_user))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()
        remember = bool(request.form.get('remember'))

        if not username or not password:
            flash('Please enter both your username and password.', 'error')
            return render_template('auth/login.html', title='Sign In')

        user = User.query.filter_by(username=username).first()

        if user is None or not user.check_password(password):
            flash('Invalid username or password. Please try again.', 'error')
            return render_template('auth/login.html', title='Sign In')

        if not user.is_active:
            flash('Your account has been deactivated. Please contact support.', 'error')
            return render_template('auth/login.html', title='Sign In')

        login_user(user, remember=remember)

        # Honour ?next= param (safe redirect only)
        next_page = request.args.get('next')
        if next_page:
            parsed = urlparse(next_page)
            if parsed.netloc:  # external redirect — reject
                next_page = None

        return redirect(next_page or _role_redirect(user))

    return render_template('auth/login.html', title='Sign In')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been signed out successfully.', 'success')
    return redirect(url_for('auth.login'))


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(_role_redirect(current_user))

    # Roles available for self-registration (admin is not self-registered)
    ALLOWED_ROLES = {
        'farmer': UserRole.FARMER,
        'buyer': UserRole.BUYER,
        'feed_supplier': UserRole.FEED_SUPPLIER,
        'veterinarian': UserRole.VETERINARIAN,
    }

    if request.method == 'POST':
        first_name  = request.form.get('first_name', '').strip()
        last_name   = request.form.get('last_name', '').strip()
        username    = request.form.get('username', '').strip()
        email       = request.form.get('email', '').strip().lower()
        password    = request.form.get('password', '').strip()
        confirm_pw  = request.form.get('confirm_password', '').strip()
        role_str    = request.form.get('role', '').strip().lower()

        errors = []

        if not all([first_name, last_name, username, email, password, confirm_pw, role_str]):
            errors.append('All fields are required.')

        if password != confirm_pw:
            errors.append('Passwords do not match.')

        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')

        if role_str not in ALLOWED_ROLES:
            errors.append('Please select a valid role.')
        
        if User.query.filter_by(username=username).first():
            errors.append(f'Username is already taken.')
        
        if User.query.filter_by(email=email).first():
            errors.append(f'Email is already taken.')

        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template('auth/register.html', title='Create Account',
                                   form_data=request.form)

        # Create the user
        user = User(
            first_name=first_name,
            last_name=last_name,
            username=username,
            email=email,
            role=ALLOWED_ROLES[role_str],
            is_active=True,
        )
        
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        flash(f'Account created successfully! Please sign in.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('auth/register.html', title='Create Account', form_data={})

@auth_bp.route('/reset_password_request', methods=['GET', 'POST'])
def reset_password_request():
    if current_user.is_authenticated:
        return redirect(_role_redirect(current_user))
    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        user = User.query.filter_by(email=email).first()
        if user:
            send_password_reset_email(user)
        flash('Check your email for the instructions to reset your password', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password_request.html', title='Reset Password')

@auth_bp.route('/reset_password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    if current_user.is_authenticated:
        return redirect(_role_redirect(current_user))
    user = User.verify_reset_password_token(token)
    if not user:
        flash('The password reset link is invalid or has expired.', 'error')
        return redirect(url_for('index'))
    if request.method == 'POST':
        password = request.form.get('password', '').strip()
        confirm_pw = request.form.get('confirm_password', '').strip()
        
        errors = []
        if not password or not confirm_pw:
            errors.append('All fields are required.')
        if password != confirm_pw:
            errors.append('Passwords do not match.')
        if len(password) < 8:
            errors.append('Password must be at least 8 characters.')
            
        if errors:
            for err in errors:
                flash(err, 'error')
            return render_template('auth/reset_password.html', title='Set New Password', token=token)
            
        user.set_password(password)
        db.session.commit()
        flash('Your password has been reset.', 'success')
        return redirect(url_for('auth.login'))
    return render_template('auth/reset_password.html', title='Set New Password', token=token)
