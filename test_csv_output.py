#!/usr/bin/env python3
"""
Test CSV output generation with mock data
"""

import csv
import os
from datetime import datetime, timedelta
from zendesk_watch_agent import save_alerts_to_file, CSV_COLUMNS

# Mock alerts for testing
mock_alerts = [
    {
        'vendor': 'twilio',
        'product': 'Twilio',
        'title': 'Twilio SMS API v1 Deprecation',
        'type': 'deprecation',
        'priority': 'high',
        'status': 'open',
        'ticket_id': '12345',
        'ticket_url': 'https://backbase.zendesk.com/agent/tickets/12345',
        'created_at': '2026-01-01T10:00:00Z',
        'deadline_date': '2026-12-31',
        'days_until_deadline': 127,
        'urgency_badge': 'NORMAL',
        'action_priority': 'MEDIUM',
        'impact_summary': 'SMS API v1 will be discontinued affecting all messaging functionality',
        'backbase_action_required': 'Migrate to SMS API v2 by deadline',
        'backbase_rationale': 'Current API version will no longer be supported',
        'logged_at': datetime.now().isoformat()
    },
    {
        'vendor': 'entrust',
        'product': 'Entrust',
        'title': 'Entrust SSL Certificate Requirements - Compliance Update',
        'type': 'compliance',
        'priority': 'critical',
        'status': 'open',
        'ticket_id': '12346',
        'ticket_url': 'https://backbase.zendesk.com/agent/tickets/12346',
        'created_at': '2026-08-20T14:30:00Z',
        'deadline_date': '2026-09-30',
        'days_until_deadline': 35,
        'urgency_badge': 'WARNING',
        'action_priority': 'HIGH',
        'impact_summary': 'SSL certificate compliance requirements have changed',
        'backbase_action_required': 'Update certificate configuration to meet new standards',
        'backbase_rationale': 'Non-compliance could impact payment processing and security',
        'logged_at': datetime.now().isoformat()
    }
]

# Remove old test file if it exists
test_file = "zendesk_watch_agent_alerts.csv"
if os.path.exists(test_file):
    os.remove(test_file)
    print(f"🗑️  Removed old {test_file}")

# Save mock alerts
print(f"\n📝 Saving mock alerts to {test_file}...")
save_alerts_to_file(mock_alerts)

# Read and display the CSV
print(f"\n📊 CSV Content Preview:")
print("=" * 100)
if os.path.exists(test_file):
    with open(test_file, 'r') as f:
        reader = csv.DictReader(f)
        for i, row in enumerate(reader, 1):
            print(f"\nAlert #{i}:")
            for col in CSV_COLUMNS:
                value = row.get(col, '')[:60]  # Truncate for display
                print(f"  {col:30s}: {value}")

    # Show file size
    file_size = os.path.getsize(test_file)
    print(f"\n✅ CSV file created: {test_file} ({file_size} bytes)")
else:
    print("❌ CSV file not created")
