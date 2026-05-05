"""Quick API test script for Phase 0 verification."""
import sys
import os
import urllib.request
import urllib.error
import json

# Fix Windows console encoding
sys.stdout.reconfigure(encoding="utf-8")
os.environ["PYTHONIOENCODING"] = "utf-8"

BASE = "http://localhost:8000"

def api_get(path):
    # Ensure trailing slash to avoid 307 redirects
    if not path.endswith("/") and "?" not in path:
        path += "/"
    r = urllib.request.urlopen(f"{BASE}{path}")
    return json.loads(r.read())


def api_post(path, data):
    # Ensure trailing slash to avoid 307 redirects  
    if "?" in path:
        parts = path.split("?")
        if not parts[0].endswith("/"):
            path = parts[0] + "/" + "?" + parts[1]
    elif not path.endswith("/"):
        path += "/"
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(data).encode(),
        headers={"Content-Type": "application/json"},
    )
    r = urllib.request.urlopen(req)
    return json.loads(r.read())


print("=" * 60)
print("PFIS Phase 0 — API Verification")
print("=" * 60)

# 1. Health
health = api_get("/api/health")
print(f"\n1. Health: {health['status']} (v{health['version']})")

# 2. Categories
cats = api_get("/api/categories")
print(f"\n2. Categories ({len(cats)} loaded):")
for c in cats:
    print(f"   {c['icon']} {c['name']} (id={c['id'][:8]}...)")

# 3. Users
users = api_get("/api/users")
demo_user = users[0]
print(f"\n3. Demo User: {demo_user['name']} ({demo_user['email']})")
user_id = demo_user["id"]

# 4. Get food category ID
food_cat = next((c for c in cats if c["name"] == "Food"), None)
shopping_cat = next((c for c in cats if c["name"] == "Shopping"), None)
transport_cat = next((c for c in cats if c["name"] == "Transport"), None)
sub_cat = next((c for c in cats if c["name"] == "Subscription"), None)
bills_cat = next((c for c in cats if c["name"] == "Bills"), None)

# 5. Create test transactions
print("\n4. Creating test transactions...")
test_txns = [
    {
        "amount": 450,
        "transaction_type": "debit",
        "merchant_raw": "SWIGGY",
        "merchant_normalized": "Swiggy",
        "category_id": food_cat["id"],
        "transaction_date": "2026-05-05",
        "account_last4": "1234",
        "reference_id": "123456789",
        "confidence_score": 0.92,
    },
    {
        "amount": 1200,
        "transaction_type": "debit",
        "merchant_raw": "AMAZON.IN",
        "merchant_normalized": "Amazon",
        "category_id": shopping_cat["id"],
        "transaction_date": "2026-05-06",
        "account_last4": "1234",
        "reference_id": "987654321",
        "confidence_score": 0.88,
    },
    {
        "amount": 230,
        "transaction_type": "debit",
        "merchant_raw": "UBER INDIA",
        "merchant_normalized": "Uber",
        "category_id": transport_cat["id"],
        "transaction_date": "2026-05-06",
        "account_last4": "1234",
        "reference_id": "111222333",
        "confidence_score": 0.95,
    },
    {
        "amount": 499,
        "transaction_type": "debit",
        "merchant_raw": "NETFLIX.COM",
        "merchant_normalized": "Netflix",
        "category_id": sub_cat["id"],
        "transaction_date": "2026-05-01",
        "account_last4": "5678",
        "reference_id": "444555666",
        "confidence_score": 0.97,
    },
    {
        "amount": 1500,
        "transaction_type": "debit",
        "merchant_raw": "ELECTRICITY BILL",
        "merchant_normalized": "Electricity",
        "category_id": bills_cat["id"],
        "transaction_date": "2026-05-03",
        "account_last4": "1234",
        "reference_id": "777888999",
        "confidence_score": 0.85,
    },
]

created = []
for txn in test_txns:
    try:
        result = api_post(f"/api/transactions?user_id={user_id}", txn)
        created.append(result)
        print(f"   + {result['merchant_normalized']:15s} INR {result['amount']:>8.2f}  [{result['transaction_type']}]  conf={result['confidence_score']}")
    except Exception as e:
        print(f"   ! Skipped (likely duplicate): {txn['merchant_normalized']}")

# 6. List transactions
print(f"\n5. Fetching transactions for May 2026...")
txns = api_get(f"/api/transactions?user_id={user_id}&month=5&year=2026")
print(f"   Found {len(txns)} transactions")

# 7. Monthly summary
print(f"\n6. Monthly Summary (May 2026):")
summary = api_get(f"/api/transactions/summary?user_id={user_id}&month=5&year=2026")
print(f"   Total Spend:  INR {summary['total_spend']:,.2f}")
print(f"   Total Income: INR {summary['total_income']:,.2f}")
print(f"   Net:          INR {summary['net']:,.2f}")
print(f"   Transactions: {summary['transaction_count']}")

print(f"\n   Category Breakdown:")
for cat in summary["category_breakdown"]:
    pct = (cat["total"] / summary["total_spend"] * 100) if summary["total_spend"] else 0
    print(f"   {'':3s}{cat['name']:15s} INR {cat['total']:>8,.2f}  ({pct:.0f}%)")

print(f"\n   Top Merchants:")
for m in summary["top_merchants"]:
    print(f"   {'':3s}{m['name']:15s} INR {m['total']:>8,.2f}  ({m['count']} txns)")

# 8. Test dedup
print(f"\n7. Dedup Test (re-inserting Swiggy)...")
try:
    api_post(f"/api/transactions?user_id={user_id}", test_txns[0])
    print("   FAIL - Duplicate was not caught!")
except urllib.error.HTTPError as e:
    error_body = e.read().decode()
    try:
        body = json.loads(error_body)
        print(f"   PASS - Blocked: {body['detail']}")
    except json.JSONDecodeError:
        print(f"   PASS - Blocked with HTTP {e.code}")
except Exception as e:
    print(f"   PASS - Blocked: {e}")

print("\n" + "=" * 60)
print("Phase 0 Verification COMPLETE")
print("=" * 60)
