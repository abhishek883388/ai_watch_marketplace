#!/usr/bin/env python3
"""
Unit tests for zendesk_watch_agent.py - validates core functions
"""

import json
import sys
from datetime import datetime, timedelta
from zendesk_watch_agent import (
    contains_vendor_keyword,
    contains_alert_keyword,
    extract_deadline_from_text,
    calculate_days_until_deadline,
    parse_zendesk_ticket
)


def test_vendor_keywords():
    """Test vendor keyword detection."""
    print("Testing vendor keyword detection...")
    assert contains_vendor_keyword("Twilio SMS deprecation") == "twilio"
    assert contains_vendor_keyword("SendGrid messaging update") == "twilio"
    assert contains_vendor_keyword("Entrust card payment") == "entrust"
    assert contains_vendor_keyword("Jumio KYC verification") == "jumio"
    assert contains_vendor_keyword("Some random text") is None
    print("✅ Vendor keyword detection working")


def test_alert_keywords():
    """Test alert keyword detection."""
    print("\nTesting alert keyword detection...")
    assert contains_alert_keyword("API deprecation notice") == True
    assert contains_alert_keyword("Security vulnerability found") == True
    assert contains_alert_keyword("Compliance requirement") == True
    assert contains_alert_keyword("End of life - EOL") == True
    assert contains_alert_keyword("Upgrade required urgent") == True
    assert contains_alert_keyword("Just a normal ticket") == False
    print("✅ Alert keyword detection working")


def test_deadline_extraction():
    """Test deadline date extraction from text."""
    print("\nTesting deadline extraction...")

    # ISO format
    text1 = "The deadline is 2026-12-31 for migration"
    deadline1 = extract_deadline_from_text(text1)
    assert deadline1 == "2026-12-31", f"Expected 2026-12-31, got {deadline1}"

    # MM/DD/YYYY format
    text2 = "Please upgrade by 12/31/2026"
    deadline2 = extract_deadline_from_text(text2)
    assert deadline2 == "12/31/2026", f"Expected 12/31/2026, got {deadline2}"

    # Month name format
    text3 = "Sunset date: December 31, 2026"
    deadline3 = extract_deadline_from_text(text3)
    assert deadline3 is not None, "Should extract December 31, 2026"

    # No deadline
    text4 = "This is just a regular update"
    deadline4 = extract_deadline_from_text(text4)
    assert deadline4 is None, "Should return None when no deadline found"

    print("✅ Deadline extraction working")


def test_urgency_calculation():
    """Test urgency badge calculation."""
    print("\nTesting urgency calculation...")

    # OVERDUE
    past_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
    days, badge = calculate_days_until_deadline(past_date)
    assert badge == "OVERDUE", f"Expected OVERDUE, got {badge}"
    assert days < 0

    # CRITICAL (0-7 days)
    critical_date = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
    days, badge = calculate_days_until_deadline(critical_date)
    assert badge == "CRITICAL", f"Expected CRITICAL, got {badge}"
    assert 0 <= days <= 7

    # WARNING (7-30 days)
    warning_date = (datetime.now() + timedelta(days=15)).strftime("%Y-%m-%d")
    days, badge = calculate_days_until_deadline(warning_date)
    assert badge == "WARNING", f"Expected WARNING, got {badge}"
    assert 7 < days <= 30

    # NORMAL (> 30 days)
    normal_date = (datetime.now() + timedelta(days=60)).strftime("%Y-%m-%d")
    days, badge = calculate_days_until_deadline(normal_date)
    assert badge == "NORMAL", f"Expected NORMAL, got {badge}"
    assert days > 30

    # Unknown
    days, badge = calculate_days_until_deadline(None)
    assert badge == "UNKNOWN"

    print("✅ Urgency calculation working")


def test_ticket_parsing():
    """Test ticket parsing function."""
    print("\nTesting ticket parsing...")

    mock_ticket = {
        'id': 12345,
        'subject': 'Twilio API Deprecation - SMS v1 sunset',
        'description': 'The Twilio SMS v1 API will be sunset on 2026-12-31. Critical security update required.',
        'created_at': '2026-01-01T10:00:00Z',
        'updated_at': '2026-08-26T15:00:00Z',
        'priority': 'high',
        'status': 'open',
        'tags': ['vendor-alert', 'critical'],
        'detected_vendor': 'twilio'
    }

    parsed = parse_zendesk_ticket(mock_ticket)

    assert parsed['vendor'] == 'twilio'
    assert parsed['ticket_id'] == 12345
    assert parsed['alert_type'] == 'deprecation'
    assert parsed['deadline_date'] == '2026-12-31'
    assert parsed['days_until_deadline'] is not None
    assert parsed['urgency_badge'] in ['NORMAL', 'WARNING', 'CRITICAL', 'OVERDUE']
    assert parsed['ticket_url'] == 'https://backbase.zendesk.com/agent/tickets/12345'

    print("✅ Ticket parsing working")


def test_complete_flow():
    """Test complete flow with mock data."""
    print("\nTesting complete alert processing flow...")

    # Simulate filtering and processing
    test_tickets = [
        {
            'id': 1,
            'subject': 'Twilio SMS API v1 deprecation',
            'description': 'SMS v1 sunset on 2026-12-31. Action required.',
            'created_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-08-26T00:00:00Z',
            'priority': 'high',
            'status': 'open',
            'tags': [],
            'detected_vendor': 'twilio'
        },
        {
            'id': 2,
            'subject': 'Entrust payment certificate upgrade',
            'description': 'SSL certificate deadline: 2026-06-30. Critical compliance requirement.',
            'created_at': '2026-01-01T00:00:00Z',
            'updated_at': '2026-08-26T00:00:00Z',
            'priority': 'critical',
            'status': 'open',
            'tags': [],
            'detected_vendor': 'entrust'
        },
    ]

    alerts = []
    for ticket in test_tickets:
        parsed = parse_zendesk_ticket(ticket)
        alert = {
            'vendor': parsed['vendor'],
            'product': parsed['vendor'].capitalize(),
            'title': parsed['subject'],
            'type': parsed['alert_type'],
            'ticket_id': parsed['ticket_id'],
            'ticket_url': parsed['ticket_url'],
            'created_at': parsed['created_at'],
            'deadline_date': parsed['deadline_date'],
            'days_until_deadline': parsed['days_until_deadline'],
            'urgency_badge': parsed['urgency_badge'],
            'logged_at': datetime.now().isoformat()
        }
        alerts.append(alert)

    assert len(alerts) == 2
    assert alerts[0]['vendor'] == 'twilio'
    assert alerts[1]['vendor'] == 'entrust'
    assert alerts[0]['type'] == 'deprecation'
    assert alerts[1]['type'] == 'compliance'

    print("✅ Complete flow working")


def main():
    """Run all tests."""
    print("=" * 60)
    print("🧪 Testing Zendesk Watch Agent")
    print("=" * 60)

    try:
        test_vendor_keywords()
        test_alert_keywords()
        test_deadline_extraction()
        test_urgency_calculation()
        test_ticket_parsing()
        test_complete_flow()

        print("\n" + "=" * 60)
        print("✅ All tests passed!")
        print("=" * 60)
        return 0
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
