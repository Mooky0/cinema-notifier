import requests
import json
import time
from datetime import datetime, timedelta
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from html import escape
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
DAYS_TO_CHECK = int(os.getenv("DAYS_TO_CHECK", 50))    # How many days after the start date to monitor
CHECK_DELAY = int(os.getenv("CHECK_DELAY", 60))   # How often to run the full check (in seconds). 3600 = 1 hour.

SMTP_SERVER = "smtp.gmail.com"  # For Gmail
SMTP_PORT = 465                 # For SSL
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
PASSWORD = os.getenv("PASSWORD")  # NOT your regular login password
RECIEVER_EMAIL = os.getenv("RECIEVER_EMAIL")
DEBUG_MODE = os.getenv("DEBUG_MODE", "False").lower() == "true"
KVSTORE_URL = os.getenv("KVSTORE_URL", "localhost:8081")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

FILM_PAGE_URL = f'https://www.cinemacity.cz/films/odyssea/{FILM_ID}'

# Headers to mimic your browser request
HEADERS = {
    'accept': 'application/json;charset=utf-8',
    'accept-language': 'en-GB,en;q=0.9,en-US;q=0.8,hu;q=0.7',
    'cache-control': 'no-cache',
    'referer': FILM_PAGE_URL,
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
                                    id=e_id,
                                    auditorium=event.get('auditorium'),
                                    sold_out=event.get('soldOut'),
                                    availability=event.get('availabilityRatio'),
                                    languages=event.get('languages'),
                                    attributes=attributes,
                                    booking_link=FILM_PAGE_URL,
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
            send_telegram_notification(new_screenings_found)
        else:
            logger.info(f"Checked {DAYS_TO_CHECK} days. No new screenings found.")

        logger.info(f"Waiting {CHECK_DELAY}s for next check...\n")
        time.sleep(CHECK_DELAY)

WEEKEND_WEEKDAYS = {4, 5, 6}  # Friday, Saturday, Sunday
LOW_AVAILABILITY_THRESHOLD = 20  # percent of seats left

def format_screening_time(screening):
    try:
        dt = datetime.strptime(screening.time, "%Y-%m-%dT%H:%M:%S")
        return dt.strftime("%A, %d %B %Y"), dt.strftime("%H:%M")
    except (TypeError, ValueError):
        return screening.date, screening.time

def parse_screening_datetime(screening):
    try:
        return datetime.strptime(screening.time, "%Y-%m-%dT%H:%M:%S")
    except (TypeError, ValueError):
        return None

def is_weekend(screening):
    dt = parse_screening_datetime(screening)
    return dt is not None and dt.weekday() in WEEKEND_WEEKDAYS

def seats_available_pct(screening):
    if screening.sold_out or screening.availability is None:
        return None
    try:
        return round((1 - float(screening.availability)) * 100)
    except (TypeError, ValueError):
        return None

def is_low_availability(screening):
    if screening.sold_out:
        return False
    pct = seats_available_pct(screening)
    return pct is not None and pct <= LOW_AVAILABILITY_THRESHOLD

def format_languages(languages):
    if not languages:
        return None
    parts = []
    if languages.get("original"):
        parts.append("audio: " + "/".join(languages["original"]).upper())
    if languages.get("dubbed"):
        parts.append("dubbed: " + "/".join(languages["dubbed"]).upper())
    if languages.get("subtitles"):
        parts.append("subtitles: " + "/".join(languages["subtitles"]).upper())
    return ", ".join(parts) if parts else None

def format_availability(screening):
    if screening.sold_out:
        return "Sold out"
    pct = seats_available_pct(screening)
    return f"{pct}% seats available" if pct is not None else None

def build_text_body(screenings):
    lines = ["New 70mm screening(s) detected!", ""]
    for s in screenings:
        day, time_str = format_screening_time(s)
        tags = []
        if is_weekend(s):
            tags.append("WEEKEND")
        if is_low_availability(s):
            tags.append("LOW AVAILABILITY")
        tag_suffix = f" [{', '.join(tags)}]" if tags else ""
        lines.append(f"- {day} at {time_str}{tag_suffix}")
        if s.auditorium:
            lines.append(f"  Auditorium: {s.auditorium}")
        langs = format_languages(s.languages)
        if langs:
            lines.append(f"  {langs}")
        availability = format_availability(s)
        if availability:
            lines.append(f"  {availability}")
        if s.attributes:
            lines.append(f"  Tags: {', '.join(s.attributes)}")
        if s.booking_link:
            lines.append(f"  Book: {s.booking_link}")
        lines.append(f"  Event ID: {s.id}")
        lines.append("")
    return "\n".join(lines)

def build_html_body(screenings):
    cards = []
    for s in screenings:
        day, time_str = format_screening_time(s)
        weekend = is_weekend(s)
        pct = seats_available_pct(s)
        low_avail = is_low_availability(s)

        if s.sold_out:
            availability_color = "#6b7280"
        elif low_avail:
            availability_color = "#dc2626"
        elif pct is not None and pct <= 40:
            availability_color = "#d97706"
        else:
            availability_color = "#16a34a"

        rows = []
        if s.auditorium:
            rows.append(("Auditorium", escape(s.auditorium), "#111111"))
        langs = format_languages(s.languages)
        if langs:
            rows.append(("Language", escape(langs), "#111111"))
        availability = format_availability(s)
        if availability:
            avail_text = escape(availability)
            if low_avail:
                avail_text = f"🔥 {avail_text} — act fast!"
            rows.append(("Availability", avail_text, availability_color))
        if s.attributes:
            rows.append(("Tags", escape(", ".join(s.attributes)), "#111111"))
        rows.append(("Event ID", escape(str(s.id)), "#111111"))

        rows_html = "".join(
            f'''<tr>
                <td style="padding:4px 0;color:#666666;font-size:14px;width:110px;vertical-align:top;">{label}</td>
                <td style="padding:4px 0;color:{color};font-size:14px;font-weight:{'bold' if color != '#111111' else 'normal'};">{value}</td>
            </tr>'''
            for label, value, color in rows
        )

        badges = ""
        if weekend:
            badges += ('<span style="display:inline-block;background-color:#ede9fe;color:#6d28d9;'
                       'font-size:12px;font-weight:bold;padding:3px 8px;border-radius:12px;'
                       'margin-right:6px;">🎉 WEEKEND</span>')
        if low_avail:
            badges += ('<span style="display:inline-block;background-color:#fee2e2;color:#dc2626;'
                       'font-size:12px;font-weight:bold;padding:3px 8px;border-radius:12px;">'
                       '🔥 ALMOST FULL</span>')
        badges_html = f'<div style="margin-bottom:6px;">{badges}</div>' if badges else ""

        card_border = "#dc2626" if low_avail else ("#7c3aed" if weekend else "#e50914")

        book_button = ""
        if s.booking_link:
            book_button = f'''
            <a href="{escape(s.booking_link)}"
               style="display:block;text-align:center;background-color:#e50914;color:#ffffff;
                      text-decoration:none;font-size:16px;font-weight:bold;padding:14px 0;
                      border-radius:8px;margin-top:12px;">
                View & book
            </a>'''

        cards.append(f'''
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0"
               style="background-color:#ffffff;border-radius:12px;margin-bottom:16px;
                      border-left:4px solid {card_border};
                      box-shadow:0 1px 3px rgba(0,0,0,0.1);">
          <tr>
            <td style="padding:16px;">
              {badges_html}
              <div style="font-size:18px;font-weight:bold;color:#111111;">{escape(day)}</div>
              <div style="font-size:22px;font-weight:bold;color:#e50914;margin-bottom:8px;">{escape(time_str)}</div>
              <table role="presentation" cellpadding="0" cellspacing="0" width="100%">
                {rows_html}
              </table>
              {book_button}
            </td>
          </tr>
        </table>''')

    return f'''\
<!DOCTYPE html>
<html>
<head>
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta charset="UTF-8">
</head>
<body style="margin:0;padding:0;background-color:#f2f2f2;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f2f2f2;">
    <tr>
      <td align="center" style="padding:16px;">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:480px;">
          <tr>
            <td style="padding:8px 4px 16px 4px;">
              <div style="font-size:20px;font-weight:bold;color:#111111;">🎬 New 70mm screening{'s' if len(screenings) != 1 else ''} found!</div>
              <div style="font-size:14px;color:#666666;margin-top:4px;">{len(screenings)} new screening{'s' if len(screenings) != 1 else ''} just went up.</div>
            </td>
          </tr>
          <tr>
            <td>
              {''.join(cards)}
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>'''

def notify(screenings):
    # Send email notification or any other form of alert
    message = MIMEMultipart("alternative")
    message["From"] = SENDER_EMAIL
    message["To"] = RECIEVER_EMAIL
    count = len(screenings)
    message["Subject"] = f"🎬 {count} New 70mm Screening{'s' if count != 1 else ''} Detected!"

    message.attach(MIMEText(build_text_body(screenings), "plain"))
    message.attach(MIMEText(build_html_body(screenings), "html"))

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

def build_telegram_message(screenings):
    count = len(screenings)
    return (f"🎬 {count} new 70mm screening{'s' if count != 1 else ''} found! "
            f"Check your email for details.")

def send_telegram_notification(screenings):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.info("Telegram not configured (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID missing), skipping.")
        return

    text = build_telegram_message(screenings)

    if DEBUG_MODE:
        logger.info("DEBUG MODE: Telegram message not sent. Here is the content:")
        logger.info(text)
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=15)
        if response.status_code == 200:
            logger.info("Telegram notification sent successfully!")
        else:
            logger.info(f"Telegram error {response.status_code}: {response.text}")
    except Exception as e:
        logger.info(f"Telegram connection error: {e}")

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