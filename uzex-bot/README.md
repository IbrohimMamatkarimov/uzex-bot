# UZEX AI Hackathon - registry Q&A bot (uz / ru)
Telegram bot. Gemini turns a question into SQL, DuckDB runs it on data/*.parquet (500k deals), Gemini phrases the answer.

Run locally:
  pip install -r requirements.txt
  export TELEGRAM_TOKEN=... GEMINI_API_KEY=... BOT_USERNAME=your_bot
  python bot.py

Deploy: push to GitHub -> Render "New Web Service" (render.yaml included) -> set the 3 env vars.
Keep awake: add the Render URL to UptimeRobot (5 min ping).
data/ was built from the organisers' CSVs with prep_data.py (clean types, commodity normalisation by HS code, UZS conversion).

Telegram Mini App:
  URL: https://uzex-bot-tbm8.onrender.com/app
  The app is served by the same Render service. It verifies Telegram initData before querying the agent.
  On startup, the bot sets its Telegram menu button to open the Mini App. The /start message also has an Open App button and sample questions.
  To register it through BotFather, use /newapp or /setmenubutton and enter the URL above after the updated service is deployed.
  If the Render URL changes, set MINI_APP_URL to the new HTTPS URL ending in /app.

Voice and motion:
    The Mini App records a short question with the microphone and reads answers aloud with built-in speech synthesis. It falls back to browser speech recognition where recording is unavailable.
  Telegram accepts voice notes up to 45 seconds; the same Gemini data agent answers them without a separate transcription request.
  /start uses a looping UZEX assistant animation. UI motion respects the device's reduced-motion preference.
  Startup no longer probes every Gemini model; diagnostics run only when /test is requested, avoiding needless API quota use.
