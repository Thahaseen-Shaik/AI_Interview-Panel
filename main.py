import json
import os
import re
import socket
from datetime import datetime, timedelta
from functools import wraps
from urllib.parse import urlparse

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
    get_interview_context,
    get_interview_messages,
    get_proctoring_events,
    init_db,
    save_interview_message,
    save_compatibility_check,
    save_proctoring_event,
    save_interview_context,
    schedule_interview,
    schedule_interviews_bulk,
    update_interview_started,
)
from email_utils import send_bulk_interview_emails, send_interview_email


load_dotenv()
load_dotenv(".env.example")

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret-key-change-me")
init_db()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "").strip()
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
GROQ_BASE_URL = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1")
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")


def _is_local_base_url(base_url):
    if not base_url:
        return True
    parsed = urlparse(base_url if "://" in base_url else f"http://{base_url}")
    hostname = (parsed.hostname or "").lower()
    return hostname in {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "your-public-domain.com",
        "example.com",
    }


def _resolve_invite_base_url():
    for candidate in (
        os.getenv("PUBLIC_BASE_URL", "").strip(),
        os.getenv("BASE_URL", "").strip(),
        request.url_root.rstrip("/") if request and request.url_root else "",
    ):
        if candidate:
            candidate = candidate.rstrip("/")
            if not _is_local_base_url(candidate):
                return candidate

    local_ip = _detect_lan_base_url()
    if local_ip:
        return local_ip

    if request and request.url_root:
        return request.url_root.rstrip("/")
    return BASE_URL.rstrip("/")


def _detect_lan_base_url():
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 80))
            local_ip = probe.getsockname()[0]
        finally:
            probe.close()

        if local_ip and not local_ip.startswith("127.") and local_ip != "0.0.0.0":
            return f"http://{local_ip}:8000"
    except Exception:
        pass
    return ""


def _invite_url_warning(base_url):
    if _is_local_base_url(base_url):
        return (
            "Invite links are still using a local address. If recipients are on another network, "
            "set PUBLIC_BASE_URL to a public deployment URL."
        )
    return ""


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


def _groq_chat(messages, *, temperature=0.7, max_tokens=256):
    if not GROQ_API_KEY:
        raise RuntimeError("GROQ_API_KEY is not configured")

    response = requests.post(
        f"{GROQ_BASE_URL.rstrip('/')}/chat/completions",
        headers={
            "Authorization": f"Bearer {GROQ_API_KEY}",
            "Content-Type": "application/json",
        },
        json={
            "model": GROQ_MODEL,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    choices = payload.get("choices") or []
    if not choices:
        return ""
    message = choices[0].get("message") or {}
    return (message.get("content") or "").strip()


def _groq_history_from_rows(rows):
    history = []
    for row in rows[-20:]:
        content = (row["content"] or "").strip()
        if not content:
            continue
        role = "assistant" if row["speaker"] == "ai" else "user"
        history.append({"role": role, "content": content})
    return history


EMAIL_PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
TOKEN_PATTERN = re.compile(r"[a-z0-9']+")

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "because",
    "but",
    "can",
    "could",
    "do",
    "does",
    "for",
    "from",
    "has",
    "have",
    "how",
    "i",
    "if",
    "in",
    "is",
    "it",
    "me",
    "my",
    "of",
    "on",
    "or",
    "please",
    "so",
    "that",
    "the",
    "their",
    "this",
    "to",
    "we",
    "what",
    "when",
    "where",
    "which",
    "with",
    "you",
    "your",
}

FILLER_PATTERNS = (
    r"\bum\b",
    r"\buh\b",
    r"\ber\b",
    r"\bah\b",
    r"\blike\b",
    r"\byou know\b",
    r"\bbasically\b",
    r"\bactually\b",
    r"\bsort of\b",
    r"\bkind of\b",
)

TECHNICAL_TERMS = {
    "algorithm",
    "api",
    "architecture",
    "authentication",
    "automation",
    "backend",
    "cloud",
    "coding",
    "concurrency",
    "data",
    "database",
    "debugging",
    "deployment",
    "design",
    "frontend",
    "framework",
    "html",
    "http",
    "integration",
    "java",
    "javascript",
    "kubernetes",
    "learning",
    "machine",
    "model",
    "network",
    "optimization",
    "python",
    "react",
    "reliability",
    "security",
    "sql",
    "testing",
    "training",
    "ui",
    "ux",
}


def _normalize_candidate_name(email_address):
    local_part = email_address.split("@", 1)[0]
    local_part = re.sub(r"[._-]+", " ", local_part).strip()
    return local_part.title() if local_part else "Candidate"


def _tokenize(text):
    return TOKEN_PATTERN.findall((text or "").lower())


def _count_filler_terms(text):
    lowered = (text or "").lower()
    return sum(len(re.findall(pattern, lowered)) for pattern in FILLER_PATTERNS)


def _collect_candidate_response_stats(messages):
    candidate_texts = []
    paired_questions = []
    last_ai_message = ""

    for item in messages:
        speaker = item.get("speaker")
        content = (item.get("content") or "").strip()
        if not content:
            continue
        if speaker == "ai":
            last_ai_message = content
        elif speaker in ("candidate", "user"):
            candidate_texts.append(content)
            paired_questions.append(last_ai_message)

    combined_text = " ".join(candidate_texts)
    tokens = _tokenize(combined_text)
    unique_tokens = set(tokens)
    total_words = len(tokens)
    total_turns = len(candidate_texts)
    average_turn_words = (total_words / total_turns) if total_turns else 0
    filler_count = sum(_count_filler_terms(text) for text in candidate_texts)
    punctuation_count = len(re.findall(r"[.!?]", combined_text))
    tech_term_hits = sum(1 for token in unique_tokens if token in TECHNICAL_TERMS)

    relevance_scores = []
    for answer, question in zip(candidate_texts, paired_questions):
        answer_tokens = {
            token for token in _tokenize(answer) if len(token) > 2 and token not in STOPWORDS
        }
        question_tokens = {
            token for token in _tokenize(question) if len(token) > 2 and token not in STOPWORDS
        }
        if not question_tokens:
            continue
        overlap = len(answer_tokens & question_tokens)
        relevance_scores.append(min(1.0, overlap / max(4, len(question_tokens) / 2)))

    relevance_score = sum(relevance_scores) / len(relevance_scores) if relevance_scores else 0.45

    speaking_score = 0
    speaking_score += min(12, total_turns * 3)
    speaking_score += min(8, int(round(average_turn_words / 5)))
    speaking_score += min(6, punctuation_count)
    speaking_score += min(4, len(unique_tokens) // 25)
    speaking_score -= min(10, filler_count * 2)
    speaking_score = max(0, min(30, speaking_score))

    grammar_score = 8
    grammar_score += min(7, punctuation_count)
    grammar_score += 4 if total_turns >= 2 else 1
    grammar_score += 4 if average_turn_words >= 12 else 1
    grammar_score -= min(12, filler_count * 2)
    grammar_score -= 2 if total_words and len(unique_tokens) / max(1, total_words) < 0.45 else 0
    grammar_score = max(0, min(25, grammar_score))

    role_content_score = int(round(relevance_score * 18))
    role_content_score += min(7, total_words // 30)
    role_content_score += 2 if total_turns >= 3 else 0
    role_content_score = max(0, min(25, role_content_score))

    subject_knowledge_score = 0
    subject_knowledge_score += min(8, tech_term_hits * 2)
    subject_knowledge_score += min(6, total_words // 40)
    subject_knowledge_score += min(4, len({token for token in unique_tokens if len(token) >= 8}) // 3)
    subject_knowledge_score += 2 if any(
        token in {"built", "implemented", "designed", "resolved", "improved", "optimized"}
        for token in unique_tokens
    ) else 0
    subject_knowledge_score = max(0, min(20, subject_knowledge_score))

    return {
        "candidate_texts": candidate_texts,
        "total_turns": total_turns,
        "total_words": total_words,
        "average_turn_words": average_turn_words,
        "filler_count": filler_count,
        "punctuation_count": punctuation_count,
        "relevance_score": relevance_score,
        "speaking_score": speaking_score,
        "grammar_score": grammar_score,
        "role_content_score": role_content_score,
        "subject_knowledge_score": subject_knowledge_score,
    }


def _parse_candidate_line(line):
    normalized = line.strip()
    if not normalized:
        return None, None

    email_match = EMAIL_PATTERN.search(normalized)
    email = email_match.group(0).strip() if email_match else ""
    name = normalized

    if "<" in normalized and ">" in normalized:
        before, _, remainder = normalized.partition("<")
        name = before.strip().rstrip(",|-")
        email = remainder.split(">", 1)[0].strip()
    elif "," in normalized:
        left, right = normalized.split(",", 1)
        name = left.strip()
        right_email = EMAIL_PATTERN.search(right)
        if right_email:
            email = right_email.group(0).strip()
    elif "|" in normalized:
        left, right = normalized.split("|", 1)
        name = left.strip()
        right_email = EMAIL_PATTERN.search(right)
        if right_email:
            email = right_email.group(0).strip()
    elif not email:
        parts = normalized.split()
        if len(parts) == 1 and EMAIL_PATTERN.fullmatch(parts[0]):
            email = parts[0]
        elif len(parts) > 1:
            potential_email = parts[-1]
            if EMAIL_PATTERN.fullmatch(potential_email):
                email = potential_email
                name = " ".join(parts[:-1]).strip()

    if not email or not EMAIL_PATTERN.fullmatch(email):
        return None, "Each candidate needs a valid email address."

    if not name or name == email:
        name = _normalize_candidate_name(email)
    else:
        name = re.sub(r"\s+", " ", name).strip(" ,|-")

    return {
        "candidate_name": name,
        "candidate_email": email,
    }, None


def _parse_bulk_candidates(raw_text):
    candidates = []
    errors = []

    for line_number, raw_line in enumerate((raw_text or "").splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue
        candidate, error = _parse_candidate_line(line)
        if error:
            errors.append(f"Line {line_number}: {error}")
            continue
        candidates.append(candidate)

    return candidates, errors


def _build_interview_link(base_url, token):
    return f"{base_url}/interview?token={token}"


def _schedule_candidate_batch(candidates, interview_time, base_url):
    scheduled = schedule_interviews_bulk(candidates, interview_time)
    recipients = [
        {
            "candidate_name": row["candidate_name"],
            "to_email": row["candidate_email"],
            "interview_time": row["interview_time"],
            "interview_link": _build_interview_link(base_url, row["token"]),
        }
        for row in scheduled
    ]

    if len(recipients) == 1:
        email_result = send_interview_email(
            recipients[0]["to_email"],
            recipients[0]["candidate_name"],
            recipients[0]["interview_time"],
            recipients[0]["interview_link"],
        )
    else:
        email_result = send_bulk_interview_emails(recipients)

    if email_result is True:
        email_status = "sent"
    elif email_result is None:
        email_status = "skipped"
    else:
        email_status = "failed"

    return scheduled, recipients, email_status


def _calculate_fallback_score(messages, duration_minutes, completed=True):
    stats = _collect_candidate_response_stats(messages)

    score = 0
    score += stats["speaking_score"]
    score += stats["grammar_score"]
    score += stats["role_content_score"]
    score += stats["subject_knowledge_score"]
    if completed:
        score += 4
    if duration_minutes and duration_minutes >= 5:
        score += 3

    score = max(0, min(100, int(round(score))))
    if score >= 85:
        summary = "Excellent speaking, grammar, role relevance, and subject knowledge."
    elif score >= 70:
        summary = "Strong interview performance with good clarity and solid technical depth."
    elif score >= 50:
        summary = "Average interview performance with room to improve fluency, grammar, and depth."
    else:
        summary = "Interview needs stronger speaking clarity, grammar, and role-specific detail."

    grammar_note = (
        "Keep grammar and sentence structure consistent under pressure."
        if stats["grammar_score"] >= 17
        else "Grammar and sentence structure need more polish."
    )
    speaking_note = (
        "Speaking was clear and confident."
        if stats["speaking_score"] >= 20
        else "Speaking fluency and pacing can improve."
    )
    content_note = (
        "Answers stayed relevant to the interview questions."
        if stats["role_content_score"] >= 15
        else "Answers should stay more tightly focused on the role."
    )
    knowledge_note = (
        "Continue adding deeper technical examples."
        if stats["subject_knowledge_score"] >= 12
        else "Subject knowledge needs more depth and examples."
    )

    return {
        "score": score,
        "summary": summary,
        "strengths": [
            "Completed the interview flow" if completed else "Interview still in progress",
            speaking_note if stats["speaking_score"] >= 20 else "Speaking needs more fluency and confidence.",
            content_note if stats["role_content_score"] >= 15 else "Need more role-specific and relevant detail.",
        ],
        "concerns": [
            grammar_note if stats["grammar_score"] < 17 else "Maintain that grammar quality consistently.",
            knowledge_note if stats["subject_knowledge_score"] < 12 else "Keep building on strong subject knowledge.",
        ],
    }


def _score_with_groq(messages, duration_minutes, completed=True):
    transcript_text = _normalize_transcript(messages)
    if not transcript_text.strip():
        return None

    system_message = (
        "You are an interview evaluator. Return ONLY valid JSON with these keys: "
        "score (integer from 0 to 100), summary (short single paragraph), strengths (array of short bullet phrases), "
        "concerns (array of short bullet phrases). "
        "Scoring rubric: speaking skill and fluency 30 points, grammar accuracy and sentence clarity 25 points, "
        "role content and relevance 25 points, subject knowledge and depth 20 points. "
        "Favor answers that sound clear, confident, and easy to understand. Penalize repeated grammar issues, filler words, "
        "and vague responses. Reward role-specific content, accurate technical detail, and good examples. "
        "If the interview was not completed, reduce the score slightly. Keep the output concise and valid JSON only."
    )
    user_message = (
        f"Duration minutes: {duration_minutes:.1f}\n"
        f"Completed: {str(completed).lower()}\n\n"
        f"Transcript:\n{transcript_text}"
    )

    text = _groq_chat(
        [
            {"role": "system", "content": system_message},
            {"role": "user", "content": user_message},
        ],
        temperature=0.2,
        max_tokens=512,
    )
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
        scored = _score_with_groq(messages, duration_minutes, completed=completed)
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
    base_url = _resolve_invite_base_url()
    scheduled, recipients, email_status = _schedule_candidate_batch(
        [
            {
                "candidate_name": name,
                "candidate_email": email,
            }
        ],
        interview_time,
        base_url,
    )
    interview = scheduled[0]
    link = recipients[0]["interview_link"]

    if email_status == "sent":
        message = "Interview scheduled and email sent."
    elif email_status == "skipped":
        message = "Interview scheduled."
    else:
        message = "Interview scheduled, but email delivery failed."

    return jsonify(
        {
            "message": message,
            "link": link,
            "token": interview["token"],
            "email_status": email_status,
            "scheduled_count": 1,
            "invite_base_url": base_url,
            "warning": _invite_url_warning(base_url),
            "scheduled": [
                {
                    "candidate_name": interview["candidate_name"],
                    "candidate_email": interview["candidate_email"],
                    "link": link,
                    "token": interview["token"],
                }
            ],
        }
    )


@app.route("/schedule/bulk", methods=["POST"])
@login_required
def schedule_bulk():
    interview_time = (request.form.get("time") or "").strip()
    candidates_text = request.form.get("candidates") or ""

    if not interview_time:
        return jsonify({"message": "Interview time is required."}), 400

    candidates, errors = _parse_bulk_candidates(candidates_text)
    if errors:
        return jsonify({"message": "One or more candidate lines are invalid.", "errors": errors}), 400
    if not candidates:
        return jsonify({"message": "Add at least one candidate."}), 400
    if len(candidates) > 100:
        return jsonify({"message": "You can schedule up to 100 interviews at once."}), 400

    base_url = _resolve_invite_base_url()
    scheduled, recipients, email_status = _schedule_candidate_batch(candidates, interview_time, base_url)

    if email_status == "sent":
        message = f"Scheduled {len(scheduled)} interviews and sent all invitations."
    elif email_status == "skipped":
        message = f"Scheduled {len(scheduled)} interviews. SMTP is not configured, so emails were skipped."
    else:
        message = f"Scheduled {len(scheduled)} interviews, but email delivery failed."

    return jsonify(
        {
            "message": message,
            "email_status": email_status,
            "scheduled_count": len(scheduled),
            "invite_base_url": base_url,
            "warning": _invite_url_warning(base_url),
            "scheduled": [
                {
                    "candidate_name": row["candidate_name"],
                    "candidate_email": row["candidate_email"],
                    "link": recipient["interview_link"],
                    "token": row["token"],
                }
                for row, recipient in zip(scheduled, recipients)
            ],
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
    compatibility_summary = {
        "passed": sum(1 for item in compatibility_checks if item.get("status", "").lower() == "passed"),
        "failed": sum(1 for item in compatibility_checks if item.get("status", "").lower() == "failed"),
        "pending": sum(1 for item in compatibility_checks if item.get("status", "").lower() not in {"passed", "failed"}),
    }
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
        compatibility_summary=compatibility_summary,
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
    mode = (request.args.get("mode") or "compat").strip().lower()
    if not token:
        return "Missing token", 400

    interview = get_interview_by_token(token)
    if not interview:
        return "Interview not found", 404

    now = datetime.now()
    interview_time = datetime.strptime(interview["interview_time"], "%Y-%m-%dT%H:%M")
    slot_end = interview_time + timedelta(minutes=30)
    is_waiting = now < interview_time
    seconds_until_start = max(0, int((interview_time - now).total_seconds()))

    if now > slot_end:
        return (
            f"<h1>Interview Expired</h1><p>The interview slot for {interview['interview_time']} has expired.</p>",
            403,
        )

    show_waiting = mode != "start" or now < interview_time
    show_interview = mode == "start" and now >= interview_time

    return render_template(
        "interview.html",
        name=interview["candidate_name"],
        token=token,
        interview_time=interview["interview_time"],
        is_waiting=is_waiting,
        seconds_until_start=seconds_until_start,
        entry_mode=mode,
        show_waiting=show_waiting,
        show_interview=show_interview,
    )


@app.route("/system-check")
def system_check():
    token = request.args.get("token")
    if not token:
        return "Missing token", 400

    interview = get_interview_by_token(token)
    if not interview:
        return "Interview not found", 404

    now = datetime.now()
    interview_time = datetime.strptime(interview["interview_time"], "%Y-%m-%dT%H:%M")
    slot_end = interview_time + timedelta(minutes=30)
    seconds_until_start = max(0, int((interview_time - now).total_seconds()))

    if now > slot_end:
        return (
            f"<h1>Interview Expired</h1><p>The interview slot for {interview['interview_time']} has expired.</p>",
            403,
        )

    return render_template(
        "system_check.html",
        name=interview["candidate_name"],
        token=token,
        interview_time=interview["interview_time"],
        seconds_until_start=seconds_until_start,
        waiting_url=url_for("interview_room", token=token),
        enter_url=url_for("interview_room", token=token, mode="start"),
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
    history = _groq_history_from_rows(get_interview_messages(token))
    messages = [{"role": "system", "content": system_instruction}]
    messages.extend(history)

    try:
        ai_response = _groq_chat(
            messages,
            temperature=0.7,
            max_tokens=256,
        )
        if not ai_response:
            ai_response = "Please continue and share a specific example from your recent experience."
    except Exception:
        ai_response = (
            "I am having trouble reaching the AI engine right now, but we can still continue. "
            "Please tell me more about your recent experience and the tools you used."
        )

    save_interview_message(token, "ai", ai_response)
    update_interview_started(token)

    return jsonify(
        {
            "response": ai_response,
            "context": history,
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
    port = int(os.getenv("PORT", "8000"))
    debug = os.getenv("FLASK_DEBUG", "1").strip().lower() in {"1", "true", "yes", "on"}
    app.run(host="0.0.0.0", port=port, debug=debug)
