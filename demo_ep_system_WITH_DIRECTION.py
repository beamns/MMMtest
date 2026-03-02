"""
EP Scanner - Polygon.io edition
Movers via Polygon snapshots, news via Polygon /v2/reference/news.
News fetched for top 50 movers in parallel (15 workers, 2s timeout each) to stay well under gunicorn's 120s limit.
"""

import os
import re
import requests
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed


class AlpacaDataProvider:
    """Scanner using Polygon.io for all market data"""

    POLY_BASE = 'https://api.polygon.io'

    def __init__(self):
        self.api_key = os.getenv('POLYGON_API_KEY', '')
        if not self.api_key:
            print("⚠️  No POLYGON_API_KEY found")
        else:
            print("✅ Scanner ready - Polygon.io")

        # Compat shims (some routes in app.py reference these)
        self.base_url = ''
        self.data_url = ''
        self.headers  = {}

        # Simple in-process news cache: ticker -> (timestamp, articles)
        self._news_cache = {}
        self._NEWS_TTL   = 300  # seconds

    # ── Polygon helper ────────────────────────────────────────────────────────

    def _poly(self, path, params=None, timeout=8):
        p = dict(params or {})
        p['apiKey'] = self.api_key
        try:
            return requests.get(f"{self.POLY_BASE}{path}", params=p, timeout=timeout)
        except Exception as e:
            print(f"⚠️ Polygon {path}: {e}")
            return None

    # ── Movers ────────────────────────────────────────────────────────────────

    def _get_movers(self, side, min_change, min_price, filter_direction):
        """Fetch gainers or losers from Polygon snapshot endpoint"""
        r = self._poly(f'/v2/snapshot/locale/us/markets/stocks/{side}',
                       params={'include_otc': 'false'})
        if not r or r.status_code != 200:
            print(f"  Polygon {side} error: {r.status_code if r else 'timeout'}")
            return []

        results = []
        for item in r.json().get('tickers', [])[:50]:
            ticker = item.get('ticker', '')
            day    = item.get('day', {})
            prev   = item.get('prevDay', {})

            price      = float(item.get('lastTrade', {}).get('p', 0) or day.get('c', 0) or 0)
            prev_close = float(prev.get('c', 0) or 0)
            if not price or not prev_close:
                continue

            pct = round((price - prev_close) / prev_close * 100, 2)

            if filter_direction == 'gainers' and pct < min_change:
                continue
            if filter_direction == 'losers'  and pct > -min_change:
                continue
            if filter_direction == 'both'    and abs(pct) < min_change:
                continue
            if price < min_price:
                continue

            results.append({
                'ticker':           ticker,
                'price':            round(price, 2),
                'percent_change':   pct,
                'catalyst':         'Price action',
                'news_url':         '',
                'has_news':         False,
                'has_exact_mention': False,
            })
            print(f"  {ticker:6s} {'UP' if pct > 0 else 'DOWN':4s} {pct:+6.1f}% | ${price:7.2f}")

        return results

    def get_top_gappers(self, min_gap_pct=15.0, min_price=0.5, direction='both'):
        """Main entry point: movers + parallel news for top 15 only"""
        print(f"\n🔍 SCANNING:")
        print(f"   • Min change: {min_gap_pct}%")
        print(f"   • Min price: ${min_price}")
        print(f"   • Direction: {direction}")

        all_movers = []

        print("Fetching GAINERS...")
        all_movers.extend(self._get_movers('gainers', min_gap_pct, min_price, direction))
        print(f"  Found {len(all_movers)} gainers (filtered)")

        print("Fetching LOSERS...")
        losers = self._get_movers('losers', min_gap_pct, min_price, direction)
        all_movers.extend(losers)
        print(f"  Found {len(losers)} losers (filtered)")

        if not all_movers:
            print("\n❌ No movers found")
            return []

        # Deduplicate
        seen, unique = set(), []
        for m in all_movers:
            if m['ticker'] not in seen:
                seen.add(m['ticker'])
                unique.append(m)
        all_movers = unique

        total = len(all_movers)
        print(f"\n✅ Found {total} movers")
        print("Fetching news (optional bonus)...\n")

        # ── News: top 50 by abs move, in parallel, 2s timeout each ──────────
        top50      = sorted(all_movers, key=lambda x: abs(x['percent_change']), reverse=True)[:50]
        ticker_set = {m['ticker'] for m in top50}

        def fetch_news(mover):
            ticker   = mover['ticker']
            articles = self.get_recent_news(ticker, hours=48)
            if articles:
                exact  = [a for a in articles if self._has_exact_ticker_mention(a, ticker)]
                source = exact if exact else articles
                mover['catalyst']          = source[0]['headline'][:150]
                mover['news_url']          = source[0].get('url', '')
                mover['has_news']          = bool(exact)
                mover['has_exact_mention'] = bool(exact)
                label = "✅" if exact else "≈"
                count = len(articles)
                print(f"  {label} {ticker:6s} - {'EXACT' if exact else f'Related only ({count} articles)'}")
            else:
                print(f"  — {ticker:6s} - No news")
            return mover

        # Run top-15 news fetches in parallel (max 8 workers)
        with ThreadPoolExecutor(max_workers=15) as ex:
            futs = {ex.submit(fetch_news, m): m for m in top50}
            for f in as_completed(futs):
                f.result()  # updates mover in-place

        # Print remainder as no-news (skip fetching to save time)
        rest_count = 0
        for m in all_movers:
            if m['ticker'] not in ticker_set:
                rest_count += 1

        if rest_count:
            print(f"  (skipped news for {rest_count} lower-ranked movers)")

        news_count = len([m for m in all_movers if m.get('has_news', False)])
        print(f"\n✅ Complete: {total} movers ({news_count} with news)\n")
        return all_movers

    # ── News ──────────────────────────────────────────────────────────────────

    def _has_exact_ticker_mention(self, news_item, ticker):
        headline = news_item.get('headline', '').upper()
        summary  = news_item.get('summary',  '').upper()
        pattern  = r'\b' + re.escape(ticker.upper()) + r'\b'
        return bool(re.search(pattern, headline) or re.search(pattern, summary))

    def get_recent_news(self, ticker, hours=48):
        """Polygon /v2/reference/news with in-process cache"""
        now = datetime.now(timezone.utc)

        cached = self._news_cache.get(ticker)
        if cached:
            ts, articles = cached
            if (now.timestamp() - ts) < self._NEWS_TTL:
                return articles

        try:
            pub_after = (now - timedelta(hours=hours)).strftime('%Y-%m-%dT%H:%M:%SZ')
            r = self._poly('/v2/reference/news', params={
                'ticker':            ticker,
                'published_utc.gte': pub_after,
                'order':             'desc',
                'limit':             10,
                'sort':              'published_utc',
            }, timeout=2)

            if not r or r.status_code != 200:
                self._news_cache[ticker] = (now.timestamp(), [])
                return []

            formatted = []
            for item in r.json().get('results', []):
                headline = item.get('title', '')
                if not headline:
                    continue
                formatted.append({
                    'headline':     headline,
                    'summary':      item.get('description', ''),
                    'url':          item.get('article_url', ''),
                    'publish_time': item.get('published_utc', ''),
                    'symbols':      [t.get('ticker', '') for t in item.get('tickers', [])]
                })

            self._news_cache[ticker] = (now.timestamp(), formatted)
            return formatted

        except Exception as e:
            print(f"⚠️ news {ticker}: {e}")
            self._news_cache[ticker] = (now.timestamp(), [])
            return []

    # ── Market status ─────────────────────────────────────────────────────────

    def is_market_open(self):
        try:
            r = self._poly('/v1/marketstatus/now')
            if r and r.status_code == 200:
                return r.json().get('market') == 'open'
        except Exception:
            pass
        return False

    def get_market_status(self):
        try:
            r = self._poly('/v1/marketstatus/now')
            if r and r.status_code == 200:
                return {'is_open': r.json().get('market') == 'open'}
        except Exception:
            pass
        return {'is_open': False}

    # ── After-hours movers ────────────────────────────────────────────────────

    def get_after_hours_movers(self, min_gap_pct=5.0, min_price=1.0):
        try:
            print("📡 Fetching today's movers for after-hours analysis...")
            candidates = {}
            for side in ['gainers', 'losers']:
                r = self._poly(f'/v2/snapshot/locale/us/markets/stocks/{side}',
                               params={'include_otc': 'false'})
                if r and r.status_code == 200:
                    for item in r.json().get('tickers', [])[:50]:
                        sym   = item.get('ticker', '')
                        price = float(item.get('lastTrade', {}).get('p', 0) or
                                      item.get('day', {}).get('c', 0) or 0)
                        if sym and price >= min_price:
                            candidates[sym] = item

            if not candidates:
                print("⚠️  No candidates found")
                return []

            symbols = list(candidates.keys())
            print(f"📊 Processing {len(symbols)} symbols for AH data...")

            movers = []
            for i in range(0, len(symbols), 100):
                batch = symbols[i:i + 100]
                r = self._poly('/v2/snapshot/locale/us/markets/stocks/tickers',
                               params={'tickers': ','.join(batch)})
                if not r or r.status_code != 200:
                    continue
                for snap in r.json().get('tickers', []):
                    try:
                        sym         = snap.get('ticker', '')
                        day         = snap.get('day', {})
                        prev_day    = snap.get('prevDay', {})
                        last_trade  = snap.get('lastTrade', {})
                        today_close = float(day.get('c', 0) or 0)
                        prev_close  = float(prev_day.get('c', 0) or 0)
                        ah_price    = float(last_trade.get('p', 0) or 0)
                        if not prev_close or not today_close:
                            continue
                        eod_gap     = (today_close - prev_close) / prev_close * 100
                        ah_move     = (ah_price - today_close) / today_close * 100 if ah_price else 0.0
                        current     = ah_price if ah_price else today_close
                        total       = (current - prev_close) / prev_close * 100
                        if abs(total) < min_gap_pct or current < min_price:
                            continue
                        direction   = "UP" if total > 0 else "DOWN"
                        catalyst    = (f"EOD gap {eod_gap:+.1f}% → AH {ah_move:+.1f}% ({direction})"
                                       if abs(ah_move) >= 1.0
                                       else f"EOD gap {eod_gap:+.1f}% (AH flat)")
                        movers.append({
                            'ticker':          sym,
                            'price':           round(current, 2),
                            'percent_change':  round(total, 2),
                            'eod_gap_pct':     round(eod_gap, 2),
                            'ah_move_pct':     round(ah_move, 2),
                            'prev_close':      round(prev_close, 2),
                            'today_close':     round(today_close, 2),
                            'catalyst':        catalyst,
                            'news_url':        '',
                            'has_news':        False,
                            'has_exact_mention': False,
                            'after_hours':     True,
                        })
                    except (ValueError, TypeError, KeyError):
                        continue

            movers.sort(key=lambda x: abs(x['percent_change']), reverse=True)
            print(f"✅ Found {len(movers)} after-hours gap candidates")

            for mover in movers[:15]:
                ticker = mover['ticker']
                news   = self.get_recent_news(ticker, hours=12)
                if news:
                    exact  = [n for n in news if self._has_exact_ticker_mention(n, ticker)]
                    source = exact if exact else news
                    mover['catalyst']          = source[0]['headline'][:150]
                    mover['news_url']          = source[0].get('url', '')
                    mover['has_news']          = bool(exact)
                    mover['has_exact_mention'] = bool(exact)
                    print(f"  {'✅' if exact else '≈'} {ticker:6s} {mover['percent_change']:+.1f}%")
                else:
                    print(f"  — {ticker:6s} {mover['percent_change']:+.1f}%")

            return movers

        except Exception as e:
            import traceback
            print(f"❌ After-hours scan error: {e}")
            traceback.print_exc()
            return []

    # ── Compat shims ──────────────────────────────────────────────────────────

    def get_stock_data(self, ticker, include_news=True):
        return {'ticker': ticker, 'current_price': 0, 'catalyst': 'Price action'}

    def get_high_volume_stocks(self, min_volume=1000000, min_price=1.0):
        return self.get_top_gappers(min_gap_pct=15.0, min_price=min_price)

    def scan_by_criteria(self, min_price=1.0, max_price=None, min_volume_ratio=1.0,
                         min_gap_pct=15.0, min_volume=1000000, scan_limit=200, direction='both'):
        return self.get_top_gappers(min_gap_pct=min_gap_pct, min_price=min_price, direction=direction)

    def get_current_price(self, ticker):
        return 0

    def get_earnings_info(self, ticker):
        return None


YFinanceDataProvider = AlpacaDataProvider


def create_data_provider():
    return AlpacaDataProvider()
