"""
Money Making Moves - Complete Backend with Trade Levels
"""

from flask import Flask, render_template, jsonify, request, session
from flask_cors import CORS
from datetime import datetime, timedelta
import os, sys, time

sys.path.append(os.path.dirname(__file__))
from demo_ep_system_WITH_DIRECTION import create_data_provider
from ep_watchlist_analyzer_DYNAMIC_THEMES import create_watchlist_analyzer
from hot_themes_tracker import HotThemesTracker, get_hot_themes_tracker
from cache_manager import get_cache_manager
# Auth enabled - database and Stripe are connected
from supabase_client import get_database
from stripe_client import get_stripe_client
from auth_manager import AuthManager
from activity_feed_generator import get_activity_generator
from news_catalyst_scanner import start_news_scanner
from functools import wraps
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

app = Flask(__name__)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable static file caching
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')

# Session persistence config
app.config.update(
    SESSION_COOKIE_SECURE=False,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Lax',
    SESSION_COOKIE_NAME='mmm_session',
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)

# Token helpers (replaces cookie sessions)
def generate_token(user_id: str) -> str:
    s = URLSafeTimedSerializer(app.secret_key)
    return s.dumps(user_id, salt='auth')

def verify_token(token: str, max_age=60*60*24*30):  # 30 days
    s = URLSafeTimedSerializer(app.secret_key)
    try:
        return s.loads(token, salt='auth', max_age=max_age)
    except (BadSignature, SignatureExpired):
        return None

def get_user_id_from_request():
    """Get user_id from Authorization header or session (backwards compat)"""
    auth = request.headers.get('Authorization', '')
    if auth.startswith('Bearer '):
        token = auth[7:]
        return verify_token(token)
    return session.get('user_id')  # fallback to cookie session

CORS(app, supports_credentials=True, origins=['https://moneymakingmoves.com', 'http://localhost:8080'])

# Initialize services
data_provider = create_data_provider()
watchlist_analyzer = create_watchlist_analyzer()

# Auth enabled - database and Stripe are connected
auth_manager = AuthManager()
supabase = auth_manager.db
stripe_client = auth_manager.stripe

# Start background news catalyst scanner
try:
    start_news_scanner(supabase)
except Exception as e:
    print(f'⚠️  News scanner failed to start: {e}')

def require_subscription(f):
    """Decorator: requires active subscription (active or trialing)"""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({'error': 'not_authenticated', 'message': 'Please log in'}), 401
        user = auth_manager.get_user(user_id)
        if not user or not user.get('is_subscribed'):
            return jsonify({'error': 'subscription_required', 'message': 'Pro subscription required'}), 403
        tier = user.get('subscription_tier', 'free')
        if tier not in ('rookie', 'pro'):
            return jsonify({'error': 'subscription_required', 'message': 'Pro subscription required'}), 403
        return f(*args, **kwargs)
    return decorated

def require_pro(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({'error': 'not_authenticated', 'message': 'Please log in'}), 401
        user = auth_manager.get_user(user_id)
        if not user or not user.get('is_subscribed'):
            return jsonify({'error': 'subscription_required', 'message': 'Pro subscription required'}), 403
        tier = user.get('subscription_tier', 'free')
        if tier != 'pro':
            return jsonify({'error': 'upgrade_required', 'message': 'Pro subscription required for this feature'}), 403
        return f(*args, **kwargs)
    return decorated

# Initialize hot themes tracker with database
hot_themes = HotThemesTracker(db=supabase)

def _refresh_themes_daily():
    """Background thread: refresh themes every 12 hours"""
    import time
    # Initial refresh on startup
    try:
        hot_themes.refresh_themes()
    except Exception as e:
        print(f"⚠️  Initial theme refresh failed: {e}")
    # Then every 12 hours
    while True:
        time.sleep(60 * 60 * 12)
        try:
            hot_themes.refresh_themes()
        except Exception as e:
            print(f"⚠️  Scheduled theme refresh failed: {e}")
cache = get_cache_manager()

# Initialize activity feed generator
activity_feed = get_activity_generator(db=supabase)

latest_scan_results = {
    'morning_gaps': [],
    'scan_time': None,
    'scan_stats': {}
}

# Background refresh state
_scan_in_progress = False
_last_scan_settings = None
_last_scan_time = None
_SCAN_CACHE_TTL = 300  # 5 minutes — serve cached if fresher than this

scanner_settings = {
    'min_change_pct': 10.0,
    'min_price': 1.0
}

def run_startup_scan():
    """Run one scan on startup to populate database cache — retries up to 3x"""
    global latest_scan_results

    # Wait for network to be ready after container start
    print("🚀 Startup scan: waiting 15s for network...")
    time.sleep(15)

    for attempt in range(3):
        try:
            print(f"🚀 Running startup scan (attempt {attempt+1}/3)...")

            movers = data_provider.get_top_gappers(
                min_gap_pct=10.0,
                min_price=1.0,
                direction='both'
            )

            if not movers:
                print(f"⚠️ Startup scan found no movers (attempt {attempt+1})")
                if attempt < 2:
                    time.sleep(30)
                    continue
                return

            all_analysis = watchlist_analyzer.analyze_for_watchlist(movers)
            score_lookup = {item['ticker']: item for item in all_analysis}

            gap_signals = []
            for mover in movers:
                ticker   = mover.get('ticker')
                ai_data  = score_lookup.get(ticker, {})
                ai_type  = ai_data.get('ai_type', 'N/A')
                ai_score = ai_data.get('score', 0)
                price    = mover.get('price', 0)
                trade_levels = calculate_trade_levels(ticker, price, ai_type, ai_score)
                gap_signals.append({
                    'ticker': ticker, 'ai_type': ai_type, 'price': price,
                    'price_change_pct': mover.get('percent_change', 0),
                    'catalyst': mover.get('catalyst', 'Price action'),
                    'news_url': mover.get('news_url', ''),
                    'has_news': mover.get('has_news', False),
                    'has_exact_mention': mover.get('has_exact_mention', False),
                    'ai_score': ai_score,
                    'ai_reason': ai_data.get('reason', ''),
                    'ai_recommendation': ai_data.get('recommendation', ''),
                    'trade_levels': trade_levels,
                    'stop_loss': trade_levels['stop_loss'],
                    'entry_price': trade_levels['entry_price'],
                    'signal_strength': 'Strong',
                    'risk_pct': 3.0
                })

            results = {
                'morning_gaps': gap_signals,
                'scan_time': datetime.now().isoformat(),
                'scan_stats': {
                    'gaps_found': len(gap_signals),
                    'with_scores': len([s for s in gap_signals if s['ai_score'] > 0]),
                    'high_scores': len([s for s in gap_signals if s['ai_score'] >= 80])
                }
            }
            latest_scan_results = results

            try:
                supabase.client.table('scan_results_cache').insert({
                    'scan_settings': '10.0_1.0_both',
                    'results': results,
                    'created_at': datetime.now().isoformat(),
                    'expires_at': (datetime.now() + timedelta(hours=24)).isoformat()
                }).execute()
                print(f"✅ Startup scan complete: {len(gap_signals)} stocks saved to database")
            except Exception as e:
                print(f"⚠️ Failed to save startup scan to database: {e}")

            return  # success

        except Exception as e:
            print(f"❌ Startup scan attempt {attempt+1} failed: {e}")
            import traceback
            traceback.print_exc()
            if attempt < 2:
                time.sleep(30)

# Run startup scan in background (don't block app startup)
import threading
threading.Thread(target=run_startup_scan, daemon=True).start()
threading.Thread(target=_refresh_themes_daily, daemon=True).start()

def calculate_trade_levels(ticker, price, ai_type, ai_score):
    """Calculate EP-specific entry, stop, and profit targets"""
    
    current_price = float(price)
    
    # EP-specific calculations
    if ai_type == "Growth EP":
        entry_price = current_price * 0.98
        stop_loss = current_price * 0.94
        target_1 = current_price * 1.10
        target_2 = current_price * 1.20
        target_3 = current_price * 1.35
        
    elif ai_type == "Story EP":
        entry_price = current_price * 1.02
        stop_loss = current_price * 0.92
        target_1 = current_price * 1.15
        target_2 = current_price * 1.30
        target_3 = current_price * 1.50
        
    elif ai_type == "Turnaround EP":
        entry_price = current_price * 0.97
        stop_loss = current_price * 0.90
        target_1 = current_price * 1.12
        target_2 = current_price * 1.25
        target_3 = current_price * 1.40
        
    elif ai_type == "Delayed Reaction EP":
        entry_price = current_price * 0.95
        stop_loss = current_price * 0.88
        target_1 = current_price * 1.15
        target_2 = current_price * 1.35
        target_3 = current_price * 1.60
        
    else:
        entry_price = current_price
        stop_loss = current_price * 0.95
        target_1 = current_price * 1.10
        target_2 = current_price * 1.20
        target_3 = current_price * 1.30
    
    # Adjust for score
    if ai_score >= 80:
        target_1 *= 1.05
        target_2 *= 1.10
        target_3 *= 1.15
    elif ai_score < 50:
        target_1 *= 0.95
        target_2 *= 0.90
        target_3 *= 0.85
    
    # Calculate metrics
    risk = entry_price - stop_loss
    reward_1 = target_1 - entry_price
    risk_reward_1 = reward_1 / risk if risk > 0 else 0
    
    return {
        'current_price': round(current_price, 2),
        'entry_price': round(entry_price, 2),
        'stop_loss': round(stop_loss, 2),
        'target_1': round(target_1, 2),
        'target_2': round(target_2, 2),
        'target_3': round(target_3, 2),
        'risk_amount': round(risk, 2),
        'reward_1': round(reward_1, 2),
        'risk_reward_ratio': round(risk_reward_1, 2),
        'stop_pct': round(((stop_loss - entry_price) / entry_price) * 100, 1),
        'target_1_pct': round(((target_1 - entry_price) / entry_price) * 100, 1),
        'target_2_pct': round(((target_2 - entry_price) / entry_price) * 100, 1),
        'target_3_pct': round(((target_3 - entry_price) / entry_price) * 100, 1)
    }

import time as _time
BUILD_VERSION = str(int(_time.time()))

@app.route('/')
def index():
    return render_template('index.html', build_version=BUILD_VERSION)

@app.route('/terms-of-use')
def terms_of_use():
    return render_template('terms_of_use.html', build_version=BUILD_VERSION)

@app.route('/privacy-policy')
def privacy_policy():
    return render_template('privacy_policy.html', build_version=BUILD_VERSION)

@app.route('/robots.txt')
def robots():
    """Serve robots.txt for SEO"""
    return app.send_static_file('robots.txt')

@app.route('/sitemap.xml')
def sitemap():
    """Serve sitemap.xml for SEO"""
    return app.send_static_file('sitemap.xml')

def _do_scan(min_change, min_price, direction, min_ai_score, require_ticker_news, include_after_hours):
    """Core scan logic — called directly or in background thread"""
    global latest_scan_results, _scan_in_progress, _last_scan_settings, _last_scan_time
    try:
        _scan_in_progress = True

        movers = data_provider.get_top_gappers(
            min_gap_pct=min_change,
            min_price=min_price,
            direction=direction
        )

        if include_after_hours and not data_provider.is_market_open():
            after_hours_movers = data_provider.get_after_hours_movers(
                min_gap_pct=min_change,
                min_price=min_price
            )
            movers.extend(after_hours_movers)

        seen = set()
        unique_movers = []
        for m in movers:
            t = m.get('ticker', '')
            if t and t not in seen:
                seen.add(t)
                unique_movers.append(m)
        movers = unique_movers

        if require_ticker_news:
            movers = [m for m in movers if m.get('has_exact_mention', False)]

        all_analysis = watchlist_analyzer.analyze_for_watchlist(movers)
        score_lookup = {item['ticker']: item for item in all_analysis}

        gap_signals = []
        for mover in movers:
            ticker = mover.get('ticker')
            ai_data = score_lookup.get(ticker, {})
            ai_type = ai_data.get('ai_type', 'N/A')
            ai_score = ai_data.get('score', 0)

            if ai_score < min_ai_score:
                continue

            price = mover.get('price', 0)
            trade_levels = calculate_trade_levels(ticker, price, ai_type, ai_score)

            signal = {
                'ticker': ticker,
                'ai_type': ai_type,
                'direction': ai_data.get('direction', 'long'),
                'price': price,
                'gap_pct': mover.get('percent_change', 0),
                'price_change_pct': mover.get('percent_change', 0),
                'catalyst': mover.get('catalyst', 'Price action'),
                'news_url': mover.get('news_url', ''),
                'has_news': mover.get('has_news', False),
                'has_exact_mention': mover.get('has_exact_mention', False),
                'stop': trade_levels['stop_loss'],
                'stop_loss': trade_levels['stop_loss'],
                'signal_strength': 'Strong',
                'risk_pct': 3.0,
                'entry_price': trade_levels['entry_price'],
                'ai_score': ai_score,
                'ai_reason': ai_data.get('reason', ''),
                'ai_recommendation': ai_data.get('recommendation', ''),
                'trade_levels': trade_levels,
                'volume_ratio': mover.get('volume_ratio', 1.0),
                'volume': mover.get('volume', 0),
            }
            if 'eod_gap_pct' in mover:
                signal['eod_gap_pct'] = mover['eod_gap_pct']
            if 'ah_move_pct' in mover:
                signal['ah_move_pct'] = mover['ah_move_pct']
            gap_signals.append(signal)

        results = {
            'morning_gaps': gap_signals,
            'ep_9m': [],
            'delayed_reactions': [],
            'sugar_babies': [],
            'story_themes': [],
            'scan_time': datetime.now().isoformat(),
            'scan_stats': {
                'gaps_scanned': 100,
                'gaps_found': len(gap_signals),
                'with_scores': len([s for s in gap_signals if s['ai_score'] > 0]),
                'high_scores': len([s for s in gap_signals if s['ai_score'] >= 80])
            }
        }

        latest_scan_results = results
        _last_scan_settings = f"{min_change}_{min_price}_{direction}_{min_ai_score}_{require_ticker_news}_{include_after_hours}"
        _last_scan_time = datetime.now()

        # Save to DB only if results differ meaningfully (skip redundant writes)
        try:
            settings_key = f"{min_change}_{min_price}_{direction}"
            # Check if we already saved identical settings recently
            recent = supabase.client.table('scan_results_cache')                .select('created_at')                .eq('scan_settings', settings_key)                .order('created_at', desc=True)                .limit(1)                .execute()
            last_saved = None
            if recent.data:
                last_saved = datetime.fromisoformat(recent.data[0]['created_at'].replace('Z',''))
            
            if not last_saved or (datetime.now() - last_saved).seconds > 240:
                supabase.client.table('scan_results_cache').insert({
                    'scan_settings': settings_key,
                    'results': results,
                    'created_at': datetime.now().isoformat(),
                    'expires_at': (datetime.now() + timedelta(hours=24)).isoformat()
                }).execute()
        except Exception as e:
            print(f"⚠️ DB save failed: {e}")

        return results
    except Exception as e:
        print(f"❌ Scan error: {e}")
        return None
    finally:
        _scan_in_progress = False

@app.route('/api/scan', methods=['POST'])
def run_scan():
    global latest_scan_results, _scan_in_progress, _last_scan_settings, _last_scan_time
    
    try:
        data = request.json or {}
        min_change = float(data.get('min_change_pct', 10))
        min_price = float(data.get('min_price', 1.0))
        direction = str(data.get('direction', 'both'))
        min_ai_score = int(data.get('min_ai_score', 0))
        require_ticker_news = bool(data.get('require_ticker_news', False))
        include_after_hours = bool(data.get('include_after_hours', False))

        settings_key = f"{min_change}_{min_price}_{direction}_{min_ai_score}_{require_ticker_news}_{include_after_hours}"

        # Serve cached results if fresh enough, kick off background refresh
        if (latest_scan_results.get('morning_gaps') and
                _last_scan_time and
                _last_scan_settings == settings_key and
                (datetime.now() - _last_scan_time).seconds < _SCAN_CACHE_TTL):

            if not _scan_in_progress:
                threading.Thread(
                    target=_do_scan,
                    args=(min_change, min_price, direction, min_ai_score, require_ticker_news, include_after_hours),
                    daemon=True
                ).start()

            results = latest_scan_results
        else:
            # No fresh cache — run scan synchronously so user gets results
            results = _do_scan(min_change, min_price, direction, min_ai_score, require_ticker_news, include_after_hours)
            if not results:
                return jsonify({'success': False, 'error': 'Scan failed'}), 500

        # Gate EOD/AH data behind Pro (work on a copy so cache stays intact)
        import copy
        safe_results = copy.deepcopy(results)
        user_id = get_user_id_from_request()
        is_pro = False
        if user_id:
            user = auth_manager.get_user(user_id)
            is_pro = bool(user and user.get('is_subscribed'))
        if not is_pro:
            for s in safe_results['morning_gaps']:
                s.pop('eod_gap_pct', None)
                s.pop('ah_move_pct', None)

        return jsonify({
            'success': True,
            'results': safe_results,
            'total_signals': len(safe_results['morning_gaps']),
            'scan_stats': safe_results['scan_stats'],
            'is_pro': is_pro,
            'from_cache': _last_scan_settings == settings_key and (datetime.now() - _last_scan_time).seconds < _SCAN_CACHE_TTL if _last_scan_time else False
        })

    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/analyze/<ticker>')
def analyze_ticker(ticker):
    """Fetch live data + run AI scoring for any ticker on demand"""
    try:
        import requests as req
        from datetime import timezone
        ticker   = ticker.upper().strip()
        poly_key = os.getenv('POLYGON_API_KEY', '')

        r    = req.get(f'https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}',
                       params={'apiKey': poly_key}, timeout=6)
        snap = r.json().get('ticker', {}) if r.status_code == 200 else {}
        day        = snap.get('day', {})
        prev       = snap.get('prevDay', {})
        price      = float(snap.get('lastTrade', {}).get('p', 0) or day.get('c', 0) or 0)
        prev_close = float(prev.get('c', 0) or 0)
        pct_change = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0.0
        volume     = int(day.get('v', 0) or 0)
        prev_vol   = int(prev.get('v', 0) or volume or 1)
        vol_ratio  = round(volume / prev_vol, 1) if prev_vol else 1.0

        catalyst = 'Price action'
        has_news = has_exact = False
        news_url = ''
        try:
            now       = datetime.now(timezone.utc)
            pub_after = (now - timedelta(days=3)).strftime('%Y-%m-%dT%H:%M:%SZ')
            nr = req.get('https://api.polygon.io/v2/reference/news',
                         params={'ticker': ticker, 'published_utc.gte': pub_after,
                                 'order': 'desc', 'limit': 5, 'sort': 'published_utc',
                                 'apiKey': poly_key}, timeout=4)
            if nr.status_code == 200:
                articles = nr.json().get('results', [])
                if articles:
                    headline = articles[0].get('title', '')
                    if headline:
                        catalyst  = headline[:120]
                        has_news  = True
                        has_exact = ticker.lower() in headline.lower()
                        news_url  = articles[0].get('article_url', '')
        except Exception as e:
            print(f"⚠️ Polygon news {ticker}: {e}")

        if not has_news:
            try:
                import yfinance as yf
                yf_news = yf.Ticker(ticker).news or []
                if yf_news:
                    content_  = yf_news[0].get('content', {})
                    headline  = content_.get('title', '') or yf_news[0].get('title', '')
                    if headline:
                        catalyst  = headline[:120]
                        has_news  = True
                        has_exact = ticker.lower() in headline.lower()
                        news_url  = (content_.get('canonicalUrl', {}).get('url', '')
                                     or yf_news[0].get('link', ''))
            except Exception as e:
                print(f"⚠️ yfinance news fallback {ticker}: {e}")

        mover = {
            'ticker': ticker, 'price': price, 'percent_change': pct_change,
            'volume': volume, 'volume_ratio': vol_ratio, 'catalyst': catalyst,
            'has_news': has_news, 'has_exact_mention': has_exact, 'news_url': news_url,
        }
        analysis = watchlist_analyzer.analyze_for_watchlist([mover])
        ai_data  = analysis[0] if analysis else {}

        return jsonify({
            'success': True, 'ticker': ticker,
            'price': round(price, 2), 'pct_change': round(pct_change, 2),
            'volume_ratio': vol_ratio, 'catalyst': catalyst, 'news_url': news_url,
            'ai_score': ai_data.get('score', 0), 'ai_type': ai_data.get('ep_type', ''),
            'ai_reason': ai_data.get('reason', ''),
            'ai_recommendation': ai_data.get('recommendation', ''),
            'direction': ai_data.get('direction', 'long'),
        })
    except Exception as e:
        print(f"❌ analyze_ticker error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/quote/<ticker>')
def get_quote(ticker):
    """Live price quote via Polygon snapshot"""
    try:
        import requests as req
        ticker   = ticker.upper().strip()
        poly_key = os.getenv('POLYGON_API_KEY', '')
        r = req.get(f'https://api.polygon.io/v2/snapshot/locale/us/markets/stocks/tickers/{ticker}',
                    params={'apiKey': poly_key}, timeout=6)
        if r.status_code != 200:
            return jsonify({'success': False, 'error': 'Quote fetch failed'}), 500
        snap     = r.json().get('ticker', {})
        day      = snap.get('day', {})
        prev_day = snap.get('prevDay', {})
        current  = float(snap.get('lastTrade', {}).get('p', 0) or day.get('c', 0) or 0)
        open_p   = float(day.get('o', 0) or 0)
        close_p  = float(prev_day.get('c', 0) or 0)
        day_high = float(day.get('h', 0) or 0)
        day_low  = float(day.get('l', 0) or 0)
        pct_change = round((current - close_p) / close_p * 100, 2) if close_p else 0
        return jsonify({
            'success': True, 'ticker': ticker,
            'current':    round(current,  2) if current  else None,
            'open':       round(open_p,   2) if open_p   else None,
            'close':      round(close_p,  2) if close_p  else None,
            'day_high':   round(day_high, 2) if day_high else None,
            'day_low':    round(day_low,  2) if day_low  else None,
            'pct_change': pct_change, 'market_state': 'REGULAR',
            'post_price': None, 'post_change': None, 'post_pct': None,
            'pre_price':  None, 'pre_change':  None, 'pre_pct':  None,
        })
    except Exception as e:
        print(f'Quote error {ticker}: {e}')
        return jsonify({'success': False, 'error': str(e)}), 500
@app.route('/api/company/<ticker>')
def get_company_profile(ticker):
    """Company profile via Polygon /v3/reference/tickers"""
    try:
        import requests as req
        ticker   = ticker.upper().strip()
        poly_key = os.getenv('POLYGON_API_KEY', '')
        r = req.get(f'https://api.polygon.io/v3/reference/tickers/{ticker}',
                    params={'apiKey': poly_key}, timeout=6)
        p = r.json().get('results', {}) if r.status_code == 200 else {}
        market_cap = float(p.get('market_cap') or 0)
        if market_cap >= 1_000_000_000:
            cap_str = f"${market_cap/1_000_000_000:.1f}B"
        elif market_cap >= 1_000_000:
            cap_str = f"${market_cap/1_000_000:.0f}M"
        else:
            cap_str = "N/A"
        desc = (p.get('description', '') or '')[:400]
        if len(desc) == 400:
            desc = desc.rsplit('.', 1)[0] + '.'
        return jsonify({
            'success': True,
            'profile': {
                'name':        p.get('name') or ticker,
                'sector':      p.get('sic_description') or 'N/A',
                'industry':    p.get('sic_description') or 'N/A',
                'description': desc or 'No description available.',
                'market_cap':  cap_str,
                'employees':   str(p.get('total_employees') or 'N/A'),
                'country':     p.get('locale', 'us').upper(),
                'website':     p.get('homepage_url') or '',
            }
        })
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/news/<ticker>')
@require_subscription
def get_news(ticker):
    try:
        limit = int(request.args.get('limit', 15))
        hours = int(request.args.get('hours', 48))
        
        news = data_provider.get_recent_news(ticker, hours=hours)
        
        return jsonify({
            'success': True,
            'ticker': ticker,
            'news': news[:limit]
        })
        
    except Exception as e:
        print(f"❌ Error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/market/status')
def get_market_status():
    try:
        return jsonify(data_provider.get_market_status())
    except:
        return jsonify({'is_open': False})

@app.route('/api/market/pulse')
def get_market_pulse():
    """ES/NQ futures + VIX — yfinance download primary, Polygon backup"""
    try:
        import yfinance as yf
        import requests as req
        from concurrent.futures import ThreadPoolExecutor

        def yf_fetch(sym):
            try:
                df = yf.download(sym, period='2d', interval='1d',
                                 progress=False, auto_adjust=True)
                if df is None or len(df) == 0:
                    return None, None
                close_col = df['Close']
                def to_float(val):
                    if hasattr(val, 'item'):   return float(val.item())
                    if hasattr(val, 'iloc'):   return float(val.iloc[0])
                    return float(val)
                if len(df) >= 2:
                    price = to_float(close_col.iloc[-1])
                    prev  = to_float(close_col.iloc[-2])
                    return round(price, 2), round((price - prev) / prev * 100, 2) if prev else 0.0
                else:
                    return round(to_float(close_col.iloc[-1]), 2), 0.0
            except Exception as e:
                print(f"⚠️ yf_fetch {sym}: {e}")
            return None, None

        SYMBOLS = ['ES=F', 'NQ=F', '^VIX']
        results = {}
        with ThreadPoolExecutor(max_workers=3) as ex:
            futs = {ex.submit(yf_fetch, sym): sym for sym in SYMBOLS}
            for f, sym in futs.items():
                price, pct = f.result()
                results[sym] = {'price': price or 0.0, 'pct': pct or 0.0}

        poly_key = os.getenv('POLYGON_API_KEY', '')
        poly_map = {'ES=F': 'I:SPX', 'NQ=F': 'I:NDX', '^VIX': 'I:VIX'}
        for sym, v in results.items():
            if v['price'] == 0 and poly_key:
                try:
                    r = req.get(
                        f'https://api.polygon.io/v2/snapshot/locale/us/markets/indices/tickers/{poly_map[sym]}',
                        params={'apiKey': poly_key}, timeout=5)
                    if r.status_code == 200:
                        session = r.json().get('results', {}).get('session', {})
                        price   = float(session.get('close', 0) or 0)
                        prev    = float(session.get('previous_close', 0) or price)
                        if price > 0:
                            results[sym] = {
                                'price': round(price, 2),
                                'pct':   round((price - prev) / prev * 100, 2) if prev else 0.0
                            }
                            print(f"📊 Pulse Polygon fallback: {sym}={price}")
                except Exception as e:
                    print(f"⚠️ Polygon pulse {sym}: {e}")

        es_pct  = results.get('ES=F', {}).get('pct', 0)
        nq_pct  = results.get('NQ=F', {}).get('pct', 0)
        vix     = results.get('^VIX', {}).get('price', 20)
        vix_pct = results.get('^VIX', {}).get('pct', 0)

        score = 0
        if es_pct > 0.3:    score += 1
        elif es_pct < -0.3: score -= 1
        if nq_pct > 0.3:    score += 1
        elif nq_pct < -0.3: score -= 1
        if vix < 18:        score += 1
        elif vix > 22:      score -= 1
        if vix_pct < -3:    score += 1
        elif vix_pct > 3:   score -= 1

        if score >= 2:
            label, color, icon = 'BULL', 'green', 'fa-arrow-trend-up'
        elif score <= -2:
            label, color, icon = 'BEAR', 'red', 'fa-arrow-trend-down'
        else:
            label, color, icon = 'NEUTRAL', 'yellow', 'fa-minus'

        print(f"📊 Pulse: ES={results['ES=F']['price']} ({es_pct:+.2f}%) "
              f"NQ={results['NQ=F']['price']} ({nq_pct:+.2f}%) VIX={vix:.1f} → {label}")

        return jsonify({
            'success': True,
            'spy':  results.get('ES=F', {}),
            'qqq':  results.get('NQ=F', {}),
            'vix':  {'price': vix, 'pct': vix_pct},
            'label': label, 'color': color, 'icon': icon,
            'score': score, 'using_futures': True,
        })
    except Exception as e:
        print(f"❌ market pulse error: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/signals')
def get_signals():
    return jsonify(latest_scan_results)

@app.route('/api/positions')
def get_positions():
    return jsonify({'positions': [], 'total_count': 0})

@app.route('/api/settings', methods=['GET', 'POST'])
def settings():
    global scanner_settings
    
    if request.method == 'GET':
        return jsonify({
            'min_change_pct': scanner_settings['min_change_pct'],
            'min_price': scanner_settings['min_price'],
        })
    else:
        try:
            data = request.json
            
            if 'min_change_pct' in data:
                scanner_settings['min_change_pct'] = float(data['min_change_pct'])
            if 'min_price' in data:
                scanner_settings['min_price'] = float(data['min_price'])
            
            return jsonify({'success': True})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

@app.route('/api/performance')
def get_performance():
    return jsonify({'total_pnl': 0, 'win_rate': 0, 'total_trades': 0})

# ========== AUTH ROUTES ==========

@app.route('/api/auth/me', methods=['GET'])
def get_current_user():
    """Get current user info"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({'authenticated': False}), 401
        
        user = auth_manager.get_user(user_id)
        if not user:
            return jsonify({'authenticated': False}), 401
        
        return jsonify({
            'authenticated': True,
            'user': {
                'id': user['id'],
                'email': user['email'],
                'username': user.get('username', ''),
                'subscription_status': user.get('subscription_status', 'inactive'),
                'is_subscribed': user.get('is_subscribed', False),
                'subscription_tier': user.get('subscription_tier', 'free')
            }
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """Login user with email + password"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'error': 'Email and password are required'}), 400
        
        user = auth_manager.login_user(email, password)
        
        if user:
            session.permanent = True
            session['user_id'] = user['id']
            token = generate_token(user['id'])
            return jsonify({'success': True, 'user': user, 'token': token})
        else:
            return jsonify({'error': 'Invalid email or password'}), 401
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    """Sign up new user with username, email, and password"""
    try:
        data = request.json
        email = data.get('email', '').strip().lower()
        username = data.get('username', '').strip()
        password = data.get('password', '')
        
        if not email or not username or not password:
            return jsonify({'error': 'Username, email, and password are required'}), 400
        
        if len(password) < 8:
            return jsonify({'error': 'Password must be at least 8 characters'}), 400
        
        user = auth_manager.create_user(email, username, password)
        
        if user:
            session.permanent = True
            session['user_id'] = user['id']
            token = generate_token(user['id'])
            return jsonify({'success': True, 'user': user, 'token': token})
        else:
            return jsonify({'error': 'Email or username already taken'}), 400
            
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/auth/logout', methods=['POST'])
def logout():
    """Logout user"""
    session.pop('user_id', None)
    return jsonify({'success': True})

# ========== WATCHLIST ROUTES ==========

@app.route('/api/watchlist', methods=['GET'])
def get_watchlist():
    """Get user's watchlist"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({'watchlist': []}), 401
        result = supabase.client.table('watchlists')            .select('ticker, notes, target_price, created_at')            .eq('user_id', user_id)            .order('created_at', desc=True)            .execute()
        return jsonify({'watchlist': result.data or []})
    except Exception as e:
        print(f"❌ get_watchlist error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/watchlist', methods=['POST'])
def add_to_watchlist():
    """Add ticker to watchlist"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401
        data = request.json
        ticker = data.get('ticker', '').upper().strip()
        if not ticker:
            return jsonify({'error': 'Ticker required'}), 400
        # Upsert — won't duplicate if already exists
        result = supabase.client.table('watchlists').upsert({
            'user_id': user_id,
            'ticker': ticker,
            'created_at': datetime.now().isoformat()
        }, on_conflict='user_id,ticker').execute()
        return jsonify({'success': True, 'ticker': ticker})
    except Exception as e:
        print(f"❌ add_to_watchlist error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/watchlist/<ticker>', methods=['DELETE'])
def remove_from_watchlist(ticker):
    """Remove ticker from watchlist"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401
        supabase.client.table('watchlists')            .delete()            .eq('user_id', user_id)            .eq('ticker', ticker.upper())            .execute()
        return jsonify({'success': True})
    except Exception as e:
        print(f"❌ remove_from_watchlist error: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/watchlist/<ticker>', methods=['PATCH'])
def update_watchlist_item(ticker):
    """Update watchlist item notes/target price"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401
        data = request.json
        updates = {}
        if 'notes' in data:
            updates['notes'] = data['notes']
        if 'target_price' in data:
            updates['target_price'] = data['target_price']
        if not updates:
            return jsonify({'error': 'Nothing to update'}), 400
        supabase.client.table('watchlists').update(updates)            .eq('user_id', user_id).eq('ticker', ticker.upper()).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== PRESETS ROUTES ==========

@app.route('/api/presets', methods=['GET'])
def get_presets():
    """Get user's scan presets"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({'presets': []}), 401
        result = supabase.client.table('user_presets')            .select('id, name, settings, created_at')            .eq('user_id', user_id)            .order('created_at', desc=False)            .execute()
        return jsonify({'presets': result.data or [], 'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/presets', methods=['POST'])
def save_preset():
    """Save a scan preset"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401
        data = request.json
        name = data.get('name', '').strip()
        settings = data.get('settings', {})
        if not name:
            return jsonify({'error': 'Preset name required'}), 400
        # Limit to 10 presets per user
        existing = supabase.client.table('user_presets')            .select('id').eq('user_id', user_id).execute()
        if len(existing.data or []) >= 10:
            return jsonify({'error': 'Max 10 presets allowed'}), 400
        result = supabase.client.table('user_presets').insert({
            'user_id': user_id,
            'name': name,
            'settings': settings
        }).execute()
        return jsonify({'success': True, 'preset': result.data[0] if result.data else {}})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/presets/<preset_id>', methods=['DELETE'])
def delete_preset(preset_id):
    """Delete a scan preset"""
    try:
        user_id = get_user_id_from_request()
        if not user_id:
            return jsonify({'error': 'Not authenticated'}), 401
        supabase.client.table('user_presets')            .delete().eq('id', preset_id).eq('user_id', user_id).execute()
        return jsonify({'success': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# ========== ANALYTICS ROUTES ==========

@app.route('/api/analytics/hot-stocks', methods=['GET'])
def get_hot_stocks():
    """Get hot stocks from last 7 days"""
    try:
        hot_stocks = supabase.get_hot_stocks()
        return jsonify({'hot_stocks': hot_stocks})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/themes/hot', methods=['GET'])
def get_hot_themes():
    """Get current hot themes with keywords for frontend filtering"""
    try:
        themes = hot_themes.get_themes()
        # Return keywords for each active theme so frontend can match catalysts
        keywords_map = {
            theme: hot_themes.THEME_KEYWORDS.get(theme, [theme.lower()])
            for theme in themes
        }
        return jsonify({'themes': themes, 'keywords': keywords_map, 'success': True})
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/themes/update', methods=['POST'])
def update_hot_themes():
    """Manually trigger theme update (admin only in production)"""
    try:
        # Run scoring directly to surface any errors
        counts = hot_themes._score_themes_from_news()
        if not counts:
            return jsonify({'success': False, 'error': 'No themes scored - check Alpaca API key or news response'}), 500
        
        hot_themes._save_to_db(counts)
        hot_themes._cache = None
        themes = hot_themes.get_themes(force_update=True)
        return jsonify({'success': True, 'themes': themes, 'scored': dict(counts.most_common(10))})
    except Exception as e:
        import traceback
        return jsonify({'error': str(e), 'trace': traceback.format_exc(), 'success': False}), 500

# ========== ACTIVITY FEED ROUTES ==========

@app.route('/api/activity/debug', methods=['GET'])
def debug_activity_feed():
    """Debug endpoint to check activity feed data sources"""
    debug_info = {
        'latest_scan_results': {
            'exists': latest_scan_results is not None,
            'has_gaps': 'morning_gaps' in latest_scan_results if latest_scan_results else False,
            'gap_count': len(latest_scan_results.get('morning_gaps', [])) if latest_scan_results else 0,
            'sample_ticker': latest_scan_results.get('morning_gaps', [{}])[0].get('ticker') if latest_scan_results and latest_scan_results.get('morning_gaps') else None
        },
        'volume_cache': {},
        'database_cache': {},
        'activity_generator': {
            'initialized': activity_feed is not None
        }
    }
    
    # Check volume cache
    common_settings = ['10.0_1.0_both', '15.0_1.0_both', '20.0_1.0_both']
    for settings_key in common_settings:
        cached = cache.get_cached_stock_data(settings_key)
        debug_info['volume_cache'][settings_key] = {
            'exists': cached is not None,
            'has_gaps': 'morning_gaps' in cached if cached else False,
            'gap_count': len(cached.get('morning_gaps', [])) if cached else 0
        }
    
    # Check database
    try:
        result = supabase.client.table('scan_results_cache')\
            .select('scan_settings, created_at')\
            .order('created_at', desc=True)\
            .limit(5)\
            .execute()
        
        debug_info['database_cache'] = {
            'table_exists': True,
            'row_count': len(result.data) if result.data else 0,
            'recent_scans': [
                {'settings': r['scan_settings'], 'created_at': r['created_at']}
                for r in (result.data or [])
            ]
        }
    except Exception as e:
        debug_info['database_cache'] = {
            'error': str(e)
        }
    
    # Test activity generation
    try:
        if latest_scan_results and 'morning_gaps' in latest_scan_results:
            test_tickers = [s['ticker'] for s in latest_scan_results['morning_gaps'][:5]]
            test_stock_data = {
                s['ticker']: {
                    'ai_score': s.get('ai_score', 0),
                    'price_change': s.get('price_change_pct', 0)
                }
                for s in latest_scan_results['morning_gaps'][:5]
            }
            
            test_activity = activity_feed.generate_simulated_activity(test_tickers, test_stock_data)
            debug_info['test_generation'] = {
                'success': test_activity is not None,
                'activity': test_activity
            }
        else:
            debug_info['test_generation'] = {'error': 'No scan results to test with'}
    except Exception as e:
        debug_info['test_generation'] = {'error': str(e)}
    
    return jsonify(debug_info)

@app.route('/api/activity/feed', methods=['GET'])
def get_activity_feed():
    """Get hybrid activity feed (real + simulated)"""
    try:
        # Get tickers from multiple sources
        tickers = []
        stock_data = {}  # ticker -> {ai_score, price_change}
        
        # First try: Current scan results (RAM)
        if latest_scan_results and 'morning_gaps' in latest_scan_results:
            for stock in latest_scan_results['morning_gaps']:
                ticker = stock['ticker']
                tickers.append(ticker)
                stock_data[ticker] = {
                    'ai_score': stock.get('ai_score', 0),
                    'price_change': stock.get('price_change_pct', 0)
                }
        
        # Second try: Volume cache (fast)
        if not tickers:
            common_settings = [
                '10.0_1.0_both',
                '15.0_1.0_both', 
                '20.0_1.0_both',
                '10.0_1.0_gainers',
                '10.0_1.0_losers'
            ]
            
            for settings_key in common_settings:
                cached = cache.get_cached_stock_data(settings_key)
                if cached and 'morning_gaps' in cached:
                    for stock in cached['morning_gaps']:
                        ticker = stock['ticker']
                        tickers.append(ticker)
                        stock_data[ticker] = {
                            'ai_score': stock.get('ai_score', 0),
                            'price_change': stock.get('price_change_pct', 0)
                        }
                    if tickers:
                        break
        
        # Third try: Database (persistent, for new visitors)
        if not tickers:
            try:
                result = supabase.client.table('scan_results_cache')\
                    .select('results')\
                    .order('created_at', desc=True)\
                    .limit(1)\
                    .execute()
                
                if result.data and len(result.data) > 0:
                    db_results = result.data[0]['results']
                    if 'morning_gaps' in db_results:
                        for stock in db_results['morning_gaps']:
                            ticker = stock['ticker']
                            tickers.append(ticker)
                            stock_data[ticker] = {
                                'ai_score': stock.get('ai_score', 0),
                                'price_change': stock.get('price_change_pct', 0)
                            }
            except Exception as e:
                print(f"⚠️ Database fallback failed: {e}")
        
        # Only show activity if we have tickers
        if not tickers:
            return jsonify({
                'success': True,
                'activities': [],
                'active_users': 0
            })
        
        # Get hybrid feed (with real stock data)
        feed = activity_feed.get_hybrid_feed(
            real_tickers=tickers, 
            stock_data=stock_data,
            count=10
        )
        active_count = activity_feed.get_active_user_count()
        
        return jsonify({
            'success': True,
            'activities': feed,
            'active_users': active_count
        })
        
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/activity/track', methods=['POST'])
def track_activity():
    """Track user activity (called from frontend)"""
    try:
        data = request.json
        user_id = get_user_id_from_request()  # None if not logged in
        
        activity_feed.track_activity(
            user_id=user_id,
            activity_type=data.get('type'),
            ticker=data.get('ticker'),
            ai_score=data.get('ai_score'),
            price_change=data.get('price_change'),
            city=data.get('city')
        )
        
        return jsonify({'success': True})
        
    except Exception as e:
        return jsonify({'error': str(e), 'success': False}), 500

@app.route('/api/activity/news', methods=['GET'])
def get_activity_news():
    """Public lightweight news feed for activity bar — no auth required"""
    try:
        now = datetime.utcnow()
        result = supabase.client.table('catalyst_watchlist') \
            .select('ticker,headline,news_url,price_change_pct,catalyst_at') \
            .gte('expires_at', now.isoformat()) \
            .order('catalyst_at', desc=True) \
            .limit(30) \
            .execute()

        entries = result.data or []

        # Deduplicate by ticker — keep most recent
        seen = {}
        for e in entries:
            t = e.get('ticker')
            if t and t not in seen:
                seen[t] = e
        entries = list(seen.values())[:15]

        return jsonify({'entries': entries, 'success': True})
    except Exception as e:
        print(f"❌ activity news error: {e}")
        return jsonify({'entries': [], 'success': False}), 500

# ========== SUBSCRIPTION ROUTES ==========

@app.route('/api/subscription/checkout', methods=['POST'])
def create_checkout():
    """Create Stripe checkout session"""
    import traceback
    try:
        print("CHECKOUT ENDPOINT HIT")
        user_id = get_user_id_from_request()
        print(f"CHECKOUT user_id={user_id}")
        if not user_id:
            return jsonify({'error': 'not_authenticated'}), 401

        user = auth_manager.get_user(user_id)
        print(f"CHECKOUT user={user}")
        if not user:
            return jsonify({'error': 'User not found'}), 404

        sc = auth_manager.stripe
        print(f"CHECKOUT stripe enabled={sc.enabled}, price_id={sc.price_id}, key_set={bool(sc.api_key)}")
        if not sc.enabled:
            return jsonify({'error': 'Stripe not configured'}), 500

        base_url = request.host_url.rstrip('/')
        tier = request.json.get('tier', 'pro') if request.json else 'pro'
        rookie_price_id = os.getenv('STRIPE_ROOKIE_PRICE_ID')
        pro_price_id = os.getenv('STRIPE_PRICE_ID')
        selected_price = rookie_price_id if tier == 'rookie' else pro_price_id
        result = auth_manager.create_checkout_session(
            user_id=user_id,
            email=user['email'],
            success_url=f"{base_url}/?subscribed=1",
            cancel_url=f"{base_url}/?canceled=1",
            price_id=selected_price
        )
        if result:
            return jsonify({'success': True, 'url': result['url']})
        return jsonify({'error': 'Checkout session returned None'}), 500
    except Exception as e:
        print(f"CHECKOUT ERROR: {traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/subscription/billing-portal', methods=['POST'])
def billing_portal():
    """Redirect to Stripe billing portal"""
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({'error': 'not_authenticated'}), 401

    # Check if user has a Stripe customer record
    try:
        result = supabase.client.table('user_subscriptions')            .select('stripe_customer_id')            .eq('user_id', user_id).execute()
        if not result.data or not result.data[0].get('stripe_customer_id'):
            return jsonify({
                'error': 'no_subscription',
                'message': 'No active subscription found. Upgrade to Pro to manage billing.'
            }), 404
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    base_url = request.host_url.rstrip('/')
    portal_url = auth_manager.create_billing_portal(
        user_id=user_id,
        return_url=f"{base_url}/"
    )

    if portal_url:
        return jsonify({'success': True, 'url': portal_url})
    return jsonify({'error': 'Could not create billing portal session'}), 500

@app.route('/api/subscription/status', methods=['GET'])
def subscription_status():
    """Get current user subscription status"""
    user_id = get_user_id_from_request()
    if not user_id:
        return jsonify({'is_subscribed': False, 'status': 'inactive'})

    user = auth_manager.get_user(user_id)
    if not user:
        return jsonify({'is_subscribed': False, 'status': 'inactive'})

    return jsonify({
        'is_subscribed': user.get('is_subscribed', False),
        'status': user.get('subscription_status', 'inactive')
    })

@app.route('/api/stripe/webhook', methods=['POST'])
def stripe_webhook():
    """Handle Stripe webhook events"""
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')

    event = stripe_client.verify_webhook_signature(payload, sig_header)
    if not event:
        return jsonify({'error': 'Invalid signature'}), 400

    event_type = event['type']
    data = event['data']['object']

    print(f"📦 Stripe webhook: {event_type}")

    if event_type == 'checkout.session.completed':
        # Fires immediately when customer completes checkout
        # Use this to activate subscription right away before subscription events arrive
        subscription_id = data.get('subscription')
        user_id = data.get('client_reference_id')
        customer_id = data.get('customer')
        if subscription_id and user_id:
            print(f"✅ Checkout complete for user {user_id}, sub {subscription_id}")
            auth_manager.handle_checkout_completed(user_id, customer_id, subscription_id)

    elif event_type == 'customer.subscription.created':
        auth_manager.handle_subscription_created(data)

    elif event_type == 'customer.subscription.updated':
        auth_manager.handle_subscription_updated(data)

    elif event_type == 'customer.subscription.deleted':
        auth_manager.handle_subscription_deleted(data)

    return jsonify({'received': True})

@app.route('/api/news-catalysts', methods=['GET'])
def get_news_catalysts():
    try:
        now = datetime.now()
        result = supabase.client.table('catalyst_watchlist') \
            .select('ticker,headline,news_url,tier,direction,matched_keyword,base_score,catalyst_at,found_at,discovery_price,current_price,price_change_pct,volume_ratio,volume,scanner_qualified') \
            .gte('expires_at', now.isoformat()) \
            .order('tier') \
            .order('catalyst_at', desc=True) \
            .limit(100) \
            .execute()

        entries = result.data or []

        # Dedup by ticker+headline — same article can't appear twice
        seen = set()
        deduped = []
        for e in entries:
            key = (e.get('ticker', ''), e.get('headline', ''))
            if key not in seen:
                seen.add(key)
                deduped.append(e)
        entries = deduped

        # Compute move since news hit
        for e in entries:
            disc = float(e.get('discovery_price') or 0)
            curr = float(e.get('current_price') or 0)
            e['move_since_news'] = round((curr - disc) / disc * 100, 2) if disc > 0 and curr > 0 else None

        # Run AI scoring — shape entries to match what analyzer expects
        try:
            movers_input = [{
                'ticker':         e['ticker'],
                'percent_change': float(e.get('price_change_pct') or 0),
                'price':          float(e.get('current_price') or 0),
                'catalyst':       e.get('headline', ''),
                'has_news':       True,
            } for e in entries]

            scored = watchlist_analyzer.analyze_for_watchlist(movers_input)
            score_lookup = {s['ticker']: s for s in scored}

            for e in entries:
                s = score_lookup.get(e['ticker'], {})
                e['ai_score']          = s.get('score', 0)
                e['ai_type']           = s.get('ep_type', 'N/A')
                e['ai_recommendation'] = s.get('recommendation', '')
        except Exception as score_err:
            print(f'AI scoring error: {score_err}')
            for e in entries:
                e['ai_score'] = 0
                e['ai_type']  = 'N/A'

        return jsonify({'entries': entries, 'count': len(entries), 'as_of': now.isoformat()})
    except Exception as e:
        print(f'News catalysts error: {e}')
        return jsonify({'entries': [], 'count': 0, 'error': str(e)})

@app.route('/health')
def health():
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.now().isoformat(),
        'market_open': data_provider.is_market_open()
    })

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8080))
    print("🚀 Money Making Moves")
    print("   ✅ Trade levels for each EP type")
    app.run(host='0.0.0.0', port=port, debug=False)
