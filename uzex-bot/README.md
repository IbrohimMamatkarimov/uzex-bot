# UZEX AI Hackathon - registry Q&A bot (uz / ru)
Telegram bot. Gemini turns a question into SQL, DuckDB runs it on data/*.parquet (500k deals), Gemini phrases the answer.

Run locally:
  pip install -r requirements.txt
  export TELEGRAM_TOKEN=... GEMINI_API_KEY=... BOT_USERNAME=your_bot
  python bot.py

Deploy: push to GitHub -> Render "New Web Service" (render.yaml included) -> set the 3 env vars.
Keep awake: add the Render URL to UptimeRobot (5 min ping).
data/ was built from the organisers' CSVs with prep_data.py (clean types, commodity normalisation by HS code, UZS conversion).
