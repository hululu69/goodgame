# alert.py

import smtplib
from email.mime.text import MIMEText
import logging
import time

# Configure logging
logging.basicConfig(filename='alert_errors.log', level=logging.ERROR)

def alert_user(url, keywords, message):
    msg = MIMEText(message)
    msg['Subject'] = f'Dark Web Alert: Changes Detected for {url}'
    msg['From'] = 'your_email@gmail.com'  # Replace with your email
    msg['To'] = 'receiver_email@example.com'  # Replace with recipient email

    try:
        with smtplib.SMTP('smtp.gmail.com', 587) as s:
            s.starttls()
            s.login('your_email@gmail.com', 'your_app_password')  # Replace with your email and App Password
            s.send_message(msg)
        print("Alert sent.")
    except Exception as e:
        print(f"Failed to send alert: {e}")
        logging.error(f"Alert failed for {url}: {e}")  # Log the error
        # Fallback: Save alert to a file with UTF-8 encoding
        with open('failed_alerts.txt', 'a', encoding='utf-8') as f:
            f.write(f"Time: {time.ctime()}\nURL: {url}\nMessage: {message}\nError: {e}\n{'-'*50}\n")