-- Stripe Subscription Schema (Add to existing Supabase)

-- User subscriptions table
CREATE TABLE user_subscriptions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE UNIQUE,
    stripe_customer_id TEXT UNIQUE,
    stripe_subscription_id TEXT UNIQUE,
    status TEXT NOT NULL, -- trialing, active, canceled, past_due, unpaid
    trial_end TIMESTAMP WITH TIME ZONE,
    current_period_start TIMESTAMP WITH TIME ZONE,
    current_period_end TIMESTAMP WITH TIME ZONE,
    cancel_at_period_end BOOLEAN DEFAULT false,
    canceled_at TIMESTAMP WITH TIME ZONE,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Indexes for performance
CREATE INDEX idx_user_subscriptions_user_id ON user_subscriptions(user_id);
CREATE INDEX idx_user_subscriptions_stripe_customer ON user_subscriptions(stripe_customer_id);
CREATE INDEX idx_user_subscriptions_status ON user_subscriptions(status);

-- Enable RLS
ALTER TABLE user_subscriptions ENABLE ROW LEVEL SECURITY;

-- Users can only see their own subscription
CREATE POLICY "Users can view own subscription" ON user_subscriptions
    FOR SELECT USING (auth.uid() = user_id);

-- Function to check if user has active access
CREATE OR REPLACE FUNCTION user_has_access(p_user_id UUID)
RETURNS BOOLEAN AS $$
DECLARE
    sub_status TEXT;
    trial_end_date TIMESTAMP WITH TIME ZONE;
    period_end_date TIMESTAMP WITH TIME ZONE;
BEGIN
    SELECT status, trial_end, current_period_end
    INTO sub_status, trial_end_date, period_end_date
    FROM user_subscriptions 
    WHERE user_id = p_user_id;
    
    -- No subscription record = no access
    IF sub_status IS NULL THEN
        RETURN false;
    END IF;
    
    -- Active subscription = access
    IF sub_status = 'active' THEN
        RETURN true;
    END IF;
    
    -- In trial period = access
    IF sub_status = 'trialing' AND trial_end_date > NOW() THEN
        RETURN true;
    END IF;
    
    -- Past due but still in billing period = grace period access
    IF sub_status = 'past_due' AND period_end_date > NOW() THEN
        RETURN true;
    END IF;
    
    -- Everything else = no access
    RETURN false;
END;
$$ LANGUAGE plpgsql;

-- Function to get subscription details
CREATE OR REPLACE FUNCTION get_user_subscription(p_user_id UUID)
RETURNS TABLE (
    has_access BOOLEAN,
    status TEXT,
    trial_ends_at TIMESTAMP WITH TIME ZONE,
    period_ends_at TIMESTAMP WITH TIME ZONE,
    cancel_at_period_end BOOLEAN,
    days_until_charge INTEGER
) AS $$
BEGIN
    RETURN QUERY
    SELECT 
        user_has_access(p_user_id) as has_access,
        us.status,
        us.trial_end as trial_ends_at,
        us.current_period_end as period_ends_at,
        us.cancel_at_period_end,
        CASE 
            WHEN us.trial_end IS NOT NULL AND us.trial_end > NOW() 
            THEN EXTRACT(DAY FROM us.trial_end - NOW())::INTEGER
            ELSE 0
        END as days_until_charge
    FROM user_subscriptions us
    WHERE us.user_id = p_user_id;
END;
$$ LANGUAGE plpgsql;
