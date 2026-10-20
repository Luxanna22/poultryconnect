from threading import Thread
from flask import current_app, render_template
from flask_mail import Message
from app import mail

def send_async_email(app, msg):
    with app.app_context():
        # Fallback for development if no mail server is configured
        if not app.config.get('MAIL_USERNAME'):
            print("================== EMAIL MOCK ==================", flush=True)
            print(f"To: {msg.recipients}", flush=True)
            print(f"Subject: {msg.subject}", flush=True)
            print(f"Body:\n{msg.body}", flush=True)
            print("================================================", flush=True)
            return

        try:
            mail.send(msg)
        except Exception as e:
            print(f"Failed to send email: {e}", flush=True)

def send_email(subject, sender, recipients, text_body, html_body=None):
    msg = Message(subject, sender=sender, recipients=recipients)
    msg.body = text_body
    if html_body:
        msg.html = html_body
    
    # We use current_app._get_current_object() so the thread gets the actual app instance
    Thread(target=send_async_email, args=(current_app._get_current_object(), msg)).start()

def send_password_reset_email(user):
    token = user.get_reset_password_token()
    send_email('[PoultryConnect] Reset Your Password',
               sender=current_app.config['ADMINS'][0],
               recipients=[user.email],
               text_body=render_template('email/reset_password.txt',
                                         user=user, token=token))
