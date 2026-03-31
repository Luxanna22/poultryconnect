from flask import Blueprint, render_template
from flask_login import login_required

analytics_bp = Blueprint('analytics', __name__)

@analytics_bp.route('/')
@login_required
def index():
    return render_template('analytics/analytics.html', title='Predictive Analytics')

@analytics_bp.route('/forecast')
@login_required
def forecast():
    return render_template('analytics/forecast.html', title='Production Forecast')
