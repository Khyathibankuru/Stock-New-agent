"""
Daily Stock Market Brief Agent
------------------------------
Fetches RSS news + live stock/index prices, asks Gemini (plain text
generation, NOT the grounded/search tool, to stay on the generous free
tier) to pick and summarize the top items, renders index.html from a
template, and pushes a Telegram message with a link to the updated page.

This mirrors the pattern already used in your AI-news-agent project:
RSS -> Gemini (no grounding) -> structured output -> render/send.

Run manually:  python agent.py
Run in CI:     triggered by .github/workflows/daily-brief.yml
"""

import os
import re
import json
import datetime
import requests
import feedparser
import yfinance as yf
from jinja2 import Environment, FileSystemLoader

# ----------------------------------------------------------------------
# CONFIG — edit this section to change tickers, feeds, counts, etc.
# ----------------------------------------------------------------------

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
GEMINI_MODEL = "gemini-2.0-flash"  # plain text generation, free-tier friendly
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

# The public URL where index.html ends up (e.g. GitHub Pages).
# Set this as a repo secret/variable once you know it, e.g.:
# https://<username>.github.io/<repo>/
SITE_URL = os.environ.get("SITE_URL", "https://example.github.io/stock-agent/")

RSS_FEEDS = {
    "global": [
        "https://www.cnbc.com/id/100003114/device/rss/rss.html",   # CNBC world markets
        "https://feeds.a.dj.com/rss/RSSMarketsMain.xml",           # WSJ markets
    ],
    "india": [
        "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",
        "https://www.business-standard.com/rss/markets-106.rss",
        "https://www.moneycontrol.com/rss/business.xml",
    ],
    "metal_gas": [
        "https://www.mining.com/feed/",
        "https://oilprice.com/rss/main",
    ],
}
# NOTE: RSS providers change/rename feeds often. If any of the above 404s,
# swap in an alternative from the same publisher — the script skips any
# feed that fails to parse instead of crashing.

# Ticker watchlists. Indian tickers use the .NS suffix for Yahoo Finance.
INDIA_STOCKS = [
    ("TCS", "TCS.NS", "IT"),
    ("Infosys", "INFY.NS", "IT"),
    ("HCL Technologies", "HCLTECH.NS", "IT"),
    ("Tech Mahindra", "TECHM.NS", "IT"),
    ("Tata Steel", "TATASTEEL.NS", "metals"),
    ("Vedanta", "VEDL.NS", "metals"),
    ("Hindustan Zinc", "HINDZINC.NS", "metals"),
    ("Adani Enterprises", "ADANIENT.NS", "conglomerate"),
    ("Power Grid", "POWERGRID.NS", "infra"),
    ("Sun Pharma", "SUNPHARMA.NS", "pharma"),
]
METAL_GAS_STOCKS = [
    ("Tata Steel", "TATASTEEL.NS", "steel"),
    ("Vedanta", "VEDL.NS", "diversified metals"),
    ("Hindustan Zinc", "HINDZINC.NS", "zinc"),
    ("Hindalco Industries", "HINDALCO.NS", "aluminium"),
    ("GAIL (India)", "GAIL.NS", "gas distribution"),
]
GLOBAL_STOCKS = [
    ("Nvidia", "NVDA", "AI chips"),
    ("Alphabet", "GOOG", "tech"),
    ("Apple", "AAPL", "tech"),
    ("Nike", "NKE", "consumer"),
    ("Amazon", "AMZN", "tech/retail"),
]
INDICES = [
    ("Sensex", "^BSESN"),
    ("Nifty 50", "^NSEI"),
    ("Nifty Metal", "^CNXMETAL"),
    ("Nifty IT", "^CNXIT"),
]

COUNTS = {"global": 5, "india": 10, "metal_gas": 5}

# ----------------------------------------------------------------------
# RSS FETCHING
# ----------------------------------------------------------------------

def fetch_feed_entries(url, max_items=15):
    try:
        feed = feedparser.parse(url)
        source = feed.feed.get("title", url)
        items = []
        for e in feed.entries[:max_items]:
            items.append({
                "title": e.get("title", "").strip(),
                "link": e.get("link", ""),
                "summary": re.sub("<[^<]+?>", "", e.get("summary", ""))[:400],
                "published": e.get("published", ""),
                "source": source,
            })
        return items
    except Exception as ex:
        print(f"[warn] failed to parse feed {url}: {ex}")
        return []


def fetch_all_news():
    news = {}
    for bucket, urls in RSS_FEEDS.items():
        entries = []
        for u in urls:
            entries.extend(fetch_feed_entries(u))
        news[bucket] = entries
    return news


# ----------------------------------------------------------------------
# STOCK / INDEX PRICES
# ----------------------------------------------------------------------

def get_quote(ticker):
    try:
        t = yf.Ticker(ticker)
        hist = t.history(period="2d")
        if len(hist) < 1:
            return None
        last = hist["Close"].iloc[-1]
        prev = hist["Close"].iloc[-2] if len(hist) > 1 else last
        pct = ((last - prev) / prev) * 100 if prev else 0
        return {"price": round(float(last), 2), "pct": round(float(pct), 2)}
    except Exception as ex:
        print(f"[warn] quote failed for {ticker}: {ex}")
        return None


def direction_and_display(pct):
    if pct is None:
        return "flat", "check live feed"
    if pct > 0.05:
        return "up", f"+{pct:.2f}%"
    if pct < -0.05:
        return "down", f"{pct:.2f}%"
    return "flat", f"{pct:.2f}%"


def build_stock_rows(stock_list, mention_text, currency_prefix=""):
    rows = []
    for name, ticker, tag in stock_list:
        q = get_quote(ticker)
        pct = q["pct"] if q else None
        direction, change_display = direction_and_display(pct)
        price_display = f"{currency_prefix}{q['price']:,}" if q else "check live feed"
        trending = name.lower() in mention_text.lower()
        rows.append({
            "name": name, "tag": tag, "price": price_display,
            "direction": direction, "change_display": change_display,
            "trending": trending,
        })
    return rows


def build_index_rows():
    rows = []
    for name, ticker in INDICES:
        q = get_quote(ticker)
        pct = q["pct"] if q else None
        direction, change_display = direction_and_display(pct)
        value = f"{q['price']:,}" if q else "—"
        rows.append({"name": name, "value": value, "direction": direction, "change_display": change_display})
    return rows


# ----------------------------------------------------------------------
# GEMINI — plain text generation (no grounding/search tool -> free tier)
# ----------------------------------------------------------------------

def call_gemini(news):
    """Ask Gemini to pick + summarize top items per bucket, and write one
    short overall note. No web-search tool is used here — we already did
    the fetching ourselves via RSS, so this stays on the generous free
    plain-text quota instead of the stricter grounded-search quota."""

    if not GEMINI_API_KEY:
        print("[warn] GEMINI_API_KEY not set — skipping Gemini call, using raw RSS order")
        return fallback_selection(news)

    def compact(entries):
        return [{"title": e["title"], "link": e["link"], "summary": e["summary"], "source": e["source"]} for e in entries]

    payload_for_model = {
        "global": compact(news["global"]),
        "india": compact(news["india"]),
        "metal_gas": compact(news["metal_gas"]),
    }

    prompt = f"""You are helping build a daily stock-market brief website.
Below is raw RSS data in three buckets: global, india, metal_gas.

Pick the {COUNTS['global']} most market-relevant items from "global",
the {COUNTS['india']} most market-relevant items from "india", and
the {COUNTS['metal_gas']} most market-relevant items from "metal_gas".
For each picked item, write a single one-sentence blurb (max 30 words)
summarizing why it matters, in your own words (do not copy sentences
verbatim from the summary). Also write one short overall paragraph
(max 40 words) capturing today's single biggest market theme.

Return STRICT JSON only, no markdown fences, no commentary, matching
exactly this schema:
{{
  "headline_note": "string",
  "global_top5": [{{"title": "...", "link": "...", "source": "...", "blurb": "..."}}],
  "india_top10": [{{"title": "...", "link": "...", "source": "...", "blurb": "..."}}],
  "metal_gas_top5": [{{"title": "...", "link": "...", "source": "...", "blurb": "..."}}]
}}

RAW DATA:
{json.dumps(payload_for_model)[:60000]}
"""

    body = {"contents": [{"parts": [{"text": prompt}]}]}
    try:
        resp = requests.post(GEMINI_URL, json=body, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        text = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        parsed = json.loads(text)
        return parsed
    except Exception as ex:
        print(f"[warn] Gemini call/parse failed: {ex} — falling back to raw RSS order")
        return fallback_selection(news)


def fallback_selection(news):
    """Used if Gemini is unavailable/quota-exhausted: just take the first
    N raw RSS items per bucket with their existing summary as the blurb."""
    def take(bucket, n):
        out = []
        for e in news[bucket][:n]:
            out.append({"title": e["title"], "link": e["link"], "source": e["source"], "blurb": e["summary"][:150]})
        return out

    return {
        "headline_note": "",
        "global_top5": take("global", COUNTS["global"]),
        "india_top10": take("india", COUNTS["india"]),
        "metal_gas_top5": take("metal_gas", COUNTS["metal_gas"]),
    }


# ----------------------------------------------------------------------
# RENDER
# ----------------------------------------------------------------------

def render_site(selection, news):
    all_text = " ".join(
        e["title"] + " " + e["summary"]
        for bucket in news.values() for e in bucket
    )

    india_stocks = build_stock_rows(INDIA_STOCKS, all_text, currency_prefix="₹")
    metal_gas_stocks = build_stock_rows(METAL_GAS_STOCKS, all_text, currency_prefix="₹")
    global_rows_all = build_stock_rows(GLOBAL_STOCKS, all_text, currency_prefix="$")

    trending_india = [s for s in (india_stocks + metal_gas_stocks) if s["trending"]]
    trending_global = [s for s in global_rows_all if s["trending"]] or global_rows_all[:5]

    env = Environment(loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "templates")))
    template = env.get_template("index_template.html")

    html = template.render(
        session_date=datetime.date.today().strftime("%b %d, %Y"),
        headline_note=selection.get("headline_note", ""),
        global_top5=selection.get("global_top5", []),
        india_top10=selection.get("india_top10", []),
        metal_gas_top5=selection.get("metal_gas_top5", []),
        indices=build_index_rows(),
        india_stocks=india_stocks,
        metal_gas_stocks=metal_gas_stocks,
        trending_india=trending_india,
        trending_global=trending_global,
        generated_at=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
    )

    out_path = os.path.join(os.path.dirname(__file__), "index.html")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[ok] wrote {out_path}")
    return out_path


# ----------------------------------------------------------------------
# TELEGRAM
# ----------------------------------------------------------------------

def send_telegram_message(text):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[warn] TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID not set — skipping Telegram send")
        return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text, "disable_web_page_preview": False}, timeout=30)
        r.raise_for_status()
        print("[ok] Telegram message sent")
    except Exception as ex:
        print(f"[warn] Telegram send failed: {ex}")


# ----------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------

def main():
    print("[1/4] Fetching RSS feeds...")
    news = fetch_all_news()

    print("[2/4] Asking Gemini to select & summarize top items...")
    selection = call_gemini(news)

    print("[3/4] Fetching stock/index prices and rendering site...")
    render_site(selection, news)

    print("[4/4] Sending Telegram notification...")
    today = datetime.date.today().strftime("%b %d, %Y")
    send_telegram_message(f"📈 Market brief for {today} is ready:\n{SITE_URL}")


if __name__ == "__main__":
    main()
