"""
Hot Themes Tracker - Auto-updates from trending news, persists to Supabase
"""

import os
import re
import requests
from datetime import datetime, timedelta, timezone
from collections import Counter


class HotThemesTracker:
    """Discovers and tracks hot market themes from recent news"""

    THEME_KEYWORDS = {
        # ── Technology ────────────────────────────────────────────────────────
        'AI': [
            'artificial intelligence', ' ai ', 'ai-powered', 'ai model', 'ai platform',
            'machine learning', 'deep learning', 'large language model', 'llm',
            'chatgpt', 'openai', 'anthropic', 'gemini', 'copilot', 'generative ai',
            'neural network', 'ai agent', 'agentic', 'ai chip', 'ai inference',
            'ai training', 'foundation model', 'transformer model',
        ],
        'Semiconductors': [
            'semiconductor', 'chip', 'microchip', 'processor', 'wafer', 'fab',
            'foundry', 'tsmc', 'nvidia', 'intel', 'amd', 'arm holdings',
            'memory chip', 'nand', 'dram', 'hbm', 'advanced packaging',
            'chip shortage', 'chip demand', 'chipmaker', 'fabless',
            'silicon carbide', 'compound semiconductor', 'photonics',
        ],
        'Cloud': [
            'cloud computing', 'cloud platform', 'cloud services', 'saas',
            'paas', 'iaas', 'aws', 'azure', 'google cloud', 'data center',
            'hyperscaler', 'cloud migration', 'multi-cloud', 'hybrid cloud',
            'cloud infrastructure', 'cloud revenue', 'cloud growth',
        ],
        'Cybersecurity': [
            'cybersecurity', 'cyber attack', 'data breach', 'ransomware',
            'zero-day', 'firewall', 'endpoint security', 'identity security',
            'network security', 'threat detection', 'zero trust',
            'cyber threat', 'hack', 'vulnerability', 'exploit',
            'incident response', 'crowdstrike', 'palo alto networks',
        ],
        'Quantum': [
            'quantum computing', 'quantum computer', 'qubit', 'quantum chip',
            'quantum advantage', 'quantum supremacy', 'quantum error correction',
            'quantum network', 'quantum encryption', 'quantum hardware',
        ],
        'Robotics': [
            'robotics', 'robot', 'automation', 'autonomous', 'humanoid robot',
            'industrial robot', 'collaborative robot', 'cobot', 'robotic arm',
            'warehouse automation', 'manufacturing automation', 'robotic surgery',
            'autonomous vehicle', 'self-driving', 'drone delivery',
        ],
        'Software': [
            'annual recurring revenue', 'arr', 'net revenue retention',
            'software subscription', 'enterprise software', 'platform revenue',
        ],
        'DataCenter': [
            'data center', 'hyperscale', 'colocation', 'server farm',
            'data center power', 'liquid cooling', 'ai data center',
            'data center construction', 'power demand',
        ],
        'Telecom': [
            '5g', '6g', 'wireless spectrum', 'fiber broadband',
            'satellite internet', 'starlink', 'cell tower',
        ],

        # ── Biotech / Healthcare ─────────────────────────────────────────────
        'Biotech': [
            'biotech', 'biopharmaceutical', 'gene therapy', 'gene editing',
            'crispr', 'mrna', 'cell therapy', 'car-t', 'immunotherapy',
            'clinical trial', 'phase 2', 'phase 3', 'phase iii',
            'pivotal trial', 'fda approval', 'fda approved', 'breakthrough therapy',
            'orphan drug', 'fast track designation', 'nda', 'bla', 'biologics',
            'drug discovery', 'precision medicine', 'genomics',
        ],
        'GLP1': [
            'glp-1', 'glp1', 'ozempic', 'wegovy', 'mounjaro', 'zepbound',
            'semaglutide', 'tirzepatide', 'liraglutide', 'weight loss drug',
            'obesity drug', 'anti-obesity', 'diabetes drug', 'incretin',
            'novo nordisk', 'eli lilly', 'weight loss treatment',
        ],
        'Healthcare': [
            'healthcare', 'hospital', 'medical device', 'diagnostics',
            'telehealth', 'health insurance', 'medicare', 'medicaid',
            'drug pricing', 'alzheimer', 'oncology', 'rare disease',
        ],
        'Pharma': [
            'pharmaceutical', 'drug approval', 'pipeline drug', 'patent cliff',
            'generic drug', 'biosimilar', 'specialty pharma', 'drug launch',
            'regulatory approval', 'compassionate use',
        ],
        'MedTech': [
            'medtech', 'medical technology', 'surgical system',
            'minimally invasive', 'implant', 'point of care',
            'continuous glucose', 'cgm', 'insulin pump', 'wearable health',
        ],

        # ── Energy ───────────────────────────────────────────────────────────
        'Nuclear': [
            'nuclear', 'small modular reactor', 'smr', 'nuclear power',
            'nuclear energy', 'uranium', 'nuclear plant', 'reactor',
            'nuclear renaissance', 'nuclear fuel', 'enriched uranium',
            'nrc approval', 'kairos', 'nuscale', 'oklo',
        ],
        'Solar': [
            'solar', 'solar panel', 'solar farm', 'photovoltaic', 'pv',
            'solar energy', 'rooftop solar', 'solar installer',
            'first solar', 'solar capacity', 'solar deployment',
        ],
        'CleanEnergy': [
            'clean energy', 'renewable energy', 'green energy', 'wind power',
            'wind turbine', 'offshore wind', 'hydrogen', 'green hydrogen',
            'fuel cell', 'battery storage', 'energy storage', 'grid storage',
            'decarbonization', 'net zero', 'carbon neutral',
        ],
        'Oil': [
            'oil price', 'crude oil', 'wti', 'brent crude', 'opec',
            'oil production', 'oil demand', 'natural gas', 'lng',
            'shale', 'permian', 'drilling', 'refinery',
        ],

        # ── Crypto / Digital Assets ──────────────────────────────────────────
        'Crypto': [
            'crypto', 'cryptocurrency', 'bitcoin', 'btc', 'ethereum', 'eth',
            'blockchain', 'defi', 'stablecoin', 'nft', 'web3',
            'crypto exchange', 'coinbase', 'binance', 'spot bitcoin etf',
            'bitcoin etf', 'digital asset', 'crypto treasury', 'bitcoin reserve',
            'bitcoin treasury', 'crypto regulation', 'sec crypto',
        ],

        # ── Macro / Policy ───────────────────────────────────────────────────
        'Fed': [
            'federal reserve', 'fed rate', 'interest rate', 'rate cut',
            'rate hike', 'fomc', 'monetary policy', 'jerome powell', 'powell',
            'inflation', 'cpi', 'pce', 'core inflation', 'yield curve',
            '10-year yield', 'treasury yield', 'quantitative tightening',
            'fed minutes', 'rate decision',
        ],
        'Tariffs': [
            'tariff', 'tariffs', 'trade war', 'trade deal', 'trade policy',
            'import duty', 'export ban', 'trade restriction', 'trade deficit',
            'reciprocal tariff', 'trade negotiation', 'section 301',
        ],
        'China': [
            'china', 'chinese', 'beijing', 'xi jinping', 'ccp',
            'china tech', 'china ban', 'china sanctions', 'made in china',
            'china tariff', 'china trade', 'alibaba', 'tencent', 'baidu',
            'byd', 'china ev', 'china stimulus', 'china real estate',
        ],
        'Geopolitical': [
            'geopolitical', 'war', 'conflict', 'sanctions', 'russia',
            'ukraine', 'middle east', 'taiwan strait', 'nato',
            'national security', 'export control', 'entity list',
        ],

        # ── Transportation / Industrial ──────────────────────────────────────
        'EV': [
            'electric vehicle', 'ev', 'ev battery', 'battery electric',
            'lithium', 'lithium-ion', 'charging station', 'charging network',
            'ev sales', 'ev demand', 'tesla', 'rivian', 'lucid',
        ],
        'Aerospace': [
            'aerospace', 'aircraft', 'aviation', 'airline', 'jet engine',
            'boeing', 'airbus', 'lockheed', 'raytheon', 'northrop',
            'general dynamics', 'defense contractor', 'aircraft order',
        ],
        'Space': [
            'space', 'satellite', 'spacex', 'rocket', 'nasa', 'orbital',
            'launch vehicle', 'reusable rocket', 'space station',
            'low earth orbit', 'leo', 'space tourism', 'blue origin',
        ],
        'Defense': [
            'defense', 'military', 'weapons', 'ammunition', 'pentagon',
            'dod contract', 'army contract', 'navy contract', 'air force',
            'drone', 'unmanned', 'hypersonic', 'missile', 'radar',
            'defense spending', 'nato spending', 'defense budget',
        ],
        'Reshoring': [
            'reshoring', 'onshoring', 'nearshoring', 'supply chain reshoring',
            'domestic manufacturing', 'chips act', 'inflation reduction act',
            'factory', 'bring back jobs',
        ],

        # ── Finance ──────────────────────────────────────────────────────────
        'Fintech': [
            'fintech', 'digital payment', 'mobile payment', 'neobank',
            'payment processing', 'buy now pay later', 'bnpl',
            'embedded finance', 'open banking', 'digital wallet',
        ],
        'Banking': [
            'bank earnings', 'net interest margin', 'nim', 'loan growth',
            'deposit', 'credit loss', 'provision', 'stress test',
            'fdic', 'bank merger', 'regional bank',
        ],
        'REITs': [
            'reit', 'real estate investment trust', 'commercial real estate',
            'cre', 'office vacancy', 'cap rate', 'mortgage reit',
        ],

        # ── Consumer ─────────────────────────────────────────────────────────
        'Retail': [
            'retail sales', 'consumer spending', 'e-commerce',
            'same-store sales', 'comparable sales', 'foot traffic',
            'holiday sales', 'consumer confidence', 'consumer sentiment',
        ],
        'Gaming': [
            'gaming', 'video game', 'esports', 'metaverse',
            'mobile gaming', 'game launch', 'game studio', 'console',
            'playstation', 'xbox', 'nintendo',
        ],

        # ── Materials / Commodities ──────────────────────────────────────────
        'Gold': [
            'gold', 'gold price', 'gold rally', 'bullion',
            'precious metals', 'safe haven', 'gold demand', 'central bank gold',
        ],
        'Copper': [
            'copper', 'copper price', 'copper demand', 'copper supply',
            'industrial metals', 'base metals', 'copper mining',
        ],
        'Uranium': [
            'uranium', 'uranium price', 'uranium supply', 'uranium demand',
            'uranium enrichment', 'nuclear fuel cycle',
        ],
        'AgriFood': [
            'agriculture', 'wheat', 'corn', 'soybean', 'crop harvest',
            'food inflation', 'fertilizer', 'agtech', 'precision agriculture',
        ],

        # ── Emerging Themes ──────────────────────────────────────────────────
        'MentalHealth': [
            'mental health', 'behavioral health', 'depression treatment',
            'psychedelic', 'ketamine', 'psilocybin', 'adhd', 'addiction treatment',
        ],
        'Longevity': [
            'longevity', 'anti-aging', 'lifespan extension',
            'senolytics', 'rapamycin', 'healthspan',
        ],
        'Water': [
            'water scarcity', 'drought', 'water infrastructure',
            'desalination', 'water treatment', 'water utility',
        ],
        'Memes': [
            'short squeeze', 'gamma squeeze', 'heavily shorted',
            'retail momentum', 'meme stock', 'wallstreetbets',
            'wsb', 'roaring kitty', 'high short interest',
        ],
    }

    def __init__(self, db=None):
        self.db = db
        self._cache = None
        self._cache_time = None

    # ==================== PUBLIC API ====================

    def get_themes(self, force_update=False):
        """Get current hot themes. Returns list of theme name strings."""

        # 5-minute in-memory cache
        if not force_update and self._cache and self._cache_time:
            age_seconds = (datetime.now() - self._cache_time).total_seconds()
            if age_seconds < 300:
                return self._cache

        # Load from database
        themes = self._load_from_db()
        if themes:
            self._cache = themes
            self._cache_time = datetime.now()
            return themes

        # Nothing in DB — try to populate it now
        print("⚠️  No themes in database, fetching from news...")
        self.refresh_themes()

        # Try DB again
        themes = self._load_from_db()
        if themes:
            self._cache = themes
            self._cache_time = datetime.now()
            return themes

        print("⚠️  No themes in database yet — run a theme refresh")
        return []

    def refresh_themes(self):
        """Fetch latest news, score themes, save to database. Call this on a schedule."""
        finnhub_key = os.getenv('FINNHUB_API_KEY', '')
        if not finnhub_key:
            print("⚠️  No Finnhub API key — cannot refresh themes")
            return False

        try:
            counts = self._score_themes_from_news()
            if not counts:
                return False

            self._save_to_db(counts)
            self._cache = None  # Bust cache so next get_themes() reads fresh data
            print(f"✅ Themes refreshed. Top: {', '.join([t for t, _ in counts.most_common(5)])}")
            return True

        except Exception as e:
            print(f"❌ refresh_themes error: {e}")
            return False

    # ==================== INTERNAL ====================

    def _score_themes_from_news(self):
        """Fetch recent news from Finnhub and count theme mentions. Returns Counter."""
        try:
            finnhub_key = os.getenv('FINNHUB_API_KEY', '')
            url = 'https://finnhub.io/api/v1/news'
            params = {'category': 'general', 'token': finnhub_key}
            resp = requests.get(url, params=params, timeout=10)

            if resp.status_code != 200:
                print(f"⚠️  News API error: {resp.status_code}")
                return None

            articles = resp.json()
            if not articles:
                print("⚠️  No news articles returned")
                return None

            counts = Counter()
            for article in articles:
                text = (article.get('headline', '') + ' ' + article.get('summary', '')).lower()
                for theme, keywords in self.THEME_KEYWORDS.items():
                    if any(kw in text for kw in keywords):
                        counts[theme] += 1

            print(f"📊 Scored {len(articles)} articles from Finnhub. Theme hits: {dict(counts.most_common(8))}")
            return counts

        except Exception as e:
            print(f"⚠️  _score_themes_from_news error: {e}")
            return None

    def _load_from_db(self):
        """Load themes from Supabase, returns list or None."""
        if not self.db or not self.db.client:
            return None
        try:
            result = (self.db.client
                      .table('hot_themes')
                      .select('theme, score, last_updated')
                      .order('score', desc=True)
                      .limit(10)
                      .execute())

            if not result.data:
                return None

            # Only use themes updated in the last 24 hours
            cutoff = datetime.now() - timedelta(hours=24)
            fresh = []
            for row in result.data:
                try:
                    raw_upd = row['last_updated'].replace('Z', '').replace('+00:00', '')
                    raw_upd = re.sub(r'\.(\d+)$', lambda m: '.' + m.group(1).ljust(6, '0')[:6], raw_upd)
                    updated = datetime.fromisoformat(raw_upd)
                    if updated > cutoff:
                        fresh.append(row['theme'])
                except Exception:
                    fresh.append(row['theme'])  # Include if can't parse date

            if fresh:
                print(f"✅ Loaded {len(fresh)} fresh themes from database")
                return fresh

            print("⚠️  Themes in database are stale (>24h old)")
            return None

        except Exception as e:
            print(f"⚠️  _load_from_db error: {e}")
            return None

    def _save_to_db(self, counts: Counter):
        """Upsert theme scores to Supabase."""
        if not self.db or not self.db.client:
            print("⚠️  No database connection, cannot save themes")
            return

        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        saved = 0
        for theme, score in counts.items():
            try:
                self.db.client.table('hot_themes').upsert({
                    'theme': theme,
                    'score': score,
                    'last_updated': now
                }, on_conflict='theme').execute()
                saved += 1
            except Exception as e:
                print(f"⚠️  Error saving theme {theme}: {e}")

        print(f"✅ Saved {saved} themes to database")


# Singleton
_tracker = None

def get_hot_themes_tracker(db=None) -> HotThemesTracker:
    global _tracker
    if _tracker is None:
        _tracker = HotThemesTracker(db=db)
    return _tracker

# Backwards compatibility alias used by ep_watchlist_analyzer_DYNAMIC_THEMES
def get_hot_themes(force_update=False):
    return get_hot_themes_tracker().get_themes(force_update=force_update)
