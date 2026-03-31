from flask import Blueprint, render_template
from flask_login import login_required

production_bp = Blueprint('production', __name__)

@production_bp.route('/')
@login_required
def index():
    return render_template('production/production.html', title='Production Monitoring')

@production_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add_data():
    return render_template('production/add_data.html', title='Add Farm Data')
