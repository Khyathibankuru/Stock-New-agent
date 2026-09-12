# Daily Stock Market Brief Agent

Fetches RSS news + live stock/index prices every morning, uses Gemini
(plain text generation — not the search/grounding tool, to stay on the
free tier) to pick and summarize the top items, rebuilds `index.html`,
and sends you a Telegram message with the link once it's live.

## How it fits together

```
GitHub Actions (cron, 7:30 AM IST)
        │
        ▼
   agent.py
   ├── fetch RSS (global / india / metal & gas)
   ├── fetch stock + index prices (yfinance)
   ├── call Gemini → pick + summarize top items
   ├── render templates/index_template.html → index.html
   └── send Telegram message with the site link
        │
        ▼
git commit + push index.html
        │
        ▼
GitHub Pages serves the updated index.html
```

## One-time setup

1. **Create a GitHub repo** and push this whole folder to it.

2. **Enable GitHub Pages**
   Repo → Settings → Pages → Source: "Deploy from a branch" → branch
   `main`, folder `/ (root)`. Your site will be live at:
   `https://<your-username>.github.io/<repo-name>/`

3. **Add repo secrets** (Settings → Secrets and variables → Actions → *Secrets*):
   - `GEMINI_API_KEY` — your Gemini API key
   - `TELEGRAM_BOT_TOKEN` — your existing Telegram bot token
   - `TELEGRAM_CHAT_ID` — the chat ID the bot should message

4. **Add one repo variable** (same page → *Variables* tab):
   - `SITE_URL` — the GitHub Pages URL from step 2, e.g.
     `https://yourname.github.io/stock-agent/`

5. **Adjust the watchlist / feeds** if needed — everything is in the
   `CONFIG` section at the top of `agent.py` (`INDIA_STOCKS`,
   `METAL_GAS_STOCKS`, `GLOBAL_STOCKS`, `INDICES`, `RSS_FEEDS`).
   RSS providers occasionally rename or retire feed URLs — if one
   404s, swap in an alternative from the same publisher. The script
   skips any feed that fails to parse instead of crashing.

6. **Test it manually** before trusting the schedule:
   Actions tab → "Daily Stock Market Brief" → "Run workflow" (this
   uses the `workflow_dispatch` trigger). Check the log, check that
   `index.html` updated, check that the Telegram message arrived.

## Running locally (optional, for testing)

```bash
pip install -r requirements.txt
export GEMINI_API_KEY=your_key
export TELEGRAM_BOT_TOKEN=your_token
export TELEGRAM_CHAT_ID=your_chat_id
export SITE_URL=https://yourname.github.io/stock-agent/
python agent.py
```

This writes `index.html` in the same folder — open it directly in a
browser to preview before it ever touches GitHub Actions.

## Notes / honest caveats

- **No live Twitter/X or YouTube data.** Nothing has free API access
  to that anymore. "Trending" here is computed by us: if a stock name
  shows up repeatedly in the day's fetched RSS headlines, it's flagged
  trending. That's attention-from-news, not social-media buzz — a
  more honest signal than most tools that claim "Twitter trending."
- **Gemini is called without the grounding/search tool** on purpose —
  the grounded search tool has a much stricter free daily quota than
  plain text generation. Since we already fetch the news ourselves via
  RSS, Gemini only needs to summarize what we hand it, not search live.
- **yfinance is unofficial** (it scrapes Yahoo Finance's public
  endpoints). It's free and generally reliable, but Yahoo can change
  things without notice — if a ticker starts returning nothing, that's
  usually why. It's fine for an informational brief, not something to
  wire to real trading.
- This is an information/summary tool, not investment advice, and
  not an auto-trader — it never places trades.
