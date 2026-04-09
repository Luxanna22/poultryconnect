from app import create_app, db
from app.models import User, Farm, ProductionRecord, Expense, Product, Order, OrderItem

app = create_app()

@app.shell_context_processor
def make_shell_context():
    return {
        'db': db,
        'User': User,
        'Farm': Farm,
        'ProductionRecord': ProductionRecord,
        'Expense': Expense,
        'Product': Product,
        'Order': Order,
        'OrderItem': OrderItem,
    }

if __name__ == '__main__':
    app.run(debug=True)

#test commentt