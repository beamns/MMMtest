"""
Supabase Database Client for Money Making Moves
Handles: User accounts, settings, watchlists, scan history, analytics
"""

from supabase import create_client, Client
import os
from datetime import datetime
from typing import List, Dict, Optional


class SupabaseDB:
    """Database client for Money Making Moves"""
    
    def __init__(self):
        supabase_url = os.getenv('SUPABASE_URL')
        supabase_key = os.getenv('SUPABASE_SERVICE_KEY')
        
        if not supabase_url or not supabase_key:
            print("⚠️  Supabase credentials not found - running without database")
            self.client = None
        else:
            try:
                self.client: Client = create_client(supabase_url, supabase_key)
                print("✅ Supabase connected")
            except Exception as e:
                print(f"⚠️  Supabase connection failed: {e}")
                print("   Running without database functionality")
                self.client = None
    
    # ==================== USER MANAGEMENT ====================
    
    def get_or_create_user(self, email: str, full_name: str = None) -> Optional[Dict]:
        """Get existing user or create new one"""
        if not self.client:
            print("❌ Supabase client not available")
            return None
        
        try:
            print(f"🔍 Looking up user: {email}")
            # Try to get existing user
            result = self.client.table('users').select('*').eq('email', email).execute()
            print(f"📊 Query result: {result.data}")
            
            if result.data and len(result.data) > 0:
                print(f"✅ User exists: {result.data[0]['id']}")
                # Update last login
                user_id = result.data[0]['id']
                self.client.table('users').update({
                    'last_login': datetime.now().isoformat()
                }).eq('id', user_id).execute()
                
                return result.data[0]
            else:
                print(f"➕ Creating new user: {email}")
                # Create new user
                new_user_data = {
                    'email': email,
                    'full_name': full_name
                }
                print(f"📝 Insert data: {new_user_data}")
                
                new_user = self.client.table('users').insert(new_user_data).execute()
                print(f"📦 Insert result: {new_user.data}")
                
                # Create default settings
                if new_user.data:
                    user_id = new_user.data[0]['id']
                    print(f"⚙️  Creating default settings for user: {user_id}")
                    self.client.table('user_settings').insert({
                        'user_id': user_id
                    }).execute()
                
                return new_user.data[0] if new_user.data else None
                
        except Exception as e:
            print(f"❌ Error in get_or_create_user: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    # ==================== USER SETTINGS ====================
    
    def get_user_settings(self, user_id: str) -> Optional[Dict]:
        """Get user's scanner settings"""
        if not self.client:
            return None
        
        try:
            result = self.client.table('user_settings').select('*').eq('user_id', user_id).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            print(f"Error getting settings: {e}")
            return None
    
    def update_user_settings(self, user_id: str, settings: Dict) -> bool:
        """Update user's scanner settings"""
        if not self.client:
            return False
        
        try:
            self.client.table('user_settings').update(settings).eq('user_id', user_id).execute()
            return True
        except Exception as e:
            print(f"Error updating settings: {e}")
            return False
    
    # ==================== WATCHLISTS ====================
    
    def get_watchlist(self, user_id: str) -> List[Dict]:
        """Get user's watchlist"""
        if not self.client:
            return []
        
        try:
            result = self.client.table('watchlists').select('*').eq('user_id', user_id).order('created_at', desc=True).execute()
            return result.data if result.data else []
        except Exception as e:
            print(f"Error getting watchlist: {e}")
            return []
    
    def add_to_watchlist(self, user_id: str, ticker: str, notes: str = None, target_price: float = None) -> bool:
        """Add stock to watchlist"""
        if not self.client:
            return False
        
        try:
            self.client.table('watchlists').insert({
                'user_id': user_id,
                'ticker': ticker,
                'notes': notes,
                'target_price': target_price
            }).execute()
            return True
        except Exception as e:
            print(f"Error adding to watchlist: {e}")
            return False
    
    def remove_from_watchlist(self, user_id: str, ticker: str) -> bool:
        """Remove stock from watchlist"""
        if not self.client:
            return False
        
        try:
            self.client.table('watchlists').delete().eq('user_id', user_id).eq('ticker', ticker).execute()
            return True
        except Exception as e:
            print(f"Error removing from watchlist: {e}")
            return False
    
    def update_watchlist_note(self, user_id: str, ticker: str, notes: str) -> bool:
        """Update notes for a watchlist stock"""
        if not self.client:
            return False
        
        try:
            self.client.table('watchlists').update({
                'notes': notes
            }).eq('user_id', user_id).eq('ticker', ticker).execute()
            return True
        except Exception as e:
            print(f"Error updating watchlist: {e}")
            return False
    
    # ==================== SCAN HISTORY ====================
    
    def save_scan(self, stocks: List[Dict], settings: Dict, cached: bool = False) -> Optional[str]:
        """Save scan results to history"""
        if not self.client:
            return None
        
        try:
            # Insert scan record
            scan_result = self.client.table('scans').insert({
                'total_stocks': len(stocks),
                'settings': settings,
                'cached': cached
            }).execute()
            
            if not scan_result.data:
                return None
            
            scan_id = scan_result.data[0]['id']
            
            # Insert stock history
            stock_records = []
            for stock in stocks:
                stock_records.append({
                    'scan_id': scan_id,
                    'ticker': stock.get('ticker'),
                    'price': stock.get('price'),
                    'change_pct': stock.get('price_change_pct'),
                    'ai_score': stock.get('ep_score'),
                    'ep_type': stock.get('ep_type'),
                    'catalyst': stock.get('catalyst'),
                    'has_news': stock.get('has_news', False),
                    'has_exact_mention': stock.get('has_exact_mention', False)
                })
            
            if stock_records:
                self.client.table('stock_history').insert(stock_records).execute()
            
            # Update hot stocks table
            self.client.rpc('update_hot_stocks').execute()
            
            return scan_id
            
        except Exception as e:
            print(f"Error saving scan: {e}")
            return None
    
    def get_recent_scans(self, limit: int = 10) -> List[Dict]:
        """Get recent scan history"""
        if not self.client:
            return []
        
        try:
            result = self.client.table('scans').select('*').order('scan_time', desc=True).limit(limit).execute()
            return result.data if result.data else []
        except Exception as e:
            print(f"Error getting scans: {e}")
            return []
    
    # ==================== ANALYTICS ====================
    
    def get_hot_stocks(self, days: int = 7) -> List[Dict]:
        """Get hot stocks from last N days"""
        if not self.client:
            return []
        
        try:
            result = self.client.rpc('get_hot_stocks_week').execute()
            return result.data if result.data else []
        except Exception as e:
            print(f"Error getting hot stocks: {e}")
            return []
    
    def get_stock_history(self, ticker: str, days: int = 30) -> List[Dict]:
        """Get history for a specific stock"""
        if not self.client:
            return []
        
        try:
            from datetime import timedelta
            cutoff = (datetime.now() - timedelta(days=days)).isoformat()
            
            result = self.client.table('stock_history').select('*').eq('ticker', ticker).gte('created_at', cutoff).order('created_at', desc=True).execute()
            return result.data if result.data else []
        except Exception as e:
            print(f"Error getting stock history: {e}")
            return []
    
    def get_scan_stats(self) -> Dict:
        """Get overall scan statistics"""
        if not self.client:
            return {}
        
        try:
            # Total scans
            scans_count = self.client.table('scans').select('*', count='exact').execute()
            
            # Total unique stocks seen
            stocks = self.client.table('stock_history').select('ticker').execute()
            unique_stocks = len(set([s['ticker'] for s in stocks.data])) if stocks.data else 0
            
            # Most scanned stock
            hot_stocks = self.get_hot_stocks(30)
            most_scanned = hot_stocks[0] if hot_stocks else None
            
            return {
                'total_scans': scans_count.count if hasattr(scans_count, 'count') else 0,
                'unique_stocks': unique_stocks,
                'most_scanned': most_scanned
            }
        except Exception as e:
            print(f"Error getting stats: {e}")
            return {}


# Singleton instance
_db = None

def get_database() -> SupabaseDB:
    """Get or create database singleton"""
    global _db
    if _db is None:
        _db = SupabaseDB()
    return _db
