"""
Stripe Integration for Money Making Moves
30-day trial + $25/month subscription
"""

import stripe
import os
from typing import Optional, Dict
from datetime import datetime


class StripeClient:
    """Stripe payment integration"""
    
    def __init__(self):
        self.api_key = os.getenv('STRIPE_SECRET_KEY')
        self.publishable_key = os.getenv('STRIPE_PUBLISHABLE_KEY')
        self.price_id = os.getenv('STRIPE_PRICE_ID')  # Monthly $25 Pro price
        self.rookie_price_id = os.getenv('STRIPE_ROOKIE_PRICE_ID')  # Monthly $10 Rookie price
        self.webhook_secret = os.getenv('STRIPE_WEBHOOK_SECRET')
        
        if not self.api_key:
            print("⚠️  Stripe API key not found")
            self.enabled = False
        else:
            stripe.api_key = self.api_key
            self.enabled = True
            print("✅ Stripe initialized")
    
    def create_checkout_session(self, user_id: str, email: str, success_url: str, cancel_url: str, price_id: str = None) -> Optional[Dict]:
        """
        Create Stripe Checkout session for 30-day trial + $25/month
        """
        if not self.enabled:
            return None
        
        try:
            session = stripe.checkout.Session.create(
                customer_email=email,
                client_reference_id=user_id,
                payment_method_types=['card'],
                line_items=[{
                    'price': self.price_id,
                    'quantity': 1,
                }],
                mode='subscription',
                subscription_data={
                    'trial_period_days': 7,  # 30-day free trial
                    'metadata': {
                        'user_id': user_id
                    }
                },
                success_url=success_url,
                cancel_url=cancel_url,
                allow_promotion_codes=True,  # Allow discount codes
            )
            
            return {
                'session_id': session.id,
                'url': session.url
            }
            
        except Exception as e:
            print(f"Error creating checkout session: {e}")
            return None
    
    def create_billing_portal_session(self, customer_id: str, return_url: str) -> Optional[str]:
        """
        Create Stripe Customer Portal session for managing subscription
        """
        if not self.enabled:
            return None
        
        try:
            session = stripe.billing_portal.Session.create(
                customer=customer_id,
                return_url=return_url,
            )
            return session.url
        except Exception as e:
            print(f"Error creating portal session: {e}")
            return None
    
    def get_subscription(self, subscription_id: str) -> Optional[Dict]:
        """Get subscription details from Stripe"""
        if not self.enabled:
            return None
        
        try:
            sub = stripe.Subscription.retrieve(subscription_id)
            return {
                'id': sub.id,
                'status': sub.status,
                'customer_id': sub.customer,
                'trial_end': datetime.fromtimestamp(sub.trial_end) if sub.trial_end else None,
                'current_period_start': datetime.fromtimestamp(sub.current_period_start),
                'current_period_end': datetime.fromtimestamp(sub.current_period_end),
                'cancel_at_period_end': sub.cancel_at_period_end,
                'canceled_at': datetime.fromtimestamp(sub.canceled_at) if sub.canceled_at else None,
            }
        except Exception as e:
            print(f"Error getting subscription: {e}")
            return None
    
    def cancel_subscription(self, subscription_id: str, at_period_end: bool = True) -> bool:
        """
        Cancel subscription
        at_period_end=True: Access until end of billing period
        at_period_end=False: Immediate cancellation
        """
        if not self.enabled:
            return False
        
        try:
            if at_period_end:
                stripe.Subscription.modify(
                    subscription_id,
                    cancel_at_period_end=True
                )
            else:
                stripe.Subscription.delete(subscription_id)
            return True
        except Exception as e:
            print(f"Error canceling subscription: {e}")
            return False
    
    def verify_webhook_signature(self, payload: bytes, sig_header: str) -> Optional[Dict]:
        """Verify webhook came from Stripe"""
        if not self.enabled or not self.webhook_secret:
            return None
        
        try:
            event = stripe.Webhook.construct_event(
                payload, sig_header, self.webhook_secret
            )
            return event
        except ValueError as e:
            print(f"Invalid payload: {e}")
            return None
        except stripe.error.SignatureVerificationError as e:
            print(f"Invalid signature: {e}")
            return None


# Singleton
_stripe_client = None

def get_stripe_client() -> StripeClient:
    """Get or create Stripe client singleton"""
    global _stripe_client
    if _stripe_client is None:
        _stripe_client = StripeClient()
    return _stripe_client
