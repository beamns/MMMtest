#!/usr/bin/env python3
"""
Test Supabase and Stripe Connections
"""

import os
import sys

print("=" * 60)
print("TESTING DATABASE & PAYMENT CONNECTIONS")
print("=" * 60)

# Test 1: Environment Variables
print("\n1. ENVIRONMENT VARIABLES:")
print("-" * 60)

supabase_url = os.getenv('SUPABASE_URL')
supabase_key = os.getenv('SUPABASE_KEY')
stripe_key = os.getenv('STRIPE_SECRET_KEY')

print(f"✓ SUPABASE_URL: {'✅ SET' if supabase_url else '❌ MISSING'}")
print(f"✓ SUPABASE_KEY: {'✅ SET' if supabase_key else '❌ MISSING'}")
print(f"✓ STRIPE_SECRET_KEY: {'✅ SET' if stripe_key else '❌ MISSING'}")

if supabase_url:
    print(f"  URL: {supabase_url[:30]}...")
if stripe_key:
    print(f"  Stripe: {stripe_key[:20]}...")

# Test 2: Import Modules
print("\n2. MODULE IMPORTS:")
print("-" * 60)

try:
    from supabase_client import get_database
    print("✅ supabase_client imported")
except Exception as e:
    print(f"❌ supabase_client import failed: {e}")
    sys.exit(1)

try:
    from stripe_client import get_stripe_client
    print("✅ stripe_client imported")
except Exception as e:
    print(f"❌ stripe_client import failed: {e}")
    sys.exit(1)

try:
    from auth_manager import AuthManager
    print("✅ auth_manager imported")
except Exception as e:
    print(f"❌ auth_manager import failed: {e}")
    sys.exit(1)

# Test 3: Initialize Clients
print("\n3. CLIENT INITIALIZATION:")
print("-" * 60)

try:
    db = get_database()
    print("✅ Supabase database client initialized")
except Exception as e:
    print(f"❌ Supabase init failed: {e}")
    db = None

try:
    stripe = get_stripe_client()
    print("✅ Stripe client initialized")
except Exception as e:
    print(f"❌ Stripe init failed: {e}")
    stripe = None

if db and stripe:
    try:
        auth = AuthManager(db, stripe)
        print("✅ Auth manager initialized")
    except Exception as e:
        print(f"❌ Auth manager init failed: {e}")
        auth = None
else:
    print("⚠️  Skipping auth manager (missing dependencies)")
    auth = None

# Test 4: Database Connection Test
print("\n4. DATABASE CONNECTION TEST:")
print("-" * 60)

if db and supabase_url and supabase_key:
    try:
        # Try to query something simple
        result = db.client.table('users').select('id').limit(1).execute()
        print(f"✅ Database connection successful!")
        print(f"   Received response from Supabase")
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        print(f"   Make sure:")
        print(f"   1. SUPABASE_URL is correct")
        print(f"   2. SUPABASE_KEY is valid")
        print(f"   3. RLS policies allow access")
else:
    print("⚠️  Skipping (missing credentials)")

# Test 5: Stripe Connection Test
print("\n5. STRIPE CONNECTION TEST:")
print("-" * 60)

if stripe and stripe_key:
    try:
        # Try to retrieve account info
        import stripe as stripe_lib
        stripe_lib.api_key = stripe_key
        account = stripe_lib.Account.retrieve()
        print(f"✅ Stripe connection successful!")
        print(f"   Account ID: {account.id}")
    except Exception as e:
        print(f"❌ Stripe connection failed: {e}")
        print(f"   Make sure STRIPE_SECRET_KEY is valid")
else:
    print("⚠️  Skipping (missing API key)")

# Summary
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)

if supabase_url and supabase_key:
    print("✅ Supabase: CONFIGURED")
else:
    print("❌ Supabase: NOT CONFIGURED")
    print("   Set SUPABASE_URL and SUPABASE_KEY in environment")

if stripe_key:
    print("✅ Stripe: CONFIGURED")
else:
    print("❌ Stripe: NOT CONFIGURED")
    print("   Set STRIPE_SECRET_KEY in environment")

print("\n" + "=" * 60)
print("Ready to deploy with database & payments!" if (supabase_url and supabase_key and stripe_key) else "⚠️  Missing configuration - set environment variables")
print("=" * 60)
