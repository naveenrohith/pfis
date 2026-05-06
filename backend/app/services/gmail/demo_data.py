"""
Demo Email Data
Sample bank transaction emails for testing the pipeline without real Gmail.

These are realistic Indian bank email formats used to:
1. Test the email filter (classification)
2. Test the parser (Phase 2)
3. Verify end-to-end pipeline
"""

SAMPLE_EMAILS = [
    # ─── HDFC Bank ───
    {
        "sender": "alerts@hdfcbank.net",
        "subject": "Alert : Update on your HDFC Bank A/c XX1234",
        "body": (
            "Dear Customer, Rs. 450.00 has been debited from your A/c XX1234 "
            "on 05-05-2026 by a UPI txn. UPI Ref No 412345678901. "
            "If not done by you, call 18002586161. - HDFC Bank"
        ),
    },
    {
        "sender": "alerts@hdfcbank.net",
        "subject": "Alert : Update on your HDFC Bank A/c XX1234",
        "body": (
            "Dear Customer, Rs.1,200.00 has been debited from A/c XX1234 on 03-05-2026 "
            "at AMAZON PAY INDIA PV via POS. Avl bal: Rs.45,670.00. "
            "If not done by you, call 18002586161. - HDFC Bank"
        ),
    },
    {
        "sender": "alerts@hdfcbank.net",
        "subject": "Alert : Money received in your HDFC Bank A/c",
        "body": (
            "Dear Customer, Rs.25,000.00 has been credited to your A/c XX1234 "
            "on 01-05-2026 by NEFT Ref No SBIN123456789012. "
            "Avl bal: Rs.70,670.00. - HDFC Bank"
        ),
    },
    # ─── SBI ───
    {
        "sender": "alerts@sbi.co.in",
        "subject": "SBI Debit Alert",
        "body": (
            "Your a/c no. XXXXXXXX1234 is debited for Rs.230.00 on 04-05-2026 "
            "(UPI Ref No 412345678902) and a/c XXXXXXXX5678 credited. "
            "If not done by you, please contact your branch. - SBI"
        ),
    },
    {
        "sender": "alerts@sbi.co.in",
        "subject": "SBI Credit Alert",
        "body": (
            "Your a/c no. XXXXXXXX1234 is credited by Rs.15,000.00 on 02-05-2026 "
            "(NEFT Ref No ICIC123456789). Avl Bal Rs.85,670.00 - SBI"
        ),
    },
    # ─── ICICI ───
    {
        "sender": "alerts@icicibank.com",
        "subject": "ICICI Bank Transaction Alert",
        "body": (
            "Dear Customer, INR 499.00 has been debited from your ICICI Bank "
            "Account XX5678 towards NETFLIX.COM on 01-05-2026. "
            "The available balance is INR 34,560.00. - ICICI Bank"
        ),
    },
    {
        "sender": "alerts@icicibank.com",
        "subject": "ICICI Bank UPI Alert",
        "body": (
            "Dear Customer, your ICICI Bank Acct XX5678 has been debited with "
            "INR 850.00 on 05-05-2026 towards UPI-SWIGGY-swiggy@axisbank-UTIB. "
            "UPI Ref: 412345678903. Avl Bal: INR 33,710.00"
        ),
    },
    # ─── Axis Bank ───
    {
        "sender": "alerts@axisbank.com",
        "subject": "Axis Bank Debit Card Transaction",
        "body": (
            "INR 1,500.00 spent on your Axis Bank Debit Card ending 9012 "
            "at BESCOM BANGALORE on 03-05-2026. Available limit: INR 48,500.00. "
            "If not you, call 18004195555."
        ),
    },
    # ─── Kotak ───
    {
        "sender": "alerts@kotak.com",
        "subject": "Kotak Bank Alert",
        "body": (
            "Rs. 799.00 debited from your Kotak Bank A/c X1234 on 02-05-2026 "
            "for UBER INDIA via UPI. Ref No: 412345678904. "
            "Balance: Rs. 22,450.00. - Kotak Mahindra Bank"
        ),
    },
    # ─── UPI Apps ───
    {
        "sender": "noreply@paytm.com",
        "subject": "Payment Successful",
        "body": (
            "You have successfully paid Rs. 350.00 to BIGBASKET via UPI on 04-05-2026. "
            "UPI Transaction ID: 412345678905. Your wallet balance: Rs. 1,200.00. - Paytm"
        ),
    },
    {
        "sender": "noreply@phonepe.com",
        "subject": "PhonePe Payment Successful",
        "body": (
            "Payment of Rs.199.00 to SPOTIFY INDIA was successful on 01-05-2026. "
            "Transaction ID: PHO412345678906. - PhonePe"
        ),
    },
    # ─── Credit Card ───
    {
        "sender": "creditcard@hdfcbank.net",
        "subject": "HDFC Credit Card Transaction Alert",
        "body": (
            "Thank you for using your HDFC Bank Credit Card ending 7890. "
            "Rs.3,499.00 has been charged for FLIPKART INTERNET on 05-05-2026. "
            "Available Credit Limit: Rs.1,45,600.00"
        ),
    },
    # ─── OTP (should be filtered OUT) ───
    {
        "sender": "alerts@hdfcbank.net",
        "subject": "HDFC Bank OTP",
        "body": (
            "Dear Customer, Your OTP for online transaction is 4567. "
            "Do not share with anyone. Valid for 5 minutes. - HDFC Bank"
        ),
    },
    # ─── Promotion (should be filtered OUT) ───
    {
        "sender": "alerts@icicibank.com",
        "subject": "Exclusive Offer for You!",
        "body": (
            "Congratulations! You have been selected for a pre-approved personal loan "
            "of Rs.5,00,000 at attractive interest rates. Limited time offer! "
            "Apply now at icicibank.com. T&C apply."
        ),
    },
    # ─── Refund ───
    {
        "sender": "alerts@hdfcbank.net",
        "subject": "Alert : Refund credited to your HDFC Bank A/c",
        "body": (
            "Dear Customer, Rs.599.00 has been credited to your A/c XX1234 "
            "on 04-05-2026 as refund from AMAZON PAY. "
            "Avl bal: Rs.46,269.00. - HDFC Bank"
        ),
    },
]
