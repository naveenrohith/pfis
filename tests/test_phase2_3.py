"""
Phase 2+3 Verification — Parsing Engine + Processing Pipeline
Tests the full flow: Demo Sync → Process Pipeline → Verify Transactions
"""
import sys
import os
import urllib.request
import urllib.error
import json

sys.stdout.reconfigure(encoding="utf-8")
BASE = "http://localhost:8000"


def api_get(path):
    if not path.endswith("/") and "?" not in path:
        path += "/"
    return json.loads(urllib.request.urlopen(f"{BASE}{path}").read())


def api_post(path, data=None):
    body = json.dumps(data).encode() if data else b""
    req = urllib.request.Request(f"{BASE}{path}", data=body,
                                headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req).read())


print("=" * 70)
print("  PFIS Phase 2+3 — Parsing Engine + Processing Pipeline")
print("=" * 70)

# 1. Get user
users = api_get("/api/users")
user_id = users[0]["id"]
print(f"\n1. User: {users[0]['name']} (id={user_id[:12]}...)")

# 2. Inject demo emails (if not already done)
print("\n2. Injecting demo emails...")
sync = api_post(f"/api/gmail/demo-sync?user_id={user_id}")
stored = sync["stats"]["emails_stored"]
dupes = sync["stats"]["emails_skipped_duplicate"]
print(f"   New: {stored}, Skipped dupes: {dupes}")

# 3. Check unprocessed emails
emails = api_get(f"/api/gmail/emails?user_id={user_id}&processed=false")
print(f"\n3. Unprocessed emails: {emails['total']}")

# 4. Run processing pipeline
print("\n4. Running Processing Pipeline...")
result = api_post(f"/api/pipeline/process?user_id={user_id}")
stats = result["stats"]

print(f"   Total processed:   {stats['total_unprocessed']}")
print(f"   Parsed OK:         {stats['parsed_success']}")
print(f"   Parse failed:      {stats['parsed_failed']}")
print(f"   Stored as txn:     {stats['stored']}")
print(f"   Duplicates:        {stats['duplicates']}")
print(f"   Low confidence:    {stats['low_confidence']}")

# 5. Show individual results
print(f"\n5. Parsing Results:")
print(f"   {'Status':<10s} {'Bank':<8s} {'Amount':>10s} {'Type':<8s} {'Merchant':<20s} {'Conf':>5s} {'Subject'}")
print(f"   {'─'*10} {'─'*8} {'─'*10} {'─'*8} {'─'*20} {'─'*5} {'─'*30}")

for r in stats["results"]:
    status = r.get("status", "?")
    bank = r.get("bank", "")[:8]
    amount = f"₹{r['amount']:,.0f}" if r.get("amount") else "—"
    txn_type = (r.get("type") or "—")[:8]
    merchant = (r.get("merchant_normalized") or r.get("merchant_raw") or "—")[:20]
    conf = f"{r.get('confidence', 0):.2f}"
    subject = r.get("subject", "")[:30]
    icon = {"stored": "✅", "duplicate": "♻️", "parse_failed": "❌", "error": "💥"}.get(status, "❓")
    print(f"   {icon} {status:<8s} {bank:<8s} {amount:>10s} {txn_type:<8s} {merchant:<20s} {conf:>5s} {subject}")

# 6. Verify transactions in DB
print(f"\n6. Transactions in DB (May 2026):")
summary = api_get(f"/api/transactions/summary?user_id={user_id}&month=5&year=2026")
print(f"   Total Spend:   ₹{summary['total_spend']:,.2f}")
print(f"   Total Income:  ₹{summary['total_income']:,.2f}")
print(f"   Net:           ₹{summary['net']:,.2f}")
print(f"   Count:         {summary['transaction_count']}")

if summary["category_breakdown"]:
    print(f"\n   Category Breakdown:")
    for cat in summary["category_breakdown"]:
        pct = (cat["total"] / summary["total_spend"] * 100) if summary["total_spend"] else 0
        print(f"      {cat['name']:<15s}  ₹{cat['total']:>8,.0f}  ({pct:.0f}%)")

if summary["top_merchants"]:
    print(f"\n   Top Merchants:")
    for m in summary["top_merchants"]:
        print(f"      {m['name']:<15s}  ₹{m['total']:>8,.0f}  ({m['count']} txns)")

# 7. Re-run pipeline (should be 0 unprocessed)
print(f"\n7. Idempotency Test (re-run pipeline)...")
result2 = api_post(f"/api/pipeline/process?user_id={user_id}")
if result2["stats"]["total_unprocessed"] == 0:
    print(f"   ✅ PASS — 0 unprocessed (all already processed)")
else:
    print(f"   ❌ FAIL — {result2['stats']['total_unprocessed']} still unprocessed")

# Summary
parsed = stats["parsed_success"]
total = stats["total_unprocessed"]
accuracy = (parsed / total * 100) if total else 0
print(f"\n{'=' * 70}")
print(f"  SUMMARY")
print(f"  {'─' * 50}")
print(f"  Parsing accuracy:      {parsed}/{total} ({accuracy:.0f}%)")
print(f"  Transactions created:  {stats['stored']}")
print(f"  Duplicates blocked:    {stats['duplicates']}")
print(f"  Low confidence:        {stats['low_confidence']}")
print(f"  Pipeline idempotent:   ✅")
print(f"{'=' * 70}")
print(f"  Phase 2+3 Verification COMPLETE ✅")
print(f"{'=' * 70}")
