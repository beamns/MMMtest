"""
Authentication Manager for Money Making Moves
Integrates Supabase Auth + Stripe Subscriptions
"""

from supabase_client import get_database
from stripe_client import get_stripe_client
from typing import Optional, Dict
from werkzeug.security import generate_password_hash, check_password_hash
import re


class AuthManager:
    """Handles user authentication and subscription access"""
    
    def __init__(self):
        self.db = get_database()
        self.stripe = get_stripe_client()
    
    # ==================== AUTHENTICATION ====================
    
    def _validate_email(self, email: str) -> bool:
        """Basic email format validation"""
        return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email))

    def _validate_username(self, username: str) -> bool:
        """Username: 3-30 chars, letters/numbers/underscores only"""
        return bool(re.match(r'^[a-zA-Z0-9_]{3,30}$', username))

    def create_user(self, email: str, username: str, password: str) -> Optional[Dict]:
        """Create new user account with hashed password"""
        if not self.db.client:
            return None

        # Validate inputs
        if not self._validate_email(email):
            return None
        if not self._validate_username(username):
            return None
        if len(password) < 8:
            return None

        try:
            # Check if email already exists
            existing_email = self.db.client.table('users').select('id').eq('email', email).execute()
            if existing_email.data:
                print(f"Signup failed: email already taken - {email}")
                return None

            # Check if username already exists
            existing_username = self.db.client.table('users').select('id').eq('username', username).execute()
            if existing_username.data:
                print(f"Signup failed: username already taken - {username}")
                return None

            # Hash the password (bcrypt via werkzeug)
            password_hash = generate_password_hash(password, method='pbkdf2:sha256')

            # Insert new user
            result = self.db.client.table('users').insert({
                'email': email,
                'username': username,
                'password_hash': password_hash,
            }).execute()

            if not result.data:
                return None

            user = result.data[0]
            print(f"✅ User created: {username} ({email})")

            # Return safe user object (no password_hash)
            return {
                'id': user['id'],
                'email': user['email'],
                'username': user['username'],
            }

        except Exception as e:
            print(f"Signup error: {e}")
            return None

    def login_user(self, email: str, password: str) -> Optional[Dict]:
        """Login user — verify email + password"""
        if not self.db.client:
            return None

        try:
            result = self.db.client.table('users').select('id, email, username, password_hash').eq('email', email).execute()

            if not result.data:
                print(f"Login failed: no user found for {email}")
                return None

            user = result.data[0]

            # Verify password against stored hash
            if not check_password_hash(user['password_hash'], password):
                print(f"Login failed: wrong password for {email}")
                return None

            print(f"✅ Login success: {user['username']} ({email})")

            # Return safe user object (no password_hash)
            return {
                'id': user['id'],
                'email': user['email'],
                'username': user['username'],
            }

        except Exception as e:
            print(f"Login error: {e}")
            return None
    
    def get_user(self, user_id: str) -> Optional[Dict]:
        """Get user by ID (for session restore)"""
        if not self.db.client:
            return None
        try:
            result = self.db.client.table('users').select('id, email, username, is_subscribed, subscription_status, subscription_tier').eq('id', user_id).execute()
            if not result.data:
                return None
            return result.data[0]
        except Exception as e:
            print(f"get_user error: {e}")
            return None

    # ==================== SUBSCRIPTION ACCESS ====================
    
    def check_user_access(self, user_id: str) -> bool:
        """Check if user has active subscription"""
        if not self.db.client:
            return False
        
        try:
            result = self.db.client.rpc('user_has_access', {'p_user_id': user_id}).execute()
            return result.data if result.data else False
        except Exception as e:
            print(f"Access check error: {e}")
            return False
    
    def get_subscription_info(self, user_id: str) -> Optional[Dict]:
        """Get detailed subscription information"""
        if not self.db.client:
            return None
        
        try:
            result = self.db.client.rpc('get_user_subscription', {'p_user_id': user_id}).execute()
            return result.data[0] if result.data else None
        except Exception as e:
            print(f"Subscription info error: {e}")
            return None
    
    # ==================== STRIPE CHECKOUT ====================
    
    def create_checkout_session(self, user_id: str, email: str, success_url: str, cancel_url: str, price_id: str = None, **kwargs) -> Optional[Dict]:
        """Create Stripe checkout for subscription"""
        if not self.stripe.enabled:
            return None
        
        return self.stripe.create_checkout_session(user_id, email, success_url, cancel_url, price_id=kwargs.get('price_id'))
    
    def create_billing_portal(self, user_id: str, return_url: str) -> Optional[str]:
        """Create Stripe billing portal session"""
        if not self.db.client or not self.stripe.enabled:
            return None
        
        try:
            # Get customer ID from database
            result = self.db.client.table('user_subscriptions').select('stripe_customer_id').eq('user_id', user_id).execute()
            
            if not result.data:
                return None
            
            customer_id = result.data[0]['stripe_customer_id']
            return self.stripe.create_billing_portal_session(customer_id, return_url)
            
        except Exception as e:
            print(f"Billing portal error: {e}")
            return None
    
    # ==================== WEBHOOK HANDLING ====================
    
    def handle_subscription_created(self, subscription_data: Dict) -> bool:
        """Handle new subscription from Stripe webhook"""
        if not self.db.client:
            return False
        
        try:
            user_id = subscription_data.get('metadata', {}).get('user_id')
            
            if not user_id:
                print("No user_id in subscription metadata")
                return False
            
            from datetime import datetime

            status = subscription_data.get('status', 'trialing')
            # current_period_start/end may be nested in items in newer Stripe API
            period_start = subscription_data.get('current_period_start')
            period_end = subscription_data.get('current_period_end')
            if not period_start:
                try:
                    period_start = subscription_data['items']['data'][0]['current_period_start']
                    period_end = subscription_data['items']['data'][0]['current_period_end']
                except Exception:
                    pass

            sub_row = {
                'user_id': user_id,
                'stripe_customer_id': subscription_data['customer'],
                'stripe_subscription_id': subscription_data['id'],
                'status': status,
                'trial_end': datetime.fromtimestamp(subscription_data['trial_end']).isoformat() if subscription_data.get('trial_end') else None,
                'current_period_start': datetime.fromtimestamp(period_start).isoformat() if period_start else None,
                'current_period_end': datetime.fromtimestamp(period_end).isoformat() if period_end else None,
            }
            existing = self.db.client.table('user_subscriptions').select('id').eq('user_id', user_id).execute()
            if existing.data:
                self.db.client.table('user_subscriptions').update(sub_row).eq('user_id', user_id).execute()
            else:
                self.db.client.table('user_subscriptions').insert(sub_row).execute()

            # Update users table so is_subscribed flips to True
            is_active = status in ('active', 'trialing')
            # Detect tier from price ID
            rookie_price_id = os.getenv('STRIPE_ROOKIE_PRICE_ID', '')
            price_id = subscription_data.get('plan', {}).get('id', '') or ''
            tier = 'rookie' if price_id == rookie_price_id else 'pro'
            self.db.client.table('users').update({
                'is_subscribed': is_active,
                'subscription_status': status,
                'subscription_tier': tier
            }).eq('id', user_id).execute()
            print(f"✅ Subscription created for user {user_id}: {status} tier={tier}")

            return True

        except Exception as e:
            print(f"Subscription created error: {e}")
            return False
    
    def handle_subscription_updated(self, subscription_data: Dict) -> bool:
        """Handle subscription update from Stripe webhook"""
        if not self.db.client:
            return False
        
        try:
            from datetime import datetime

            status = subscription_data.get('status', 'active')
            period_start = subscription_data.get('current_period_start')
            period_end = subscription_data.get('current_period_end')

            self.db.client.table('user_subscriptions').update({
                'status': status,
                'trial_end': datetime.fromtimestamp(subscription_data['trial_end']).isoformat() if subscription_data.get('trial_end') else None,
                'current_period_start': datetime.fromtimestamp(period_start).isoformat() if period_start else None,
                'current_period_end': datetime.fromtimestamp(period_end).isoformat() if period_end else None,
                'cancel_at_period_end': subscription_data.get('cancel_at_period_end', False),
                'canceled_at': datetime.fromtimestamp(subscription_data['canceled_at']).isoformat() if subscription_data.get('canceled_at') else None,
                'updated_at': datetime.now().isoformat()
            }).eq('stripe_subscription_id', subscription_data['id']).execute()

            # Also update users table
            is_active = status in ('active', 'trialing')
            # Find user by subscription id
            sub_row = self.db.client.table('user_subscriptions').select('user_id').eq('stripe_subscription_id', subscription_data['id']).execute()
            if sub_row.data:
                uid = sub_row.data[0]['user_id']
                self.db.client.table('users').update({
                    'is_subscribed': is_active,
                    'subscription_status': status
                }).eq('id', uid).execute()
                print(f"✅ Subscription updated for user {uid}: {status}")

            return True

        except Exception as e:
            print(f"Subscription updated error: {e}")
            return False
    
    def handle_subscription_deleted(self, subscription_data: Dict) -> bool:
        """Handle subscription cancellation from Stripe webhook"""
        if not self.db.client:
            return False
        
        try:
            from datetime import datetime

            # Find user before updating
            sub_row = self.db.client.table('user_subscriptions').select('user_id').eq('stripe_subscription_id', subscription_data['id']).execute()

            self.db.client.table('user_subscriptions').update({
                'status': 'canceled',
                'canceled_at': datetime.now().isoformat()
            }).eq('stripe_subscription_id', subscription_data['id']).execute()

            # Flip users table
            if sub_row.data:
                uid = sub_row.data[0]['user_id']
                self.db.client.table('users').update({
                    'is_subscribed': False,
                    'subscription_status': 'inactive'
                }).eq('id', uid).execute()
                print(f"✅ Subscription canceled for user {uid}")

            return True

        except Exception as e:
            print(f"Subscription deleted error: {e}")
            return False


    def handle_checkout_completed(self, user_id: str, customer_id: str, subscription_id: str) -> bool:
        """Handle checkout.session.completed - activate subscription immediately"""
        if not self.db.client:
            return False
        try:
            from datetime import datetime
            import stripe as stripe_lib

            stripe_lib.api_key = self.stripe.api_key
            sub = stripe_lib.Subscription.retrieve(subscription_id)

            status = sub.get('status', 'trialing')
            period_start = sub.get('current_period_start')
            period_end = sub.get('current_period_end')

            existing = self.db.client.table('user_subscriptions').select('id').eq('user_id', user_id).execute()

            sub_data = {
                'user_id': user_id,
                'stripe_customer_id': customer_id,
                'stripe_subscription_id': subscription_id,
                'status': status,
                'trial_end': datetime.fromtimestamp(sub['trial_end']).isoformat() if sub.get('trial_end') else None,
                'current_period_start': datetime.fromtimestamp(period_start).isoformat() if period_start else None,
                'current_period_end': datetime.fromtimestamp(period_end).isoformat() if period_end else None,
                'cancel_at_period_end': sub.get('cancel_at_period_end', False),
                'updated_at': datetime.now().isoformat()
            }

            if existing.data:
                self.db.client.table('user_subscriptions').update(sub_data).eq('user_id', user_id).execute()
            else:
                sub_data['created_at'] = datetime.now().isoformat()
                self.db.client.table('user_subscriptions').insert(sub_data).execute()

            # THIS is the critical step - flip is_subscribed on users table
            is_active = status in ('active', 'trialing')
            self.db.client.table('users').update({
                'is_subscribed': is_active,
                'subscription_status': status
            }).eq('id', user_id).execute()

            print(f"✅ Checkout completed for user {user_id}: {status}, is_subscribed={is_active}")
            return True

        except Exception as e:
            print(f"❌ handle_checkout_completed error: {e}")
            return False


# Singleton
_auth_manager = None

def get_auth_manager() -> AuthManager:
    """Get or create auth manager singleton"""
    global _auth_manager
    if _auth_manager is None:
        _auth_manager = AuthManager()
    return _auth_manager
