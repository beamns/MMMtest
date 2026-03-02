"""
Cache Manager - Multi-layer caching for stock data, news, and AI scores
Layer 1: RAM (0.01ms, 5-minute TTL)
Layer 2: Volume (1ms, 24-hour TTL)
"""

import json
import os
import time
from datetime import datetime, timedelta
from typing import Optional, Dict, List


class CacheManager:
    """Manages multi-layer caching of stock data, news, and AI scores"""
    
    def __init__(self, cache_dir='/data/cache'):
        self.cache_dir = cache_dir
        self.stock_cache_file = f'{cache_dir}/stock_cache.json'
        self.news_cache_file = f'{cache_dir}/news_cache.json'
        self.ai_cache_file = f'{cache_dir}/ai_scores_cache.json'
        
        # Create cache directory if it doesn't exist
        os.makedirs(cache_dir, exist_ok=True)
        
        # Layer 1: RAM Cache (fastest)
        self._memory_stock_cache = {}
        self._memory_news_cache = {}
        self._memory_ai_cache = {}
        self._memory_timestamps = {
            'stock': {},
            'news': {},
            'ai': {}
        }
        
        # Cache durations
        self.MEMORY_CACHE_SECONDS = 300  # 5 minutes (RAM)
        self.STOCK_CACHE_HOURS = 24      # 24 hours (Volume)
        self.NEWS_CACHE_HOURS = 24       # 24 hours (Volume)
        self.AI_CACHE_HOURS = 24         # 24 hours (Volume)
        
        print("✅ Multi-layer cache initialized (RAM + Volume)")
    
    # ==================== STOCK DATA CACHE ====================
    
    def get_cached_stock_data(self, settings_key: str) -> Optional[Dict]:
        """
        Get cached stock scan results (with RAM layer)
        settings_key = f"{min_change}_{min_price}_{direction}"
        """
        # Layer 1: Check RAM first (0.01ms)
        if settings_key in self._memory_stock_cache:
            age = time.time() - self._memory_timestamps['stock'].get(settings_key, 0)
            if age < self.MEMORY_CACHE_SECONDS:
                print(f"💨 RAM cache HIT for stocks: {settings_key} ({age:.1f}s old)")
                return self._memory_stock_cache[settings_key]
            else:
                # Expired, remove from RAM
                del self._memory_stock_cache[settings_key]
                del self._memory_timestamps['stock'][settings_key]
        
        # Layer 2: Check Volume (1ms)
        # Layer 2: Check Volume (1ms)
        if not os.path.exists(self.stock_cache_file):
            return None
        
        try:
            with open(self.stock_cache_file, 'r') as f:
                cache = json.load(f)
            
            if settings_key not in cache:
                return None
            
            entry = cache[settings_key]
            cached_time = datetime.fromisoformat(entry['timestamp'])
            age_hours = (datetime.now() - cached_time).total_seconds() / 3600
            
            if age_hours < self.STOCK_CACHE_HOURS:
                print(f"📂 Volume cache HIT for stocks: {settings_key} ({age_hours:.1f}h old)")
                # Promote to RAM
                self._memory_stock_cache[settings_key] = entry['data']
                self._memory_timestamps['stock'][settings_key] = time.time()
                return entry['data']
            else:
                print(f"⏰ Cache expired (age: {age_hours:.1f}h)")
                return None
                
        except Exception as e:
            print(f"⚠️ Error reading stock cache: {e}")
            return None
    
    def save_stock_data(self, settings_key: str, data: Dict):
        """Save stock scan results to cache (RAM + Volume)"""
        try:
            # Layer 1: Save to RAM (instant)
            self._memory_stock_cache[settings_key] = data
            self._memory_timestamps['stock'][settings_key] = time.time()
            print(f"💨 Saved to RAM cache: {settings_key}")
            
            # Layer 2: Save to Volume (persistent)
            cache = {}
            if os.path.exists(self.stock_cache_file):
                with open(self.stock_cache_file, 'r') as f:
                    cache = json.load(f)
            
            cache[settings_key] = {
                'timestamp': datetime.now().isoformat(),
                'data': data
            }
            
            # Clean old entries (keep only last 10 different settings combinations)
            if len(cache) > 10:
                sorted_keys = sorted(
                    cache.keys(), 
                    key=lambda k: cache[k]['timestamp'], 
                    reverse=True
                )
                cache = {k: cache[k] for k in sorted_keys[:10]}
            
            with open(self.stock_cache_file, 'w') as f:
                json.dump(cache, f)
            
            print(f"💾 Saved stock data to cache (key: {settings_key})")
            
        except Exception as e:
            print(f"⚠️ Error saving stock cache: {e}")
    
    # ==================== NEWS CACHE ====================
    
    def get_cached_news(self, ticker: str) -> Optional[List[Dict]]:
        """Get cached news articles for a ticker (with RAM layer)"""
        # Layer 1: Check RAM first
        if ticker in self._memory_news_cache:
            age = time.time() - self._memory_timestamps['news'].get(ticker, 0)
            if age < self.MEMORY_CACHE_SECONDS:
                print(f"💨 RAM cache HIT for news: {ticker}")
                return self._memory_news_cache[ticker]
            else:
                del self._memory_news_cache[ticker]
                del self._memory_timestamps['news'][ticker]
        
        # Layer 2: Check Volume
        if not os.path.exists(self.news_cache_file):
            return None
        
        try:
            with open(self.news_cache_file, 'r') as f:
                cache = json.load(f)
            
            if ticker not in cache:
                return None
            
            entry = cache[ticker]
            cached_time = datetime.fromisoformat(entry['timestamp'])
            age_hours = (datetime.now() - cached_time).total_seconds() / 3600
            
            if age_hours < self.NEWS_CACHE_HOURS:
                print(f"📂 Volume cache HIT for news: {ticker} ({age_hours:.1f}h old)")
                # Promote to RAM
                self._memory_news_cache[ticker] = entry['articles']
                self._memory_timestamps['news'][ticker] = time.time()
                return entry['articles']
            else:
                print(f"⏰ News cache expired for {ticker}")
                return None
                
        except Exception as e:
            print(f"⚠️ Error reading news cache: {e}")
            return None
    
    def save_news(self, ticker: str, articles: List[Dict]):
        """Save news articles to cache (RAM + Volume)"""
        try:
            # Layer 1: Save to RAM
            self._memory_news_cache[ticker] = articles
            self._memory_timestamps['news'][ticker] = time.time()
            
            # Layer 2: Save to Volume
            cache = {}
            if os.path.exists(self.news_cache_file):
                with open(self.news_cache_file, 'r') as f:
                    cache = json.load(f)
            
            cache[ticker] = {
                'timestamp': datetime.now().isoformat(),
                'articles': articles
            }
            
            # Clean old entries (keep only last 100 tickers)
            if len(cache) > 100:
                sorted_keys = sorted(
                    cache.keys(), 
                    key=lambda k: cache[k]['timestamp'], 
                    reverse=True
                )
                cache = {k: cache[k] for k in sorted_keys[:100]}
            
            with open(self.news_cache_file, 'w') as f:
                json.dump(cache, f)
            
            print(f"💾 Saved news for {ticker} to cache")
            
        except Exception as e:
            print(f"⚠️ Error saving news cache: {e}")
    
    # ==================== AI SCORES CACHE ====================
    
    def get_cached_ai_scores(self, ticker: str) -> Optional[Dict]:
        """Get cached AI analysis for a ticker (with RAM layer)"""
        # Layer 1: Check RAM first
        if ticker in self._memory_ai_cache:
            age = time.time() - self._memory_timestamps['ai'].get(ticker, 0)
            if age < self.MEMORY_CACHE_SECONDS:
                print(f"💨 RAM cache HIT for AI: {ticker}")
                return self._memory_ai_cache[ticker]
            else:
                del self._memory_ai_cache[ticker]
                del self._memory_timestamps['ai'][ticker]
        
        # Layer 2: Check Volume
        if not os.path.exists(self.ai_cache_file):
            return None
        
        try:
            with open(self.ai_cache_file, 'r') as f:
                cache = json.load(f)
            
            if ticker not in cache:
                return None
            
            entry = cache[ticker]
            cached_time = datetime.fromisoformat(entry['timestamp'])
            age_hours = (datetime.now() - cached_time).total_seconds() / 3600
            
            if age_hours < self.AI_CACHE_HOURS:
                print(f"📂 Volume cache HIT for AI: {ticker} ({age_hours:.1f}h old)")
                # Promote to RAM
                self._memory_ai_cache[ticker] = entry['analysis']
                self._memory_timestamps['ai'][ticker] = time.time()
                return entry['analysis']
            else:
                print(f"⏰ AI cache expired for {ticker}")
                return None
                
        except Exception as e:
            print(f"⚠️ Error reading AI cache: {e}")
            return None
    
    def save_ai_scores(self, ticker: str, analysis: Dict):
        """Save AI analysis to cache (RAM + Volume)"""
        try:
            # Layer 1: Save to RAM
            self._memory_ai_cache[ticker] = analysis
            self._memory_timestamps['ai'][ticker] = time.time()
            
            # Layer 2: Save to Volume
            cache = {}
            if os.path.exists(self.ai_cache_file):
                with open(self.ai_cache_file, 'r') as f:
                    cache = json.load(f)
            
            cache[ticker] = {
                'timestamp': datetime.now().isoformat(),
                'analysis': analysis
            }
            
            # Clean old entries (keep only last 200 tickers)
            if len(cache) > 200:
                sorted_keys = sorted(
                    cache.keys(), 
                    key=lambda k: cache[k]['timestamp'], 
                    reverse=True
                )
                cache = {k: cache[k] for k in sorted_keys[:200]}
            
            with open(self.ai_cache_file, 'w') as f:
                json.dump(cache, f)
            
            print(f"💾 Saved AI scores for {ticker} to cache")
            
        except Exception as e:
            print(f"⚠️ Error saving AI cache: {e}")
    
    # ==================== UTILITIES ====================
    
    def clear_all_cache(self):
        """Clear all cache files"""
        for cache_file in [self.stock_cache_file, self.news_cache_file, self.ai_cache_file]:
            if os.path.exists(cache_file):
                os.remove(cache_file)
        print("🗑️ All caches cleared")
    
    def get_cache_stats(self) -> Dict:
        """Get statistics about cache usage"""
        stats = {
            'stock_entries': 0,
            'news_entries': 0,
            'ai_entries': 0,
            'total_size_mb': 0
        }
        
        try:
            if os.path.exists(self.stock_cache_file):
                with open(self.stock_cache_file, 'r') as f:
                    stats['stock_entries'] = len(json.load(f))
                stats['total_size_mb'] += os.path.getsize(self.stock_cache_file) / 1024 / 1024
            
            if os.path.exists(self.news_cache_file):
                with open(self.news_cache_file, 'r') as f:
                    stats['news_entries'] = len(json.load(f))
                stats['total_size_mb'] += os.path.getsize(self.news_cache_file) / 1024 / 1024
            
            if os.path.exists(self.ai_cache_file):
                with open(self.ai_cache_file, 'r') as f:
                    stats['ai_entries'] = len(json.load(f))
                stats['total_size_mb'] += os.path.getsize(self.ai_cache_file) / 1024 / 1024
            
            stats['total_size_mb'] = round(stats['total_size_mb'], 2)
            
        except Exception as e:
            print(f"⚠️ Error getting cache stats: {e}")
        
        return stats


# Singleton instance
_cache_manager = None

def get_cache_manager() -> CacheManager:
    """Get or create cache manager singleton"""
    global _cache_manager
    if _cache_manager is None:
        _cache_manager = CacheManager()
    return _cache_manager
