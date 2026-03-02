"""
News Catalyst Scanner
Runs every 15 minutes as a background job.

Two jobs in one loop:
  1. News scan    — pull Finnhub general news feed, match tier keywords, store new catalysts
  2. Price enrich — batch-fetch yfinance snapshots for all active entries,
                    update price/volume/price_change_pct, flag scanner_qualified if move qualifies

Quality rules:
  - Tier 1: always store  (hard catalyst: FDA, earnings, M&A, trial data, etc.)
  - Tier 2: single-ticker article + specific keyword only (thematic, partnership, etc.)
  - Tier 3: dropped
  - Max 200 active entries (oldest trimmed)
  - 48hr TTL per entry
"""

import os
import re
import requests
import time
import threading
from datetime import datetime, timedelta, timezone

SCAN_INTERVAL         = 15 * 60   # 15 minutes
WATCHLIST_TTL_HOURS   = 48
NEWS_LOOKBACK_MINUTES = 20
MAX_FEED_ENTRIES      = 200

QUALIFY_MIN_CHANGE_PCT   = 10.0
QUALIFY_MIN_VOLUME_RATIO = 2.0

# ---------------------------------------------------------------------------
# TIER 1 — Hard catalysts (high conviction, always store)
# ---------------------------------------------------------------------------
LONG_TIER1 = [
    # FDA / regulatory
    'fda approval', 'fda approved', 'fda grants', 'fda clears', 'fda clearance',
    'pdufa', 'nda approval', 'bla approval', 'ema approval', 'ce mark',
    'breakthrough therapy', 'fast track designation', 'priority review',
    'accelerated approval', 'orphan drug designation',
    # Clinical trials
    'phase 3 results', 'phase 3 data', 'phase iii results', 'phase iii data',
    'phase 2 results', 'phase 2 data', 'pivotal trial results',
    'clinical trial results', 'positive results', 'met primary endpoint',
    'statistically significant', 'survival benefit',
    # Earnings beats
    'beats estimates', 'beats expectations', 'beat estimates', 'beat expectations',
    'raised guidance', 'raises guidance', 'raised outlook', 'raises outlook',
    'record revenue', 'record earnings', 'record profit',
    # M&A / buyout
    'acquisition', 'acquired by', 'merger agreement', 'buyout', 'takeover bid',
    'going private', 'strategic alternatives', 'sale process',
    # Contracts / partnerships (hard)
    'awarded contract', 'major contract', 'billion-dollar contract',
    'multi-billion', 'government contract', 'dod contract', 'pentagon contract',
    'defense contract', 'nasa contract', 'faa approval',
    # Technical
    'short squeeze', 'gamma squeeze',
]

SHORT_TIER1 = [
    # FDA negative
    'fda rejects', 'fda rejection', 'complete response letter', 'crl issued',
    'clinical hold', 'failed to meet', 'missed primary endpoint',
    'trial failure', 'phase 3 failed', 'phase iii failed',
    # Earnings misses
    'misses estimates', 'misses expectations', 'missed estimates',
    'lowered guidance', 'lowers guidance', 'lowered outlook', 'below expectations',
    # Corporate distress
    'going concern', 'material weakness', 'bankruptcy filing', 'chapter 11',
    'chapter 7', 'delisting notice', 'nasdaq delisting', 'nyse delisting',
    'sec investigation', 'doj investigation', 'subpoena', 'securities fraud',
    'restatement', 'accounting irregularities',
    # Leadership
    'ceo resigned', 'ceo departure', 'cfo resigned', 'cfo departure',
    'auditor resigned', 'auditor dismissal',
    # Dilution
    'dilutive offering', 'registered direct', 'atm offering',
]

# ---------------------------------------------------------------------------
# TIER 2 — Thematic / specific signals (single-ticker only)
# ---------------------------------------------------------------------------
TIER2_LONG_KEYWORDS = [
    'ai partnership', 'ai collaboration', 'ai agreement',
    'bitcoin treasury', 'crypto treasury', 'bitcoin reserve', 'ethereum treasury',
    'glp-1', 'ozempic', 'wegovy', 'semaglutide', 'tirzepatide',
    'quantum computing', 'quantum computer',
    'nuclear reactor', 'small modular reactor', 'smr',
    'hypersonic', 'drone contract', 'autonomous vehicle',
    'share repurchase', 'buyback program', 'special dividend',
    'new ceo', 'ceo appointment', 'new chief executive',
    'joint venture', 'license agreement', 'licensing deal',
    'strategic partnership', 'multi-year agreement',
    'exclusive agreement', 'distribution agreement',
    'ipo priced', 'uplisting', 'nasdaq uplisting',
]

TIER2_SHORT_KEYWORDS = [
    'going concern', 'material weakness', 'sec investigation',
    'doj investigation', 'subpoena', 'restatement',
    'ceo resigned', 'ceo departure', 'auditor resigned',
]

ETF_BLACKLIST = {
    'SPY', 'QQQ', 'IWM', 'DIA', 'VXX', 'SQQQ', 'TQQQ', 'UVXY',
    'GLD', 'SLV', 'USO', 'XLF', 'XLK', 'XLE', 'XLV', 'XLI',
    'ARKK', 'ARKG', 'ARKW', 'SOXS', 'SOXL', 'SVXY',
}


def _ts_now() -> str:
    """Clean ISO string without microseconds for DB storage."""
    return datetime.now().strftime('%Y-%m-%dT%H:%M:%S')


def _tier_match(headline: str, num_symbols: int) -> tuple:
    """
    Returns (tier, direction, matched_keyword) or (None, None, None).
    Tier 1: always pass.
    Tier 2: single-ticker article + specific keyword only.
    Tier 3: drop.
    """
    h = headline.lower()

    for kw in LONG_TIER1:
        if kw in h:
            return 1, 'long', kw
    for kw in SHORT_TIER1:
        if kw in h:
            return 1, 'short', kw

    if num_symbols == 1:
        for kw in TIER2_LONG_KEYWORDS:
            if kw in h:
                return 2, 'long', kw
        for kw in TIER2_SHORT_KEYWORDS:
            if kw in h:
                return 2, 'short', kw

    return None, None, None


# ---------------------------------------------------------------------------
# Finnhub — market-wide news feed
# ---------------------------------------------------------------------------
def _extract_symbols(headline: str, related: str = '') -> list:
    """
    Extract stock tickers from Finnhub article.
    Uses 'related' field first (comma-separated), then extracts from headline.
    """
    symbols = []

    if related:
        for sym in related.split(','):
            sym = sym.strip().upper()
            if 1 < len(sym) <= 5 and sym.isalpha() and sym not in ETF_BLACKLIST:
                symbols.append(sym)

    if symbols:
        return symbols[:5]

    # Fallback: all-caps tokens from headline
    noise = {
        'THE', 'FOR', 'AND', 'BUT', 'NOT', 'ARE', 'HAS', 'INC', 'LLC',
        'LTD', 'CEO', 'CFO', 'FDA', 'SEC', 'DOJ', 'IPO', 'USD', 'GDP',
        'ETF', 'NYSE', 'NASDAQ', 'AI', 'US', 'UK', 'EU', 'UN', 'NATO',
        'NEW', 'ITS', 'ALL', 'CAN', 'MAY', 'WILL', 'NOW', 'TWO', 'ONE',
    }
    tokens = re.findall(r'\b([A-Z]{2,5})\b', headline)
    for tok in tokens:
        if tok not in noise and tok not in ETF_BLACKLIST:
            symbols.append(tok)

    return list(dict.fromkeys(symbols))[:5]


def _fetch_news_feed() -> list:
    """Pull the last NEWS_LOOKBACK_MINUTES of general market news from Finnhub."""
    finnhub_key = os.getenv('FINNHUB_API_KEY', '')
    if not finnhub_key:
        print('  ⚠️  No FINNHUB_API_KEY set')
        return []
    try:
        resp = requests.get(
            'https://finnhub.io/api/v1/news',
            params={'category': 'general', 'token': finnhub_key},
            timeout=10
        )
        if resp.status_code != 200:
            print(f'  ⚠️  Finnhub news error: {resp.status_code}')
            return []

        raw = resp.json() or []
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=NEWS_LOOKBACK_MINUTES)
        articles = []

        for item in raw:
            ts = item.get('datetime', 0)
            pub_dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else datetime.now(timezone.utc)
            if pub_dt < cutoff:
                continue

            headline = item.get('headline', '') or ''
            symbols  = _extract_symbols(headline, item.get('related', ''))

            articles.append({
                'headline':   headline,
                'symbols':    symbols,
                'url':        item.get('url', ''),
                'created_at': pub_dt.strftime('%Y-%m-%dT%H:%M:%SZ'),
            })

        print(f'  📰 Fetched {len(articles)} articles from Finnhub (last {NEWS_LOOKBACK_MINUTES}min)')
        return articles

    except Exception as e:
        print(f'  ⚠️  Finnhub news feed failed: {e}')
        return []


# ---------------------------------------------------------------------------
# yfinance — price/volume snapshot
# ---------------------------------------------------------------------------
def _fetch_snapshots(tickers: list) -> dict:
    """
    Fetch current price + daily change% for a list of tickers via yfinance.
    Returns {ticker: {current_price, price_change_pct, volume, volume_ratio, prev_close}}
    """
    if not tickers:
        return {}
    try:
        import yfinance as yf

        result = {}
        batch = ' '.join(tickers)
        data  = yf.download(
            batch,
            period='2d',
            interval='1d',
            group_by='ticker',
            auto_adjust=True,
            progress=False,
            threads=True,
        )

        for ticker in tickers:
            try:
                df = data[ticker] if len(tickers) > 1 else data
                if df is None or df.empty:
                    continue
                rows = df.dropna(subset=['Close'])
                if len(rows) < 1:
                    continue

                curr_price = float(rows['Close'].iloc[-1])
                prev_close = float(rows['Close'].iloc[-2]) if len(rows) >= 2 else curr_price
                today_vol  = float(rows['Volume'].iloc[-1]) if 'Volume' in rows.columns else 0
                prev_vol   = float(rows['Volume'].iloc[-2]) if ('Volume' in rows.columns and len(rows) >= 2) else 0

                pct_change = round((curr_price - prev_close) / prev_close * 100, 2) if prev_close > 0 else 0.0
                vol_ratio  = round(today_vol / prev_vol, 2) if prev_vol > 0 else 1.0

                result[ticker] = {
                    'current_price':    round(curr_price, 4),
                    'price_change_pct': pct_change,
                    'volume':           today_vol,
                    'volume_ratio':     vol_ratio,
                    'prev_close':       round(prev_close, 4),
                }
            except Exception:
                continue

        print(f'  📈 Snapshots fetched for {len(result)}/{len(tickers)} tickers')
        return result

    except Exception as e:
        print(f'  ⚠️  yfinance snapshot fetch failed: {e}')
        return {}


# ---------------------------------------------------------------------------
# Core scan logic (unchanged structure, updated sources)
# ---------------------------------------------------------------------------
def _news_scan(supabase) -> int:
    """Pull Finnhub news, match T1/T2 catalysts, store new entries. Returns count written."""
    articles = _fetch_news_feed()
    if not articles:
        print('  ⚠️  No catalyst-matching news found')
        return 0

    ticker_map = {}

    for article in articles:
        headline = article.get('headline', '') or ''
        symbols  = article.get('symbols', []) or []
        url      = article.get('url', '') or ''
        pub_time = article.get('created_at', _ts_now())

        if not headline or not symbols:
            continue
        if len(symbols) > 3:
            continue  # sector roundup

        tier, direction, matched_kw = _tier_match(headline, len(symbols))
        if tier is None:
            continue

        for sym in symbols:
            if not sym or len(sym) > 5 or not sym.isalpha():
                continue
            if sym in ETF_BLACKLIST:
                continue

            existing = ticker_map.get(sym)
            if existing is None or tier < existing['tier']:
                ticker_map[sym] = {
                    'ticker':          sym.upper(),
                    'headline':        headline[:200],
                    'news_url':        url,
                    'tier':            tier,
                    'direction':       direction,
                    'matched_keyword': matched_kw,
                    'catalyst_at':     pub_time,
                }

    if not ticker_map:
        print('  ⚠️  No catalyst-matching news found')
        return 0

    snapshots  = _fetch_snapshots(list(ticker_map.keys()))
    now_str    = _ts_now()
    expires_at = (datetime.now() + timedelta(hours=WATCHLIST_TTL_HOURS)).strftime('%Y-%m-%dT%H:%M:%S')
    written    = 0

    for sym, rec in ticker_map.items():
        base_score = {1: 75, 2: 50}.get(rec['tier'], 35)
        snap = snapshots.get(sym, {})

        row = {
            'ticker':            rec['ticker'],
            'headline':          rec['headline'],
            'news_url':          rec['news_url'],
            'tier':              rec['tier'],
            'direction':         rec['direction'],
            'matched_keyword':   rec['matched_keyword'],
            'base_score':        base_score,
            'catalyst_at':       rec['catalyst_at'],
            'found_at':          now_str,
            'expires_at':        expires_at,
            'discovery_price':   snap.get('current_price', 0),
            'current_price':     snap.get('current_price', 0),
            'price_change_pct':  snap.get('price_change_pct', 0),
            'volume':            snap.get('volume', 0),
            'volume_ratio':      snap.get('volume_ratio', 0),
            'scanner_qualified': False,
            'last_enriched_at':  now_str,
        }

        try:
            existing = supabase.client.table('catalyst_watchlist') \
                .select('id, tier') \
                .eq('ticker', rec['ticker']) \
                .gte('expires_at', now_str) \
                .order('tier') \
                .limit(1) \
                .execute()

            if existing.data:
                existing_tier = existing.data[0]['tier']
                if rec['tier'] <= existing_tier:
                    supabase.client.table('catalyst_watchlist') \
                        .update({
                            'expires_at':      expires_at,
                            'headline':        rec['headline'],
                            'tier':            rec['tier'],
                            'base_score':      base_score,
                            'matched_keyword': rec['matched_keyword'],
                        }) \
                        .eq('id', existing.data[0]['id']) \
                        .execute()
                    print(f'    ↻  {rec["ticker"]} refreshed (tier {rec["tier"]})')
            else:
                supabase.client.table('catalyst_watchlist').insert(row).execute()
                price_str = f'${snap.get("current_price", 0):.2f}' if snap.get('current_price') else 'no price'
                print(f'    ✅ {rec["ticker"]} tier {rec["tier"]} {rec["direction"].upper()} ({rec["matched_keyword"]}) {price_str}')
                written += 1

        except Exception as e:
            print(f'    ❌ Failed to write {sym}: {e}')

    # Enforce MAX_FEED_ENTRIES
    try:
        active = supabase.client.table('catalyst_watchlist') \
            .select('id') \
            .gte('expires_at', now_str) \
            .order('tier') \
            .order('found_at', desc=True) \
            .execute()

        all_ids = [r['id'] for r in (active.data or [])]
        if len(all_ids) > MAX_FEED_ENTRIES:
            ids_to_drop = all_ids[MAX_FEED_ENTRIES:]
            supabase.client.table('catalyst_watchlist') \
                .delete() \
                .in_('id', ids_to_drop) \
                .execute()
            print(f'  🧹 Trimmed to {MAX_FEED_ENTRIES} entries')
    except Exception as e:
        print(f'  ⚠️  Feed trim failed: {e}')

    print(f'  📊 News scan done — {written} new entries')
    return written


def _price_enrich(supabase,
                  min_change_pct=QUALIFY_MIN_CHANGE_PCT,
                  min_volume_ratio=QUALIFY_MIN_VOLUME_RATIO):
    """
    Batch-fetch current price/volume for all active catalyst entries via yfinance.
    Updates current_price, price_change_pct, volume_ratio, scanner_qualified.
    """
    try:
        now_str = _ts_now()
        active = supabase.client.table('catalyst_watchlist') \
            .select('id, ticker, direction, discovery_price') \
            .gte('expires_at', now_str) \
            .execute()

        entries = active.data or []
        if not entries:
            print('  ℹ️  No active entries to enrich')
            return

        tickers = list({e['ticker'] for e in entries})
        print(f'  📈 Enriching {len(tickers)} active catalyst tickers...')

        snapshots = _fetch_snapshots(tickers)
        if not snapshots:
            return

        qualified_count = 0
        for entry in entries:
            ticker    = entry['ticker']
            snap      = snapshots.get(ticker)
            if not snap:
                continue

            price_pct = snap['price_change_pct']
            vol_ratio = snap['volume_ratio']
            direction = entry['direction']

            move_qualifies = (
                (direction == 'long'  and price_pct >=  min_change_pct) or
                (direction == 'short' and price_pct <= -min_change_pct)
            )
            qualified = move_qualifies and vol_ratio >= min_volume_ratio
            if qualified:
                qualified_count += 1

            try:
                supabase.client.table('catalyst_watchlist') \
                    .update({
                        'current_price':     snap['current_price'],
                        'price_change_pct':  price_pct,
                        'volume':            snap['volume'],
                        'volume_ratio':      vol_ratio,
                        'scanner_qualified': qualified,
                        'last_enriched_at':  now_str,
                    }) \
                    .eq('id', entry['id']) \
                    .execute()
            except Exception as e:
                print(f'    ⚠️  Enrich update failed for {ticker}: {e}')

        print(f'  ✅ Price enrich done — {qualified_count} entries now scanner-qualified')

    except Exception as e:
        print(f'  ❌ Price enrichment failed: {e}')


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------
def run_news_scan(supabase) -> int:
    """Public: run one full news scan + price enrichment cycle."""
    print(f'\n🔍 Catalyst scan — {datetime.now().strftime("%H:%M:%S")}')
    written = _news_scan(supabase)
    _price_enrich(supabase)
    return written


def start_news_scanner(supabase):
    """Launch background scanner. Runs immediately then every 15 min."""
    def _loop():
        try:
            run_news_scan(supabase)
        except Exception as e:
            print(f'❌ Initial catalyst scan failed: {e}')
        while True:
            time.sleep(SCAN_INTERVAL)
            try:
                run_news_scan(supabase)
            except Exception as e:
                print(f'❌ Scheduled catalyst scan failed: {e}')

    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print('✅ News catalyst scanner started (every 15 min, max 200 entries)')
    return t
