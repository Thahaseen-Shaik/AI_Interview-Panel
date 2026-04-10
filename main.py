import json
import os
import re
from datetime import datetime, timedelta
from functools import wraps

import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

from database import (
    complete_interview,
    create_admin,
    delete_interview,
    get_admin_by_username,
    get_all_interviews,
    get_compatibility_checks,
    get_interview_by_token,
    get_interview_messages,
    get_proctoring_events,
    init_db,
    save_interview_message,
    save_compatibility_check,
    save_proctoring_event,
    schedule_interview,
    update_interview_started,
)
from email_utils import send_interview_email


load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
init_db()

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434/api/generate")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return redirect(url_for("home"))
        return view(*args, **kwargs)

    return wrapped


def _render_home(message=None, error=None, active_form=None):
    return render_template(
        "home.html",
        message=message,
        error=error,
        username=session.get("admin_username"),
        active_form=active_form,
    )


def _normalize_transcript(messages):
    transcript_lines = []
    for item in messages:
        speaker = item.get("speaker", "candidate")
        label = "Candidate" if speaker in ("candidate", "user") else "AI"
        content = item.get("content", "").strip()
        if content:
            transcript_lines.append(f"{label}: {content}")
    return "\n".join(transcript_lines)


def _messages_from_rows(rows):
    return [
        {
            "speaker": row["speaker"],
            "content": row["content"],
            "created_at": row["created_at"],
        }
        for row in rows
    ]


def _rows_to_dicts(rows):
    return [
        {key: row[key] for key in row.keys()}
        for row in rows
    ]


def _calculate_fallback_score(messages, duration_minutes, completed=True):
    candidate_messages = [
        item for item in messages if item.get("speaker") in ("candidate", "user")
    ]
    ai_messages = [item for item in messages if item.get("speaker") == "ai"]
    candidate_words = sum(
        len(re.findall(r"\w+", item.get("content", ""))) for item in candidate_messages
    )
    candidate_turns = len(candidate_messages)

    score = 20
    score += min(25, int(round((duration_minutes or 0) * 2)))
    score += min(25, candidate_turns * 5)
    score += min(20, candidate_words // 8)
    score += min(10, len(ai_messages) * 2)
    if completed:
        score += 10

    score = max(0, min(100, int(score)))
    if score >= 85:
        summary = "Excellent interview performance with strong engagement and depth."
    elif score >= 70:
        summary = "Good interview performance with solid communication and preparation."
    elif score >= 50:
        summary = "Average interview performance with room to improve depth and clarity."
    else:
        summary = "Interview showed limited engagement or incomplete responses."

    return {
        "score": score,
        "summary": summary,
        "strengths": [
            "Completed the interview flow" if completed else "Interview still in progress",
            f"Answered {candidate_turns} question(s)",
        ],
        "concerns": [
            "Add more technical depth" if candidate_words < 120 else "Could still sharpen examples",
        ],
    }


def _score_with_ollama(messages, duration_minutes, completed=True):
    transcript_text = _normalize_transcript(messages)
    if not transcript_text.strip():
        return None

    prompt = f"""
You are an interview evaluator.
Return ONLY valid JSON with these keys:
- score: integer from 0 to 100
- summary: short single paragraph
- strengths: array of short bullet phrases
- concerns: array of short bullet phrases

Scoring guidance:
- Judge clarity, relevance, confidence, and depth of answers.
- If the interview was not completed, reduce the score slightly.
- Keep the output concise and valid JSON only.

Duration minutes: {duration_minutes:.1f}
Completed: {str(completed).lower()}

Transcript:
{transcript_text}
"""

    response = requests.post(
        OLLAMA_URL,
        json={
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False,
        },
        timeout=25,
    )
    response.raise_for_status()
    payload = response.json()
    text = (payload.get("response") or "").strip()
    text = re.sub(r"^```json\s*", "", text)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    parsed = json.loads(text)
    if "score" not in parsed:
        return None
    parsed["score"] = max(0, min(100, int(parsed["score"])))
    parsed.setdefault("summary", "Interview evaluated successfully.")
    parsed.setdefault("strengths", [])
    parsed.setdefault("concerns", [])
    return parsed


def score_interview(messages, duration_minutes, completed=True):
    try:
        scored = _score_with_ollama(messages, duration_minutes, completed=completed)
        if scored:
            return scored
    except Exception:
        pass
    return _calculate_fallback_score(messages, duration_minutes, completed=completed)


@app.route("/")
def home():
    if session.get("admin_id"):
        return redirect(url_for("dashboard"))
    return _render_home()


@app.route("/register", methods=["POST"])
def register():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    confirm_password = request.form.get("confirm_password") or ""

    if not username or not password:
        return _render_home(error="Username and password are required.", active_form="login")
    if password != confirm_password:
        return _render_home(error="Passwords do not match.", active_form="register")
    if get_admin_by_username(username):
        return _render_home(error="That username already exists.", active_form="register")

    admin_id = create_admin(username, generate_password_hash(password))
    session["admin_id"] = admin_id
    session["admin_username"] = username
    return redirect(url_for("dashboard"))


@app.route("/login", methods=["POST"])
def login():
    username = (request.form.get("username") or "").strip()
    password = request.form.get("password") or ""
    admin = get_admin_by_username(username)

    if not admin or not check_password_hash(admin["password_hash"], password):
        return _render_home(error="Invalid username or password.", active_form="login")

    session["admin_id"] = admin["id"]
    session["admin_username"] = admin["username"]
    return redirect(url_for("dashboard"))


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))


@app.route("/dashboard")
@login_required
def dashboard():
    interviews = get_all_interviews()
    total = len(interviews)
    completed = sum(1 for row in interviews if row["status"] == "completed")
    scheduled = sum(1 for row in interviews if row["status"] == "scheduled")
    in_progress = sum(1 for row in interviews if row["status"] == "in_progress")
    scored = [row["score"] for row in interviews if row["score"] is not None]
    average_score = round(sum(scored) / len(scored), 1) if scored else None

    return render_template(
        "dashboard.html",
        admin_username=session.get("admin_username"),
        interviews=interviews,
        total_interviews=total,
        completed_interviews=completed,
        scheduled_interviews=scheduled,
        in_progress_interviews=in_progress,
        average_score=average_score,
    )


@app.route("/api/ping")
def ping():
    return jsonify({"ok": True, "server_time": datetime.utcnow().isoformat(timespec="seconds")})


@app.route("/schedule", methods=["POST"])
@login_required
def schedule():
    name = (request.form.get("name") or "").strip()
    email = (request.form.get("email") or "").strip()
    interview_time = (request.form.get("time") or "").strip()

    if not name or not email or not interview_time:
        return jsonify({"message": "All fields are required."}), 400

    token = schedule_interview(name, email, interview_time)
    base_url = request.url_root.rstrip("/") if request.url_root else BASE_URL.rstrip("/")
    link = f"{base_url}/interview?token={token}"

    email_result = send_interview_email(email, name, interview_time, link)
    if email_result is True:
        message = "Interview scheduled and email sent."
        email_status = "sent"
    elif email_result is None:
        message = "Interview scheduled."
        email_status = "skipped"
    else:
        message = "Interview scheduled, but email delivery failed."
        email_status = "failed"

    return jsonify(
        {
            "message": message,
            "link": link,
            "token": token,
            "email_status": email_status,
        }
    )


@app.route("/dashboard/interviews/<token>")
@login_required
def interview_detail(token):
    interview = get_interview_by_token(token)
    if not interview:
        return "Interview not found", 404

    messages = _messages_from_rows(get_interview_messages(token))
    compatibility_checks = _rows_to_dicts(get_compatibility_checks(token))
    proctoring_events = _rows_to_dicts(get_proctoring_events(token))
    transcript = interview["transcript"]
    transcript_text = ""
    evaluation = {}
    if transcript:
        try:
            parsed_transcript = json.loads(transcript)
            if isinstance(parsed_transcript, list):
                transcript_text = _normalize_transcript(parsed_transcript)
            else:
                transcript_text = str(parsed_transcript)
        except Exception:
            transcript_text = transcript
    if interview["feedback"]:
        try:
            evaluation = json.loads(interview["feedback"])
        except Exception:
            evaluation = {"summary": interview["feedback"]}
    if not transcript_text:
        transcript_text = _normalize_transcript(messages)

    return render_template(
        "interview_detail.html",
        admin_username=session.get("admin_username"),
        interview=interview,
        messages=messages,
        compatibility_checks=compatibility_checks,
        proctoring_events=proctoring_events,
        transcript_text=transcript_text,
        evaluation=evaluation,
    )


@app.route("/dashboard/interviews/<token>/delete", methods=["POST"])
@login_required
def interview_delete(token):
    interview = get_interview_by_token(token)
    if not interview:
        return jsonify({"error": "Interview not found"}), 404

    delete_interview(token)
    return jsonify({"message": "Interview deleted"})


@app.route("/api/interviews/<token>/compatibility", methods=["POST"])
def interview_compatibility(token):
    interview = get_interview_by_token(token)
    if not interview:
        return jsonify({"error": "Interview not found"}), 404

    data = request.get_json(silent=True) or {}
    check_name = (data.get("check_name") or "").strip()
    status = (data.get("status") or "").strip()
    details = (data.get("details") or "").strip()

    if not check_name or not status:
        return jsonify({"error": "check_name and status are required"}), 400

    save_compatibility_check(token, check_name, status, details)
    return jsonify({"message": "Compatibility check saved"})


@app.route("/api/interviews/<token>/event", methods=["POST"])
def interview_event(token):
    interview = get_interview_by_token(token)
    if not interview:
        return jsonify({"error": "Interview not found"}), 404

    data = request.get_json(silent=True) or {}
    event_type = (data.get("event_type") or "").strip()
    details = (data.get("details") or "").strip()

    if not event_type:
        return jsonify({"error": "event_type is required"}), 400

    save_proctoring_event(token, event_type, details)
    return jsonify({"message": "Event saved"})


@app.route("/interview")
def interview_room():
    token = request.args.get("token")
    if not token:
        return "Missing token", 400

    interview = get_interview_by_token(token)
    if not interview:
        return "Interview not found", 404

    now = datetime.now()
    interview_time = datetime.strptime(interview["interview_time"], "%Y-%m-%dT%H:%M")
    slot_start = interview_time - timedelta(minutes=5)
    slot_end = interview_time + timedelta(minutes=30)

    if now < slot_start:
        return (
            f"<h1>Too early!</h1><p>Your interview starts at {interview['interview_time']}. Please return then.</p>",
            403,
        )
    if now > slot_end:
        return (
            f"<h1>Interview Expired</h1><p>The interview slot for {interview['interview_time']} has expired.</p>",
            403,
        )

    return render_template(
        "interview.html",
        name=interview["candidate_name"],
        token=token,
        interview_time=interview["interview_time"],
    )


@app.route("/api/interviews/<token>/start", methods=["POST"])
def interview_start(token):
    interview = get_interview_by_token(token)
    if not interview:
        return jsonify({"error": "Interview not found"}), 404

    update_interview_started(token)
    save_proctoring_event(token, "interview_started", "Candidate entered the interview room")
    return jsonify({"message": "Interview started"})


@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    token = data.get("token")
    prompt = (data.get("prompt") or "").strip()
    context = data.get("context", [])
    elapsed_minutes = float(data.get("elapsed_minutes", 0) or 0)

    interview = get_interview_by_token(token) if token else None
    if not interview:
        return jsonify({"error": "Interview not found"}), 404

    if prompt:
        save_interview_message(token, "candidate", prompt)

    if elapsed_minutes < 10:
        timing_instruction = (
            f"Only {elapsed_minutes:.1f} minutes have passed. The interview must last at least 10 minutes. "
            "Keep asking deep technical or behavioral questions."
        )
    else:
        timing_instruction = (
            f"{elapsed_minutes:.1f} minutes have passed. You may conclude the interview if you have enough information. "
            "If concluding, start with exactly '[CONCLUDE]' and end with a warm thank you."
        )

    system_instruction = (
        "You are a professional AI recruiter. Ask one insightful follow-up question at a time. "
        "Be polite, concise, and conversational. "
        f"{timing_instruction} "
        "The candidate just said: "
    )
    full_prompt = (
        f"{system_instruction}\"{prompt}\"\n\n"
        "Respond with the next question or conclude if appropriate."
    )

    try:
        response = requests.post(
            OLLAMA_URL,
            json={
                "model": OLLAMA_MODEL,
                "prompt": full_prompt,
                "stream": False,
                "context": context,
            },
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        ai_response = (payload.get("response") or "").strip()
        response_context = payload.get("context", context)
        if not ai_response:
            ai_response = "Please continue and share a specific example from your recent experience."
    except Exception:
        ai_response = (
            "I am having trouble reaching the AI engine right now, but we can still continue. "
            "Please tell me more about your recent experience and the tools you used."
        )
        response_context = context

    save_interview_message(token, "ai", ai_response)
    update_interview_started(token)

    return jsonify(
        {
            "response": ai_response,
            "context": response_context,
        }
    )


@app.route("/api/interviews/<token>/complete", methods=["POST"])
def interview_complete(token):
    interview = get_interview_by_token(token)
    if not interview:
        return jsonify({"error": "Interview not found"}), 404

    data = request.get_json(silent=True) or {}
    duration_minutes = float(data.get("duration_minutes", 0) or 0)
    transcript_payload = data.get("transcript") or []

    if not transcript_payload:
        transcript_payload = _messages_from_rows(get_interview_messages(token))
    elif isinstance(transcript_payload, list):
        transcript_payload = transcript_payload
    else:
        transcript_payload = []

    transcript_text = _normalize_transcript(transcript_payload)
    score_data = score_interview(transcript_payload, duration_minutes, completed=True)

    complete_interview(
        token,
        score_data["score"],
        json.dumps(score_data, ensure_ascii=False),
        transcript_text,
        duration_minutes,
    )
    save_proctoring_event(token, "interview_completed", f"Final score {score_data['score']}")

    return jsonify(
        {
            "message": "Interview completed",
            "score": score_data["score"],
            "summary": score_data.get("summary", ""),
            "strengths": score_data.get("strengths", []),
            "concerns": score_data.get("concerns", []),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=True)
