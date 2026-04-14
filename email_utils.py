import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv

load_dotenv()
load_dotenv(".env.example")


def _first_env(*names, default=""):
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


SMTP_HOST = _first_env("SMTP_HOST", "SMTP_SERVER", default="smtp.gmail.com")
SMTP_PORT = int(_first_env("SMTP_PORT", default="587"))
SMTP_USER = _first_env("SMTP_USER", default="")
MAIL_PASSWORD = _first_env("MAIL_PASSWORD", "SMTP_PASSWORD", default="")
SMTP_FROM = _first_env("SMTP_FROM", default=SMTP_USER or "AI Interview Room")


def _build_interview_message(to_email, candidate_name, interview_time, interview_link):
    compatibility_link = (
        interview_link.replace("/interview?", "/system-check?")
        if "/interview?" in interview_link
        else interview_link
    )
    start_link = interview_link if "mode=" in interview_link else f"{interview_link}&mode=start"
    msg = MIMEMultipart()
    msg["From"] = SMTP_FROM if "@" in SMTP_FROM else SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = f"AI Interview Invitation - {candidate_name}"

    html = f"""
    <html>
    <head>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
            .container {{ padding: 20px; border: 1px solid #ddd; border-radius: 8px; max-width: 600px; margin: auto; }}
            .header {{ background-color: #4A90E2; color: white; padding: 10px; text-align: center; border-radius: 8px 8px 0 0; }}
            .content {{ padding: 20px; }}
            .button {{ display: inline-block; padding: 10px 20px; color: white; background-color: #4A90E2; text-decoration: none; border-radius: 5px; margin-top: 15px; }}
            .button-secondary {{ display: inline-block; padding: 10px 20px; color: white; background-color: #10b981; text-decoration: none; border-radius: 5px; margin-top: 10px; }}
            .checklist {{ margin-top: 14px; padding-left: 18px; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header"><h1>Interview Invitation</h1></div>
            <div class="content">
                <p>Hello {candidate_name},</p>
                <p>You have been invited for an AI Interview.</p>
                <p><strong>Time:</strong> {interview_time}</p>
                <p>Please use the link below to join the interview at the scheduled time.</p>
                <p><strong>Before joining, please make sure:</strong></p>
                <ul class="checklist">
                    <li>Your camera is working and permission is allowed</li>
                    <li>Your microphone is enabled and unmuted</li>
                    <li>You use a supported browser like Chrome or Edge</li>
                    <li>You keep a stable internet connection during the interview</li>
                </ul>
                <p>When you open the interview, you will first see a System Compatibility Check page for camera, microphone, speaker, and internet support.</p>
                <p>After that, you can wait for the scheduled time and start the interview when it opens.</p>
                <p>Note that you won't be able to join before or significantly after the slot.</p>
                <a href="{compatibility_link}" class="button">System Compatibility Check</a>
                <br>
                <a href="{start_link}" class="button-secondary">Start Interview</a>
                <p>Good luck!</p>
            </div>
        </div>
    </body>
    </html>
    """
    msg.attach(MIMEText(html, "html"))
    return msg


def _send_messages(messages):
    if not SMTP_USER or not MAIL_PASSWORD:
        print("[INFO] SMTP credentials not set. Email delivery skipped.")
        for message in messages:
            print(f"Link: {message['To']}")
        return None

    try:
        if SMTP_PORT == 465:
            server = smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT)
        else:
            server = smtplib.SMTP(SMTP_HOST, SMTP_PORT)
        with server:
            if SMTP_PORT != 465:
                server.starttls()
            server.login(SMTP_USER, MAIL_PASSWORD)
            for message in messages:
                server.send_message(message)
        return True
    except Exception as e:
        print(f"[ERROR] Failed to send email: {e}")
        return False


def send_interview_email(to_email, candidate_name, interview_time, interview_link):
    message = _build_interview_message(to_email, candidate_name, interview_time, interview_link)
    return _send_messages([message])


def send_bulk_interview_emails(recipients):
    messages = [
        _build_interview_message(
            recipient["to_email"],
            recipient["candidate_name"],
            recipient["interview_time"],
            recipient["interview_link"],
        )
        for recipient in recipients
    ]
    return _send_messages(messages)
