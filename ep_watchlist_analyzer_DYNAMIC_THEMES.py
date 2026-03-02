"""
EP Watchlist Analyzer - Multi-Factor Scoring Engine
Based on Pradeep Bonde's Episodic Pivot (EP) Playbook.

EP Types scored:
  - Breakout          : Blowout earnings/sales, neglected stock forced to reprice
  - Comeback          : Recovery from prolonged decline, profitability restored
  - Theme Play        : Hot narrative (AI, crypto, GLP-1, etc.) drives the move
  - Delayed Reaction : Big volume day 1, messy close -> secondary entry later
  - Volume Spike      : Volume-only signal -- abnormal volume IS the catalyst
  - Small Float Runner: Habitual runners, small float, 40-50% bursts in 5-6 days
  - Short Setup       : Negative catalyst, always better as delayed entry

Scoring factors: catalyst tier, EP type bonus, volume (Bonde's #1 signal),
move size, price range, hot theme, multi-signal confirmation, penalties.
"""

from datetime import datetime
from typing import List, Dict, Tuple
import sys, os
sys.path.append(os.path.dirname(__file__))
from hot_themes_tracker import get_hot_themes


# --- LONG Catalyst Tiers (Bonde playbook) -------------------------------------
# Tier 1: Game-changing, forces immediate market repricing
LONG_TIER1 = [
    # FDA / Clinical
    'fda approval', 'fda approved', 'fda clearance', 'accelerated approval',
    'breakthrough therapy', 'orphan drug', 'fast track', 'priority review',
    'phase 3', 'phase iii', 'pivotal trial', 'positive data', 'nda approved',
    # M&A
    'acquisition', 'acquired', 'merger', 'buyout', 'going private',
    'strategic review', 'takeover', 'tender offer',
    # Earnings/Sales blowout (Growth EP core signal)
    'earnings beat', 'eps beat', 'revenue beat', 'blowout earnings',
    'blowout sales', 'triple digit', 'sales doubled', 'revenue doubled',
    'raised guidance', 'upgraded guidance', 'raises outlook',
    # Transformative deals
    'special dividend', 'spin-off', 'spinoff', 'major contract',
    'government contract', 'dod contract', 'nasa contract',
]

# Tier 2: Strong catalyst, significant but not transformative
LONG_TIER2 = [
    # Earnings/growth (still meaningful)
    'earnings', 'revenue', 'sales growth', 'profit', 'guidance', 'eps',
    'beat estimates', 'beat expectations', 'exceeded', 'surpassed',
    # Deals & partnerships
    'partnership', 'collaboration', 'licensing', 'license agreement',
    'supply agreement', 'distribution deal', 'joint venture',
    'contract', 'deal', 'agreement', 'award', 'win',
    # Corporate actions
    'buyback', 'share repurchase', 'dividend', 'new ceo', 'new management',
    'strategic shift', 'restructuring plan', 'cost cutting',
    # Thematic (Story EP signals)
    'ai partnership', 'bitcoin treasury', 'crypto treasury',
    'weight loss', 'glp-1', 'ozempic', 'wegovy', 'robotics',
    'quantum', 'nuclear', 'defense contract',
]

# Tier 3: Soft catalyst -- Turnaround signals, analyst upgrades
LONG_TIER3 = [
    # Turnaround EP signals
    'turnaround', 'return to profitability', 'profitable', 'breakeven',
    'first profit', 'positive ebitda', 'operational improvement',
    'new product', 'product launch', 'fda submission', 'nda submission',
    # Analyst / institutional
    'upgrade', 'upgraded', 'analyst upgrade', 'price target raised',
    'price target increase', 'initiated', 'overweight', 'outperform',
    'strong buy', 'buy rating',
    # Recovery language (Turnaround EP)
    'recovery', 'rebound', 'improvement', 'momentum', 'inflection',
]

# --- SHORT Catalyst Tiers -----------------------------------------------------
SHORT_TIER1 = [
    # Earnings disaster
    'earnings miss', 'revenue miss', 'missed estimates', 'missed expectations',
    'below estimates', 'below expectations', 'guidance cut', 'cuts guidance',
    'lowered guidance', 'reduced guidance', 'withdraws guidance',
    'suspends guidance', 'guides below',
    # FDA / Clinical failure
    'fda rejected', 'fda rejection', 'complete response letter', 'crl',
    'clinical failure', 'trial failure', 'failed trial', 'trial stopped',
    'failed to meet', 'did not meet',
    # Existential threats
    'going concern', 'bankruptcy', 'chapter 11', 'default',
    'subpoena', 'sec investigation', 'doj investigation', 'fraud charges',
    'restatement', 'material weakness',
]

SHORT_TIER2 = [
    # Miss language
    'missed', 'misses', 'shortfall', 'disappointing', 'disappoints',
    'below consensus', 'fell short',
    # Financial stress
    'loss', 'losses', 'net loss', 'operating loss', 'cash burn',
    'dilution', 'equity offering', 'secondary offering',
    # Negative corporate
    'downgrade', 'downgraded', 'price target cut', 'price target lowered',
    'recall', 'warning letter', 'fda warning', 'investigation',
    'impairment', 'write-down', 'write-off',
    'layoff', 'layoffs', 'job cuts', 'restructuring charges',
    'ceo resigned', 'ceo departure', 'management change',
]

SHORT_TIER3 = [
    'below expectations', 'weakness', 'headwinds', 'challenging environment',
    'difficult market', 'slowdown', 'decline', 'declining', 'soft demand',
    'pressure', 'margin compression', 'cost pressure', 'concerns',
    'cautious', 'uncertainty', 'deceleration',
]

# --- Penalty words ------------------------------------------------------------
PENALTY_WORDS = [
    'dilut', 'offering', 'shelf registration', 'secondary offering',
    'lawsuit', 'litigation', 'sec invest', 'sec probe',
    'bankruptcy', 'default', 'delist', 'fraud', 'restat',
    'going concern', 'auditor',
]

# --- Story/Thematic EP keywords (Bonde: AI, crypto, GLP-1, robotics, etc.) ---
STORY_KEYWORDS = [
    'artificial intelligence', ' ai ', 'machine learning', 'llm', 'chatgpt',
    'bitcoin', 'crypto', 'blockchain', 'ethereum', 'treasury',
    'weight loss', 'glp-1', 'ozempic', 'wegovy', 'semaglutide', 'tirzepatide',
    'quantum computing', 'quantum',
    'robotics', 'autonomous', 'self-driving',
    'nuclear', 'small modular reactor', 'smr',
    'defense', 'military', 'drone', 'hypersonic',
    'space', 'satellite',
]

# --- Sugar Baby patterns ------------------------------------------------------
SUGAR_BABY_SIGNALS = [
    'squeeze', 'short squeeze', 'gamma squeeze',
    'heavily shorted', 'high short interest', 'retail momentum',
]


class EPWatchlistAnalyzer:
    """
    Multi-factor EP scoring engine aligned with Bonde's Episodic Pivot playbook.
    """

    def __init__(self):
        self.hot_themes = []
        self.hot_theme_keywords = []
        self._load_hot_themes()

    def _load_hot_themes(self):
        try:
            from hot_themes_tracker import HotThemesTracker
            tracker = HotThemesTracker()
            self.hot_themes = tracker.get_themes()
            self.hot_theme_keywords = []
            for theme in self.hot_themes:
                keywords = tracker.THEME_KEYWORDS.get(theme, [theme.lower()])
                self.hot_theme_keywords.extend(keywords)
            print(f"Loaded {len(self.hot_themes)} hot themes ({len(self.hot_theme_keywords)} keywords)")
        except Exception as e:
            print(f"Error loading themes: {e}")
            self.hot_themes = []
            self.hot_theme_keywords = []

    def analyze_for_watchlist(self, movers: List[Dict]) -> List[Dict]:
        recommendations = []
        for mover in movers:
            score, reasons, ai_type, direction = self._score_mover(mover)
            reason_text = ", ".join(reasons) if reasons else "Price move"
            recommendations.append({
                'ticker':         mover['ticker'],
                'reason':         reason_text,
                'score':          score,
                'ep_type':        ai_type,
                'direction':      direction,
                'catalyst':       mover.get('catalyst', 'Price action'),
                'price':          mover.get('price', 0),
                'percent_change': mover.get('percent_change', 0),
                'has_news':       mover.get('has_news', False),
                'volume_ratio':   mover.get('volume_ratio', 1.0),
                'recommendation': self._recommendation_text(reason_text, score, ai_type, direction)
            })
        recommendations.sort(key=lambda x: x['score'], reverse=True)
        return recommendations

    def _score_mover(self, mover: Dict) -> Tuple[int, List[str], str, str]:
        raw_pct   = mover.get('percent_change', 0)
        pct       = abs(raw_pct)
        is_short  = raw_pct < 0
        catalyst  = mover.get('catalyst', '').lower()
        price     = mover.get('price', 0)
        has_news  = mover.get('has_news', False)
        exact     = mover.get('has_exact_mention', False)
        vol_ratio = mover.get('volume_ratio', 1.0)
        volume    = mover.get('volume', 0)

        score   = 0
        reasons = []

        # 1. Catalyst quality & EP type classification
        if is_short:
            cat_score, cat_reasons, ai_type = self._short_catalyst_score(catalyst, has_news, exact)
        else:
            cat_score, cat_reasons, ai_type = self._long_catalyst_score(catalyst, has_news, exact)
        score   += cat_score
        reasons += cat_reasons

        # 2. Volume Spike EP -- volume-only EP (abnormal volume IS the catalyst)
        ep9m_score, ep9m_reason, is_ep9m = self._ep9m_score(vol_ratio, volume, has_news)
        if is_ep9m and ai_type == "Price Mover":
            ai_type = "Volume Spike"
        score += ep9m_score
        if ep9m_reason:
            reasons.append(ep9m_reason)

        # 3. Move size
        move_score, move_reason = self._move_score(pct)
        score += move_score
        if move_reason:
            reasons.append(move_reason)

        # 4. Volume confirmation (Bonde's #1 signal)
        vol_score, vol_reason = self._volume_score(vol_ratio, volume)
        score += vol_score
        if vol_reason:
            reasons.append(vol_reason)

        # 5. Price range
        price_score = self._price_score(price, pct)
        score += price_score

        # 6. Hot theme / Theme Play
        theme_score = 0
        if not is_short:
            theme_score, theme_reason = self._theme_score(catalyst)
            score += theme_score
            if theme_reason:
                reasons.append(theme_reason)
                if ai_type in ("Price Mover", "Volume Spike"):
                    ai_type = "Theme Play"

        # 7. Small Float Runner pattern
        if not is_short and price < 10 and pct >= 30:
            sb_score, sb_reason = self._sugar_baby_score(catalyst, price, pct, vol_ratio)
            score += sb_score
            if sb_reason:
                reasons.append(sb_reason)
                if ai_type == "Price Mover":
                    ai_type = "Small Float Runner"

        # 8. Multi-signal confirmation
        signals_firing = sum([
            cat_score > 0,
            move_score >= 15,
            vol_score >= 10,
            theme_score > 0,
            is_ep9m,
        ])
        if signals_firing >= 3:
            score += 15
            reasons.append("multi-signal confirmation")
        elif signals_firing >= 2 and has_news:
            score += 8

        # 9. Penalties
        penalty, penalty_reason = self._penalty_score(catalyst, price, pct, has_news, is_short, vol_ratio)
        score += penalty
        if penalty_reason:
            reasons.append(penalty_reason)

        # Floor & cap
        if score <= 0:
            score = 10
            if not reasons:
                reasons = ["Price move"]
        score = min(score, 100)
        direction = "short" if is_short else "long"
        return score, reasons, ai_type, direction

    def _long_catalyst_score(self, catalyst: str, has_news: bool, exact: bool) -> Tuple[int, List[str], str]:
        score = 0
        reasons = []
        ai_type = "Price Mover"

        is_tier1 = any(kw in catalyst for kw in LONG_TIER1)
        is_tier2 = any(kw in catalyst for kw in LONG_TIER2)
        is_tier3 = any(kw in catalyst for kw in LONG_TIER3)

        if is_tier1:
            score += 45
            matched = next((kw for kw in LONG_TIER1 if kw in catalyst), '')
            reasons.append(f"Major catalyst ({matched.upper()})")
            if any(kw in catalyst for kw in ['fda', 'approval', 'phase 3', 'pivotal', 'breakthrough', 'orphan', 'fast track', 'nda']):
                ai_type = "Biotech Catalyst"
            elif any(kw in catalyst for kw in ['acquisition', 'merger', 'buyout', 'takeover', 'going private', 'tender']):
                ai_type = "Buyout Play"
            else:
                ai_type = "Growth"

        elif is_tier2:
            score += 30
            if any(kw in catalyst for kw in ['earnings', 'revenue', 'sales', 'eps', 'beat', 'exceeded', 'guidance']):
                reasons.append("Earnings/Growth catalyst")
                ai_type = "Growth"
            elif any(kw in catalyst for kw in ['ai ', 'bitcoin', 'crypto', 'glp-1', 'ozempic', 'quantum', 'robotics', 'nuclear', 'defense']):
                reasons.append("Thematic catalyst")
                ai_type = "Theme Play"
            elif any(kw in catalyst for kw in ['new ceo', 'new management', 'strategic shift', 'cost cutting']):
                reasons.append("Leadership/strategic catalyst")
                ai_type = "Comeback"
            else:
                reasons.append("Strong catalyst")
                ai_type = "Growth"

        elif is_tier3:
            score += 18
            if any(kw in catalyst for kw in ['turnaround', 'return to profitability', 'profitable', 'first profit', 'recovery', 'inflection']):
                reasons.append("Turnaround signal")
                ai_type = "Comeback"
            else:
                reasons.append("Analyst/soft catalyst")
                ai_type = "Watchlist Setup"

        if exact:
            score += 20
            reasons.append("ticker-specific news")
        elif has_news and (is_tier1 or is_tier2):
            score += 12
            reasons.append("confirmed by news")
        elif has_news:
            score += 6

        return score, reasons, ai_type

    def _short_catalyst_score(self, catalyst: str, has_news: bool, exact: bool) -> Tuple[int, List[str], str]:
        score = 0
        reasons = []
        ai_type = "Short Setup"

        is_tier1 = any(kw in catalyst for kw in SHORT_TIER1)
        is_tier2 = any(kw in catalyst for kw in SHORT_TIER2)
        is_tier3 = any(kw in catalyst for kw in SHORT_TIER3)

        if is_tier1:
            score += 45
            matched = next((kw for kw in SHORT_TIER1 if kw in catalyst), '')
            reasons.append(f"Major breakdown ({matched.upper()})")
            if any(kw in catalyst for kw in ['going concern', 'bankruptcy', 'fraud', 'sec invest', 'restat', 'subpoena', 'material weakness']):
                ai_type = "Breakdown"
            elif any(kw in catalyst for kw in ['fda rejected', 'fda rejection', 'clinical failure', 'trial failure', 'crl']):
                ai_type = "FDA Fail"
            else:
                ai_type = "Earnings Miss"

        elif is_tier2:
            score += 30
            if any(kw in catalyst for kw in ['missed', 'misses', 'loss', 'shortfall', 'fell short']):
                reasons.append("Missed estimates")
                ai_type = "Earnings Miss"
            elif any(kw in catalyst for kw in ['downgrade', 'downgraded', 'price target cut']):
                reasons.append("Analyst downgrade")
                ai_type = "Analyst Downgrade"
            else:
                reasons.append("Negative catalyst")
                ai_type = "Short Setup"

        elif is_tier3:
            score += 12
            reasons.append("Negative outlook")
            ai_type = "Short Setup"

        else:
            score += 5
            reasons.append("Price breakdown")
            ai_type = "Short Setup"

        if exact:
            score += 20
            reasons.append("ticker-specific news")
        elif has_news and (is_tier1 or is_tier2):
            score += 12
            reasons.append("confirmed by news")
        elif has_news:
            score += 6

        return score, reasons, ai_type

    def _ep9m_score(self, vol_ratio: float, volume: float, has_news: bool) -> Tuple[int, str, bool]:
        """Bonde: abnormal volume IS the catalyst. Volume-only EP."""
        if volume >= 9_000_000:
            if vol_ratio >= 10:
                return 20, f"Vol Spike: {volume/1e6:.0f}M shares ({vol_ratio:.0f}x normal)", True
            return 15, f"Vol Spike: {volume/1e6:.0f}M shares traded", True
        # Relative volume proxy when no absolute data
        if vol_ratio >= 5 and not has_news:
            return 12, f"implied catalyst ({vol_ratio:.1f}x vol, no news)", True
        return 0, "", False

    def _move_score(self, pct: float) -> Tuple[int, str]:
        if pct >= 100:
            return 30, "parabolic move (100%+)"
        elif pct >= 50:
            return 25, "explosive move (50%+)"
        elif pct >= 30:
            return 20, "strong move (30%+)"
        elif pct >= 20:
            return 15, "solid move (20%+)"
        elif pct >= 15:
            return 10, ""
        elif pct >= 10:
            return 5, ""
        return 0, ""

    def _volume_score(self, vol_ratio: float, volume: float) -> Tuple[int, str]:
        """Bonde's #1 conviction signal: huge volume increase."""
        if vol_ratio >= 20:
            return 30, f"{vol_ratio:.0f}x volume (institutional)"
        elif vol_ratio >= 10:
            return 25, f"{vol_ratio:.0f}x volume"
        elif vol_ratio >= 5:
            return 20, f"{vol_ratio:.1f}x volume"
        elif vol_ratio >= 3:
            return 15, f"{vol_ratio:.1f}x volume"
        elif vol_ratio >= 2:
            return 8, f"{vol_ratio:.1f}x volume"
        elif vol_ratio >= 1.5:
            return 4, ""
        elif vol_ratio < 0.7 and volume > 0:
            return -10, "low volume warning"
        return 0, ""

    def _price_score(self, price: float, pct: float) -> int:
        """Bonde: small/mid-cap re-rates have biggest impact. Sugar babies valid at <$5."""
        # Sugar baby / small float explosive move exception
        if price < 5.0 and pct >= 30:
            return 8
        if price < 1.0:
            return -15
        elif price < 2.0:
            return 0   # Removed penalty — Bonde trades $1-5 range actively
        elif 2.0 <= price < 5.0:
            return 5
        elif 5.0 <= price <= 50.0:
            return 12  # Sweet spot for EP re-rating
        elif 50.0 < price <= 150.0:
            return 8
        elif 150.0 < price <= 500.0:
            return 4
        return 0

    def _theme_score(self, catalyst: str) -> Tuple[int, str]:
        """Bonde Story EP: AI, crypto, GLP-1, quantum, robotics, nuclear."""
        if self.hot_theme_keywords:
            matched = [kw for kw in self.hot_theme_keywords if kw in catalyst]
            if matched:
                return 15, f"hot theme: {matched[0].upper()}"
        for kw in STORY_KEYWORDS:
            if kw in catalyst:
                return 12, f"story theme: {kw.strip().upper()}"
        return 0, ""

    def _sugar_baby_score(self, catalyst: str, price: float, pct: float, vol_ratio: float) -> Tuple[int, str]:
        """Bonde Sugar Babies: habitual runners, 40-50% bursts in 5-6 days."""
        score = 0
        reason = ""
        if price < 5.0 and pct >= 40 and vol_ratio >= 3:
            score += 10
            reason = f"Sugar Baby profile (${price:.2f}, +{pct:.0f}%)"
        elif price < 10.0 and pct >= 30 and vol_ratio >= 5:
            score += 8
            reason = "small-float runner"
        if any(kw in catalyst for kw in SUGAR_BABY_SIGNALS):
            score += 5
            reason = (reason + ", squeeze signal") if reason else "squeeze signal"
        return score, reason

    def _penalty_score(self, catalyst: str, price: float, pct: float, has_news: bool, is_short: bool, vol_ratio: float) -> Tuple[int, str]:
        penalty = 0
        reasons = []
        if any(kw in catalyst for kw in PENALTY_WORDS):
            if not is_short:
                penalty -= 25
                reasons.append("dilution/risk flag")
            else:
                penalty -= 5
        # Big move, no news, low volume = suspicious (not EP 9M)
        if pct >= 40 and not has_news and vol_ratio < 3:
            penalty -= 15 if not is_short else 5
            reasons.append("large move, no news/volume")
        if price < 0.5:
            penalty -= 15
        return penalty, ", ".join(reasons)

    def _recommendation_text(self, reason: str, score: int, ai_type: str, direction: str) -> str:
        if score >= 80:
            strength = "High conviction"
        elif score >= 65:
            strength = "Strong signal"
        elif score >= 45:
            strength = "Moderate signal"
        else:
            strength = "Early stage"
        side = "SHORT" if direction == "short" else "LONG"
        return f"{strength} {side} — {ai_type}: {reason}"


def create_watchlist_analyzer():
    return EPWatchlistAnalyzer()
