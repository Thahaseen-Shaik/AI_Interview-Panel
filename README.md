# Interview_Schedular

Flask interview scheduling app with single and bulk interview invites.

## Run

1. Create a `.env` file or keep editing `.env.example`.
2. Set your SMTP credentials and API settings.
3. Set `PUBLIC_BASE_URL` to the public URL where this app is deployed if you want people on different networks to join from email. If everyone is on the same Wi-Fi/LAN, the app will try to use your machine's LAN IP automatically.
4. Set your Groq API values:
   - `GROQ_API_KEY`
   - `GROQ_MODEL` if you want to override the default
   - `GROQ_BASE_URL` only if you use a custom Groq-compatible endpoint
5. Install dependencies:
   `pip install -r requirements.txt`
6. Start the app:
   `python main.py`
7. Open `http://localhost:8000`.

## Deploy on Render

1. Push this repository to GitHub.
2. In Render, create a new Web Service from the repository and let it use `render.yaml`.
3. Use the bundled Render Postgres database in `render.yaml`. The web service is configured to use `DATABASE_URL` from that database.
4. Set these environment variables in Render:
   - `SMTP_HOST`
   - `SMTP_PORT`
   - `SMTP_USER`
   - `MAIL_PASSWORD`
   - `SMTP_FROM`
   - `GROQ_API_KEY`
   - optionally `GROQ_MODEL`
5. Render will use the public service URL for invite links, so interviews can be opened from phones and laptops anywhere.
6. For higher traffic, upgrade the web service plan in Render to `standard` or above.

## Bulk scheduling

- Use the dashboard bulk form to paste up to 100 candidates.
- Supported line formats:
  - `Name, email@example.com`
  - `Name <email@example.com>`
  - `email@example.com`
