"""
Activity Feed Generator - Hybrid Real + Simulated
Creates engaging activity feed for viral growth
"""

import random
from datetime import datetime, timedelta
from typing import List, Dict


class ActivityFeedGenerator:
    """Generates realistic activity feed mixing real + simulated data"""
    
    def __init__(self, db=None):
        self.db = db
        
        # Realistic first names (diverse)
        self.first_names = [
            'Alex', 'Sarah', 'Mike', 'Jessica', 'David', 'Maria', 'Chris', 'Emily',
            'Ryan', 'Ashley', 'Kevin', 'Nicole', 'Jason', 'Lauren', 'Brian', 'Amanda',
            'Daniel', 'Rachel', 'Matthew', 'Jennifer', 'Andrew', 'Melissa', 'Josh', 'Amy',
            'Tyler', 'Michelle', 'Brandon', 'Stephanie', 'Jordan', 'Rebecca', 'Justin', 'Angela',
            'James', 'Lisa', 'John', 'Karen', 'Robert', 'Nancy', 'Michael', 'Linda',
            'Chen', 'Yuki', 'Carlos', 'Sofia', 'Ahmed', 'Priya', 'Luis', 'Fatima'
        ]
        
        # Major US cities with state codes
        self.cities = [
            'NYC', 'LA', 'Chicago', 'Houston', 'Phoenix', 'Philadelphia', 'San Antonio',
            'San Diego', 'Dallas', 'Austin', 'Seattle', 'Denver', 'Boston', 'Miami',
            'Atlanta', 'Portland', 'Las Vegas', 'Detroit', 'Nashville', 'Baltimore',
            'San Francisco', 'Charlotte', 'Columbus', 'Indianapolis', 'San Jose',
            'Jacksonville', 'Fort Worth', 'Oklahoma City', 'Raleigh', 'Memphis',
            'Louisville', 'Richmond', 'New Orleans', 'Salt Lake City', 'Tampa',
            'Minneapolis', 'Cleveland', 'Orlando', 'Tucson', 'Honolulu'
        ]
        
        # Activity templates
        self.activity_templates = {
            'found_mover': {
                'emoji': '💰',
                'template': '{name} from {city} found {ticker} {change}% (AI: {score})',
                'weight': 40  # Most exciting, show often
            },
            'scanning': {
                'emoji': '🚀',
                'template': '{name} from {city} scanning for {scan_type}',
                'weight': 25
            },
            'view_stock': {
                'emoji': '📈',
                'template': '{name} from {city} opened {ticker} (AI: {score})',
                'weight': 20
            },
            'add_watchlist': {
                'emoji': '⭐',
                'template': '{name} from {city} added {ticker} to watchlist',
                'weight': 15
            }
        }
        
        self.scan_types = [
            'gainers', 'losers', 'hot themes', 'high AI scores',
            'after-hours movers', 'breakouts', 'momentum plays'
        ]
    
    def generate_simulated_activity(self, real_tickers: List[str] = None, stock_data: Dict = None) -> Dict:
        """Generate one realistic simulated activity using REAL stock data"""
        
        # ONLY generate if we have real tickers from scan
        if not real_tickers or len(real_tickers) == 0:
            return None
        
        # Choose activity type (weighted random)
        activity_type = random.choices(
            list(self.activity_templates.keys()),
            weights=[t['weight'] for t in self.activity_templates.values()]
        )[0]
        
        template_data = self.activity_templates[activity_type]
        
        # Build activity
        activity = {
            'type': activity_type,
            'emoji': template_data['emoji'],
            'name': random.choice(self.first_names),
            'city': random.choice(self.cities),
            'timestamp': datetime.now().isoformat(),
            'simulated': True
        }
        
        # Add type-specific data - use REAL stock data
        if activity_type == 'found_mover':
            ticker = random.choice(real_tickers)
            
            # Use REAL data if available
            if stock_data and ticker in stock_data:
                ai_score = stock_data[ticker].get('ai_score', random.randint(75, 98))
                price_change = abs(stock_data[ticker].get('price_change', random.uniform(10, 35)))
            else:
                ai_score = random.randint(75, 98)
                price_change = random.uniform(10, 35)
            
            activity.update({
                'ticker': ticker,
                'change': round(price_change, 1),
                'score': ai_score
            })
            
        elif activity_type == 'scanning':
            activity['scan_type'] = random.choice(self.scan_types)
            
        elif activity_type == 'view_stock':
            ticker = random.choice(real_tickers)
            
            # Use REAL AI score if available
            if stock_data and ticker in stock_data:
                ai_score = stock_data[ticker].get('ai_score', random.randint(65, 95))
            else:
                ai_score = random.randint(65, 95)
            
            activity.update({
                'ticker': ticker,
                'score': ai_score
            })
            
        elif activity_type == 'add_watchlist':
            ticker = random.choice(real_tickers)
            activity['ticker'] = ticker
        
        # Format message with error handling
        try:
            activity['message'] = template_data['template'].format(**activity)
        except KeyError as e:
            print(f"⚠️ Missing key in activity template: {e}")
            # Fallback message
            if activity_type == 'found_mover':
                activity['message'] = f"{activity['name']} from {activity['city']} found {activity.get('ticker', 'stock')} +{activity.get('change', 0)}%"
            elif activity_type == 'scanning':
                activity['message'] = f"{activity['name']} from {activity['city']} scanning for {activity.get('scan_type', 'stocks')}"
            elif activity_type == 'view_stock':
                activity['message'] = f"{activity['name']} from {activity['city']} opened {activity.get('ticker', 'stock')}"
            elif activity_type == 'add_watchlist':
                activity['message'] = f"{activity['name']} from {activity['city']} added {activity.get('ticker', 'stock')} to watchlist"
            else:
                activity['message'] = f"{activity['name']} from {activity['city']} is active"
        
        return activity
    
    def get_recent_real_activity(self, limit: int = 5) -> List[Dict]:
        """Get recent real user activity from database"""
        if not self.db:
            return []
        
        try:
            result = self.db.client.table('user_activity')\
                .select('*')\
                .order('created_at', desc=True)\
                .limit(limit)\
                .execute()
            
            activities = []
            for row in result.data:
                activity = {
                    'type': row['activity_type'],
                    'ticker': row.get('ticker'),
                    'ai_score': row.get('ai_score'),
                    'price_change': row.get('price_change'),
                    'city': row.get('city', 'Unknown'),
                    'timestamp': row['created_at'],
                    'simulated': False
                }
                
                # Format message based on type
                if activity['type'] == 'found_mover':
                    activity['emoji'] = '💰'
                    activity['message'] = f"Trader from {activity['city']} found {activity['ticker']} {activity['price_change']}% (AI: {activity['ai_score']})"
                elif activity['type'] == 'view_stock':
                    activity['emoji'] = '📈'
                    activity['message'] = f"Someone from {activity['city']} opened {activity['ticker']}"
                elif activity['type'] == 'add_watchlist':
                    activity['emoji'] = '⭐'
                    activity['message'] = f"Trader from {activity['city']} added {activity['ticker']} to watchlist"
                
                activities.append(activity)
            
            return activities
            
        except Exception as e:
            print(f"Error fetching real activity: {e}")
            return []
    
    def get_hybrid_feed(self, real_tickers: List[str] = None, stock_data: Dict = None, count: int = 10) -> List[Dict]:
        """
        Get hybrid feed: mix of real + simulated activity
        ONLY uses tickers from actual scan results with REAL data
        """
        
        # No tickers = no feed (wait for scan)
        if not real_tickers or len(real_tickers) == 0:
            return []
        
        # Get real activity
        real_activities = self.get_recent_real_activity(limit=3)
        
        # Calculate how many simulated we need
        real_count = len(real_activities)
        simulated_needed = max(0, count - real_count)
        
        # Generate simulated activity (with real stock data)
        simulated_activities = []
        for _ in range(simulated_needed):
            activity = self.generate_simulated_activity(real_tickers, stock_data)
            if activity:  # Only add if generation succeeded
                simulated_activities.append(activity)
        
        # Mix them together
        all_activities = real_activities + simulated_activities
        
        # Shuffle to mix real and simulated
        random.shuffle(all_activities)
        
        # Sort by timestamp (most recent first)
        all_activities.sort(key=lambda x: x['timestamp'], reverse=True)
        
        return all_activities[:count]
    
    def track_activity(self, user_id: str, activity_type: str, ticker: str = None, 
                       ai_score: int = None, price_change: float = None, city: str = None):
        """Track real user activity to database"""
        if not self.db:
            return
        
        try:
            self.db.client.table('user_activity').insert({
                'user_id': user_id if user_id else None,  # Allow anonymous
                'activity_type': activity_type,
                'ticker': ticker,
                'ai_score': ai_score,
                'price_change': price_change,
                'city': city or self._get_random_city(),  # Fallback to random city for privacy
                'created_at': datetime.now().isoformat()
            }).execute()
            
            print(f"✅ Tracked activity: {activity_type} - {ticker}")
            
        except Exception as e:
            print(f"⚠️ Error tracking activity: {e}")
    
    def get_active_user_count(self) -> int:
        """Get current active users count (mix of real + simulated)"""
        
        # Get real active users (last 5 minutes)
        real_active = 0
        if self.db:
            try:
                five_min_ago = (datetime.now() - timedelta(minutes=5)).isoformat()
                result = self.db.client.table('user_activity')\
                    .select('user_id', count='exact')\
                    .gte('created_at', five_min_ago)\
                    .execute()
                
                real_active = result.count if result.count else 0
                
            except Exception as e:
                print(f"Error counting active users: {e}")
        
        # Add simulated buffer (makes it look busier)
        # Base: 50-150 users
        # + Real users
        simulated_base = random.randint(50, 150)
        
        total = simulated_base + (real_active * 2)  # Multiply real by 2 for social proof
        
        return total
    
    def _get_random_ticker(self) -> str:
        """Get random popular ticker for simulated activity"""
        popular_tickers = [
            'AAPL', 'TSLA', 'NVDA', 'MSFT', 'GOOGL', 'AMZN', 'META',
            'AMD', 'NFLX', 'DIS', 'BA', 'PLTR', 'COIN', 'SOFI',
            'NIO', 'RIVN', 'LCID', 'F', 'GM', 'INTC', 'PYPL'
        ]
        return random.choice(popular_tickers)
    
    def _get_random_city(self) -> str:
        """Get random city for privacy"""
        return random.choice(self.cities)


# Singleton
_activity_generator = None

def get_activity_generator(db=None):
    """Get or create activity generator singleton"""
    global _activity_generator
    if _activity_generator is None:
        _activity_generator = ActivityFeedGenerator(db)
    return _activity_generator
