import requests
import json
import time
from datetime import datetime, timedelta
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os

# --- CONFIGURATION ---
FILM_ID = os.getenv("FILM_ID")  # From your URL
START_DATE_STR = os.getenv("START_DATE_STR")
DAYS_TO_CHECK = int(os.getenv("DAYS_TO_CHECK", 10))    # How many days after the start date to monitor
CHECK_DELAY = int(os.getenv("CHECK_DELAY", 60))   # How often to run the full check (in seconds). 3600 = 1 hour.

SMTP_SERVER = "smtp.gmail.com"  # For Gmail
SMTP_PORT = 465                 # For SSL
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
PASSWORD = os.getenv("PASSWORD")  # NOT your regular login password
RECIEVER_EMAIL = os.getenv("RECIEVER_EMAIL")

# Headers to mimic your browser request
HEADERS = {
    'accept': 'application/json;charset=utf-8',
    'accept-language': 'en-GB,en;q=0.9,en-US;q=0.8,hu;q=0.7',
    'cache-control': 'no-cache',
    'referer': f'https://www.cinemacity.cz/films/odyssea/{FILM_ID}',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0',
    'sec-ch-ua': '"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
}

def get_api_url(date):
    return f"https://www.cinemacity.cz/cz/data-api-service/v1/quickbook/10101/cinema-events/in-group/prague/with-film/{FILM_ID}/at-date/{date}?attr=&lang=en_GB"

def check_for_screenings():
    # We use a set to keep track of event IDs we've already seen
    # In a real scenario, you might want to save this to a file
    seen_event_ids = set()
    
    start_date = datetime.strptime(START_DATE_STR, "%Y-%m-%d")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting check cycle...")

    while True:
        new_screenings_found = []
        
        for i in range(DAYS_TO_CHECK):
            target_date = (start_date + timedelta(days=i)).strftime("%Y-%m-%d")
            url = get_api_url(target_date)
            
            try:
                # We use a Session to handle cookies automatically
                response = requests.get(url, headers=HEADERS, timeout=15)
                
                if response.status_code == 200:
                    data = response.json()
                    # The events are typically located in body -> events
                    events = data.get('body', {}).get('events', [])
                    
                    for event in events:
                        e_id = event.get('id')
                        if e_id not in seen_event_ids:
                            # New screening detected!
                            info = {
                                "date": target_date,
                                "time": event.get('eventDateTime'),
                                "attribute": event.get('attributeIds'),
                                "id": e_id
                            }
                            new_screenings_found.append(info)
                            seen_event_ids.add(e_id)
                else:
                    print(f"Error {response.status_code} for date {target_date}")

            except Exception as e:
                print(f"Connection error on {target_date}: {e}")
            
            # Short sleep between requests to avoid rate limiting
            time.sleep(2)

        # Notification Logic
        if new_screenings_found:
            print("\n🔔 NEW SCREENINGS DETECTED!")
            for s in new_screenings_found:
                print(f"📅 Date: {s['date']} | Time: {s['time']} | ID: {s['id']}")
            print("-" * 30)
            notify(new_screenings_found)
        else:
            print(f"Checked {DAYS_TO_CHECK} days. No new screenings found.")

        print(f"Waiting {CHECK_DELAY}s for next check...\n")
        time.sleep(CHECK_DELAY)

def notify(screenings):
    # Send email notification or any other form of alert
    message = MIMEMultipart()
    message["From"] = SENDER_EMAIL
    message["To"] = RECIEVER_EMAIL
    message["Subject"] = "Cinema Screening Alert! 🎬"

    body = "A new screening has been detected. Check the script output for details."
    body += "\n\nDetails:\n"
    for s in screenings:
        body += f"- Date: {s['date']}, Time: {s['time']}, ID: {s['id']}\n"
    message.attach(MIMEText(body, "plain"))

    # Create a secure SSL context and send the email
    context = ssl.create_default_context()

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            server.login(SENDER_EMAIL, PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIEVER_EMAIL, message.as_string())
        print("Email sent successfully!")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    check_for_screenings()