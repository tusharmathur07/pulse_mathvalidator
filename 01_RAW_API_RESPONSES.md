# Maria — Raw API Responses (Exactly As Each Integration Returns Them)

**Client:** Maria Souza · Maria's Kitchen · Vancouver, BC
**Business type:** restaurant
**Integrations connected:** Plaid (bank) · QuickBooks (accounting) · ADP Run (payroll) · Toast (POS) · Square (POS/payments)

This is **Phase 1 — Data Ingestion**. Every block below is the raw JSON each provider's API actually returns. Pulse makes one or more API calls per provider, receives this, and then normalizes it into PostgreSQL (see `02_NORMALIZED_DB_ROWS.md`).

> Read-only. Pulse never writes back to any of these systems. It only pulls.

---

## 1. PLAID — Bank Data Layer

**Required for every customer.** Two API calls: Balance API + Transactions API.

### 1a. `POST /accounts/balance/get`

```json
{
  "accounts": [
    {
      "account_id": "blgvv1ZxK7iqK6Bd9wGGuPb4Wn5a8hZmEDQK",
      "balances": {
        "available": 23150.00,
        "current": 24300.00,
        "limit": null,
        "iso_currency_code": "CAD",
        "unofficial_currency_code": null
      },
      "mask": "0000",
      "name": "Business Chequing",
      "official_name": "TD Business Chequing Account",
      "subtype": "checking",
      "type": "depository"
    }
  ],
  "item": {
    "institution_id": "ins_3",
    "institution_name": "TD Canada Trust"
  },
  "request_id": "qk5Bxp8mfQz2RA1"
}
```

### 1b. `POST /transactions/get` (90-day window — sample of 1,847 returned)

```json
{
  "accounts": [ { "account_id": "blgvv1ZxK7iqK6Bd9wGGuPb4Wn5a8hZmEDQK" } ],
  "transactions": [
    {
      "transaction_id": "lPNjeW1nR6CDn5okmGQ6hEpMo4lLNoSrzqDje",
      "account_id": "blgvv1ZxK7iqK6Bd9wGGuPb4Wn5a8hZmEDQK",
      "amount": 15320.24,
      "iso_currency_code": "CAD",
      "date": "2026-02-28",
      "authorized_date": "2026-02-28",
      "merchant_name": "ADP PAYROLL",
      "name": "ADP PAY-BY-PAY 8829 PAYROLL",
      "payment_channel": "other",
      "pending": false,
      "personal_finance_category": {
        "primary": "TRANSFER_OUT",
        "detailed": "TRANSFER_OUT_PAYROLL"
      }
    },
    {
      "transaction_id": "Wd9zKEPnR6CDw3okmGQ6hEpMo4lLNoQrabPmx",
      "account_id": "blgvv1ZxK7iqK6Bd9wGGuPb4Wn5a8hZmEDQK",
      "amount": 14200.00,
      "iso_currency_code": "CAD",
      "date": "2026-02-26",
      "authorized_date": "2026-02-25",
      "merchant_name": "METRO PRODUCE SUPPLY",
      "name": "METRO PRODUCE SUPPLY VANCOUVER BC",
      "payment_channel": "in store",
      "pending": false,
      "personal_finance_category": {
        "primary": "FOOD_AND_DRINK",
        "detailed": "FOOD_AND_DRINK_VENDORS"
      }
    },
    {
      "transaction_id": "8gKgNVPnR6CDw3okmGQ6hEpMo4lLNoXrcd1ab",
      "account_id": "blgvv1ZxK7iqK6Bd9wGGuPb4Wn5a8hZmEDQK",
      "amount": -4900.00,
      "iso_currency_code": "CAD",
      "date": "2026-02-24",
      "authorized_date": "2026-02-24",
      "merchant_name": "SQUARE INC",
      "name": "SQUARE INC TRANSFER 240224 DEP",
      "payment_channel": "online",
      "pending": false,
      "personal_finance_category": {
        "primary": "INCOME",
        "detailed": "INCOME_OTHER_INCOME"
      }
    },
    {
      "transaction_id": " x4PpqVPnR6CDw3okmGQ6hEpMo4lLNoYref88",
      "account_id": "blgvv1ZxK7iqK6Bd9wGGuPb4Wn5a8hZmEDQK",
      "amount": 420.00,
      "iso_currency_code": "CAD",
      "date": "2026-02-20",
      "authorized_date": "2026-02-20",
      "merchant_name": "BC Hydro",
      "name": "BCHYDRO BILL PAYMENT 8841",
      "payment_channel": "online",
      "pending": false,
      "personal_finance_category": {
        "primary": "RENT_AND_UTILITIES",
        "detailed": "RENT_AND_UTILITIES_GAS_AND_ELECTRICITY"
      }
    },
    {
      "transaction_id": "mQ2RstPnR6CDw3okmGQ6hEpMo4lLNoZsgh99",
      "account_id": "blgvv1ZxK7iqK6Bd9wGGuPb4Wn5a8hZmEDQK",
      "amount": 89.00,
      "iso_currency_code": "CAD",
      "date": "2026-02-19",
      "authorized_date": "2026-02-19",
      "merchant_name": "SYSCO CANADA 4821",
      "name": "SYSCO CANADA 4821 POS PURCHASE",
      "payment_channel": "in store",
      "pending": false,
      "personal_finance_category": {
        "primary": "GENERAL_MERCHANDISE",
        "detailed": "GENERAL_MERCHANDISE_OTHER"
      }
    },
    {
      "transaction_id": "pending_tx_a91kdj2",
      "account_id": "blgvv1ZxK7iqK6Bd9wGGuPb4Wn5a8hZmEDQK",
      "amount": 312.50,
      "iso_currency_code": "CAD",
      "date": "2026-02-28",
      "authorized_date": null,
      "merchant_name": "RICExPRESS WHOLESALE",
      "name": "RICExPRESS WHOLESALE PENDING",
      "payment_channel": "in store",
      "pending": true,
      "personal_finance_category": {
        "primary": "FOOD_AND_DRINK",
        "detailed": "FOOD_AND_DRINK_VENDORS"
      }
    }
  ],
  "total_transactions": 1847,
  "request_id": "45QSn8pYxT9wKLm"
}
```

> Note: `amount` sign convention in Plaid is **positive = money leaving the account (debit)**, **negative = money entering (credit)**. This is the opposite of intuition and is inverted during normalization. The Square deposit (-4900.00) is a credit/inflow.

---

## 2. QUICKBOOKS — Accounting Layer

**OAuth 2.0. Token expires every 60 min (auto-refreshed every 55 min).** Three calls: Invoices (receivables), Bills (payables), P&L report.

### 2a. `GET /v3/company/{realmId}/query?query=SELECT * FROM Invoice`

```json
{
  "QueryResponse": {
    "Invoice": [
      {
        "Id": "312",
        "DocNumber": "INV-312",
        "TxnDate": "2026-01-26",
        "DueDate": "2026-02-25",
        "TotalAmt": 9800.00,
        "Balance": 9800.00,
        "CustomerRef": { "value": "58", "name": "Miller & Sons Catering" },
        "CurrencyRef": { "value": "CAD" },
        "EmailStatus": "EmailSent"
      },
      {
        "Id": "309",
        "DocNumber": "INV-309",
        "TxnDate": "2026-02-10",
        "DueDate": "2026-03-12",
        "TotalAmt": 3200.00,
        "Balance": 3200.00,
        "CustomerRef": { "value": "61", "name": "Westside Events Co" },
        "CurrencyRef": { "value": "CAD" },
        "EmailStatus": "EmailSent"
      },
      {
        "Id": "301",
        "DocNumber": "INV-301",
        "TxnDate": "2025-12-15",
        "DueDate": "2026-01-14",
        "TotalAmt": 5600.00,
        "Balance": 0.00,
        "CustomerRef": { "value": "58", "name": "Miller & Sons Catering" },
        "CurrencyRef": { "value": "CAD" },
        "LinkedTxn": [ { "TxnId": "PMT-880", "TxnType": "Payment" } ],
        "EmailStatus": "EmailSent"
      }
    ],
    "startPosition": 1,
    "maxResults": 3
  },
  "time": "2026-02-28T03:14:22.000-08:00"
}
```

### 2b. `GET /v3/company/{realmId}/query?query=SELECT * FROM Bill`

```json
{
  "QueryResponse": {
    "Bill": [
      {
        "Id": "BILL-77",
        "TxnDate": "2026-02-15",
        "DueDate": "2026-03-08",
        "TotalAmt": 2100.00,
        "Balance": 2100.00,
        "VendorRef": { "value": "12", "name": "Pacific Linen Service" },
        "CurrencyRef": { "value": "CAD" }
      },
      {
        "Id": "BILL-79",
        "TxnDate": "2026-02-20",
        "DueDate": "2026-03-22",
        "TotalAmt": 880.00,
        "Balance": 880.00,
        "VendorRef": { "value": "15", "name": "GreaseAway Disposal" },
        "CurrencyRef": { "value": "CAD" }
      }
    ]
  },
  "time": "2026-02-28T03:14:24.000-08:00"
}
```

### 2c. `GET /v3/company/{realmId}/reports/ProfitAndLoss` (trailing 90d)

```json
{
  "Header": {
    "ReportName": "ProfitAndLoss",
    "StartPeriod": "2025-12-01",
    "EndPeriod": "2026-02-28",
    "Currency": "CAD"
  },
  "Rows": {
    "Row": [
      { "group": "Income",
        "Summary": { "ColData": [ { "value": "Total Income" }, { "value": "80400.00" } ] } },
      { "group": "COGS",
        "Summary": { "ColData": [ { "value": "Total COGS" }, { "value": "30552.00" } ] } },
      { "group": "GrossProfit",
        "Summary": { "ColData": [ { "value": "Gross Profit" }, { "value": "49848.00" } ] } },
      { "group": "Expenses",
        "Summary": { "ColData": [ { "value": "Total Expenses" }, { "value": "44100.00" } ] } },
      { "group": "NetIncome",
        "Summary": { "ColData": [ { "value": "Net Income" }, { "value": "5748.00" } ] } }
    ]
  }
}
```

---

## 3. ADP RUN — Payroll Layer

**OAuth 2.0. Requires partner approval.** Two calls: payroll output + next pay schedule.

### 3a. `GET /payroll/v1/payroll-output`

```json
{
  "payrollOutputs": [
    {
      "payrollOutputId": "PR-2026-0228-MK",
      "payrollGroupCode": "MK1",
      "payDate": "2026-02-28",
      "checkDate": "2026-02-28",
      "payPeriod": { "startDate": "2026-02-15", "endDate": "2026-02-28" },
      "payFrequency": "biweekly",
      "employeeCount": 9,
      "payrollSummary": {
        "grossPay":      { "amount": 18400.00, "currencyCode": "CAD" },
        "netPayTotal":   { "amount": 13920.00, "currencyCode": "CAD" },
        "employerTaxes": { "amount": 1400.24,  "currencyCode": "CAD" },
        "deductions":    { "amount": 4480.00,  "currencyCode": "CAD" }
      },
      "employerTaxBreakdown": {
        "cpp": { "amount": 1094.80, "rate": 0.0595, "label": "Employer CPP" },
        "ei":  { "amount": 305.44,  "rate": 0.0166, "label": "Employer EI"  }
      }
    }
  ]
}
```

### 3b. `GET /payroll/v1/pay-schedule`

```json
{
  "paySchedule": {
    "payrollGroupCode": "MK1",
    "frequency": "biweekly",
    "nextPayDate": "2026-03-15",
    "nextCheckDate": "2026-03-15",
    "estimatedGrossPay": { "amount": 18400.00, "currencyCode": "CAD" }
  }
}
```

> `2026-03-15` is **Day 16** relative to the forecast start (`2026-02-28`). This is the payroll day the cash-gap model checks against.

---

## 4. TOAST — Restaurant POS Layer

**Partner API token.** Provides food-specific data Plaid cannot see (COGS %, net sales).

### 4a. `GET /reporting/v1/sales` (trailing week)

```json
{
  "restaurantGuid": "8a1f-mk-vancouver-2026",
  "businessDate": "2026-02-28",
  "salesSummary": {
    "netSales":   { "amount": 26800.00, "currencyCode": "CAD" },
    "grossSales": { "amount": 28950.00, "currencyCode": "CAD" },
    "voids":      { "amount": 410.00,   "currencyCode": "CAD" },
    "comps":      { "amount": 290.00,   "currencyCode": "CAD" },
    "covers": 1240,
    "checkCount": 612,
    "averageCheck": { "amount": 43.79, "currencyCode": "CAD" }
  },
  "costOfGoods": {
    "foodCost":   { "amount": 10299.00, "currencyCode": "CAD" },
    "foodCostPct": 38.43
  },
  "laborSummary": {
    "totalLaborCost": { "amount": 9650.00, "currencyCode": "CAD" },
    "laborHours": 612.5,
    "laborPct": 36.01
  }
}
```

---

## 5. SQUARE — Secondary POS / Payments Layer

**Self-serve OAuth 2.0.** Maria uses Square for counter/takeout; deposits land in the TD account (seen by Plaid as the -4900.00 credit).

### 5a. `GET /v2/payments` (trailing week, aggregated)

```json
{
  "payments": [
    {
      "id": "sq_pmt_88231",
      "created_at": "2026-02-24T19:42:00Z",
      "amount_money": { "amount": 490000, "currency": "CAD" },
      "status": "COMPLETED",
      "source_type": "CARD",
      "total_money": { "amount": 490000, "currency": "CAD" }
    }
  ],
  "cursor": null
}
```

> Square reports money in **cents** (`490000` = $4,900.00). Converted during normalization. This is the same $4,900 deposit Plaid sees hit the bank.

---

## What Happens Next

Phase 1 ends here. The pipeline now holds all of the above in memory. Phase 2 (categorization) tags every transaction, then Phase 3 (the financial model — your `pulse_math_validator.py`) consumes the normalized rows. See `02_NORMALIZED_DB_ROWS.md` for exactly how the raw JSON above becomes database rows.
