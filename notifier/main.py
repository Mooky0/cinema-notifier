import requests
import json
import time
from datetime import datetime, timedelta
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import logging
import sys
from dotenv import load_dotenv
from kvstore import Movie, MovieStore

if os.path.exists('.env'):
    from dotenv import load_dotenv
    load_dotenv()

# --- CONFIGURATION ---
FILM_ID = os.getenv("FILM_ID")  # From your URL
CINEMA_ID = os.getenv("CINEMA_ID", "1052")  # Default cinema ID if not set
START_DATE_STR = os.getenv("START_DATE_STR")
DAYS_TO_CHECK = int(os.getenv("DAYS_TO_CHECK", 10))    # How many days after the start date to monitor
CHECK_DELAY = int(os.getenv("CHECK_DELAY", 60))   # How often to run the full check (in seconds). 3600 = 1 hour.

SMTP_SERVER = "smtp.gmail.com"  # For Gmail
SMTP_PORT = 465                 # For SSL
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
PASSWORD = os.getenv("PASSWORD")  # NOT your regular login password
RECIEVER_EMAIL = os.getenv("RECIEVER_EMAIL")
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"
KVSTORE_URL = os.getenv("KVSTORE_URL", "localhost:8081")

# Headers to mimic your browser request
HEADERS = {
    'accept': 'application/json;charset=utf-8',
    'accept-language': 'en-GB,en;q=0.9,en-US;q=0.8,hu;q=0.7',
    'cache-control': 'no-cache',
    'referer': f'https://www.cinemacity.cz/films/odyssea/{FILM_ID}',
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0',
    'sec-ch-ua': '"Microsoft Edge";v="143", "Chromium";v="143", "Not A(Brand";v="24"',
}

logger = logging.getLogger(__name__)
db: MovieStore = None  # Will be initialized later

def get_api_url(date):
    return f"https://www.cinemacity.cz/cz/data-api-service/v1/quickbook/10101/cinema-events/in-group/prague/with-film/{FILM_ID}/at-date/{date}?attr=&lang=en_GB"

def check_for_screenings():
    # We use a set to keep track of event IDs we've already seen
    # In a real scenario, you might want to save this to a file
    #seen_event_ids = set()

    global db

    start_date = datetime.strptime(START_DATE_STR, "%Y-%m-%d")

    logger.info(f"[{datetime.now().strftime('%H:%M:%S')}] Starting check cycle...")

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
                        attributes = event.get('attributeIds', {})
                        cinema_id = event.get('cinemaId')
                        if not db.exists(e_id):
                            if cinema_id == CINEMA_ID and "70-mm" in attributes:
                                # New screening detected!
                                info = Movie(
                                    date=target_date,
                                    time=event.get('eventDateTime'),
                                    id=e_id
                                )
                                new_screenings_found.append(info)
                                db.put_movie(e_id, info)
                else:
                    logger.info(f"Error {response.status_code} for date {target_date}")

            except Exception as e:
                logger.info(f"Connection error on {target_date}: {e}")
            
            # Short sleep between requests to avoid rate limiting
            time.sleep(2)

        # Notification Logic
        if new_screenings_found:
            logger.info("🔔 NEW SCREENINGS DETECTED!")
            for s in new_screenings_found:
                logger.info(f"📅 Date: {s.date} | Time: {s.time} | ID: {s.id}")
            logger.info("-" * 30)
            notify(new_screenings_found)
        else:
            logger.info(f"Checked {DAYS_TO_CHECK} days. No new screenings found.")

        logger.info(f"Waiting {CHECK_DELAY}s for next check...\n")
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
        body += f"- Date: {s.date}, Time: {s.time}, ID: {s.id}\n"
    message.attach(MIMEText(body, "plain"))

    # Create a secure SSL context and send the email
    context = ssl.create_default_context()

    try:
        with smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT, context=context) as server:
            if DEBUG_MODE:
                logger.info("DEBUG MODE: Email not sent. Here is the email content:")
                logger.info(message.as_string())
                return
            server.login(SENDER_EMAIL, PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIEVER_EMAIL, message.as_string())
        logger.info("Email sent successfully!")
    except Exception as e:
        logger.info(f"Error: {e}")

def main():
    global db
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('[%(asctime)s] - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    root.addHandler(handler)

    db = MovieStore(KVSTORE_URL)

    check_for_screenings()

if __name__ == "__main__":
    main()