#!/usr/bin/env python3
"""Test suite for age_status escalation in twilio_watch_agent.py"""

import sys
from datetime import datetime, timedelta
from twilio_watch_agent import escalate_alerts_by_age

def test_age_status_new():
    """Test: 0-7 days should be 'New'"""
    records = {
        "Test New Alert": {
            'category': 'Architecture Deprecation',
            'logged_at': (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S"),
            'urgency_level': 'NORMAL',
            'backbase_action_required': 'Assessment Needed'
        }
    }
    escalate_alerts_by_age(records)

    assert records["Test New Alert"]['age_status'] == 'New', f"Expected 'New', got {records['Test New Alert']['age_status']}"
    assert records["Test New Alert"]['age_days'] == 3, f"Expected 3 days, got {records['Test New Alert']['age_days']}"
    print("✅ PASS: 0-7 days threshold (New)")

def test_age_status_aging():
    """Test: 8-14 days should be 'Aging' with WARNING urgency"""
    records = {
        "Test Aging Alert": {
            'category': 'Architecture Deprecation',
            'logged_at': (datetime.now() - timedelta(days=10)).strftime("%Y-%m-%d %H:%M:%S"),
            'urgency_level': 'NORMAL',
            'backbase_action_required': 'Assessment Needed'
        }
    }
    escalate_alerts_by_age(records)

    assert records["Test Aging Alert"]['age_status'] == 'Aging', f"Expected 'Aging', got {records['Test Aging Alert']['age_status']}"
    assert records["Test Aging Alert"]['age_days'] == 10, f"Expected 10 days, got {records['Test Aging Alert']['age_days']}"
    assert records["Test Aging Alert"]['urgency_level'] == 'WARNING', f"Expected 'WARNING', got {records['Test Aging Alert']['urgency_level']}"
    assert records["Test Aging Alert"]['backbase_action_required'] == 'Code Migration Required', f"Expected 'Code Migration Required', got {records['Test Aging Alert']['backbase_action_required']}"
    print("✅ PASS: 8-14 days threshold (Aging with WARNING)")

def test_age_status_pending():
    """Test: 15-30 days should be 'Pending' with CRITICAL urgency"""
    records = {
        "Test Pending Alert": {
            'category': 'Architecture Deprecation',
            'logged_at': (datetime.now() - timedelta(days=20)).strftime("%Y-%m-%d %H:%M:%S"),
            'urgency_level': 'NORMAL',
            'backbase_action_required': 'Assessment Needed'
        }
    }
    escalate_alerts_by_age(records)

    assert records["Test Pending Alert"]['age_status'] == 'Pending', f"Expected 'Pending', got {records['Test Pending Alert']['age_status']}"
    assert records["Test Pending Alert"]['age_days'] == 20, f"Expected 20 days, got {records['Test Pending Alert']['age_days']}"
    assert records["Test Pending Alert"]['urgency_level'] == 'CRITICAL', f"Expected 'CRITICAL', got {records['Test Pending Alert']['urgency_level']}"
    assert records["Test Pending Alert"]['backbase_action_required'] == 'CRITICAL - Immediate Action', f"Expected 'CRITICAL - Immediate Action', got {records['Test Pending Alert']['backbase_action_required']}"
    print("✅ PASS: 15-30 days threshold (Pending with CRITICAL)")

def test_age_status_overdue():
    """Test: 30+ days should be 'Overdue' with OVERDUE urgency"""
    records = {
        "Test Overdue Alert": {
            'category': 'Architecture Deprecation',
            'logged_at': (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S"),
            'urgency_level': 'NORMAL',
            'backbase_action_required': 'Assessment Needed'
        }
    }
    escalate_alerts_by_age(records)

    assert records["Test Overdue Alert"]['age_status'] == 'Overdue', f"Expected 'Overdue', got {records['Test Overdue Alert']['age_status']}"
    assert records["Test Overdue Alert"]['age_days'] == 45, f"Expected 45 days, got {records['Test Overdue Alert']['age_days']}"
    assert records["Test Overdue Alert"]['urgency_level'] == 'OVERDUE', f"Expected 'OVERDUE', got {records['Test Overdue Alert']['urgency_level']}"
    assert records["Test Overdue Alert"]['backbase_action_required'] == 'OVERDUE - Action Required', f"Expected 'OVERDUE - Action Required', got {records['Test Overdue Alert']['backbase_action_required']}"
    print("✅ PASS: 30+ days threshold (Overdue with OVERDUE)")

def test_age_status_boundary_7_days():
    """Test: Exactly 7 days should be 'New' (boundary test)"""
    records = {
        "Test 7 Day Alert": {
            'category': 'Architecture Deprecation',
            'logged_at': (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d %H:%M:%S"),
            'urgency_level': 'NORMAL',
            'backbase_action_required': 'Assessment Needed'
        }
    }
    escalate_alerts_by_age(records)

    assert records["Test 7 Day Alert"]['age_status'] == 'New', f"Expected 'New' at 7 days, got {records['Test 7 Day Alert']['age_status']}"
    print("✅ PASS: 7 days boundary (New)")

def test_age_status_boundary_8_days():
    """Test: Exactly 8 days should be 'Aging' (boundary test)"""
    records = {
        "Test 8 Day Alert": {
            'category': 'Architecture Deprecation',
            'logged_at': (datetime.now() - timedelta(days=8)).strftime("%Y-%m-%d %H:%M:%S"),
            'urgency_level': 'NORMAL',
            'backbase_action_required': 'Assessment Needed'
        }
    }
    escalate_alerts_by_age(records)

    assert records["Test 8 Day Alert"]['age_status'] == 'Aging', f"Expected 'Aging' at 8 days, got {records['Test 8 Day Alert']['age_status']}"
    print("✅ PASS: 8 days boundary (Aging)")

def test_age_status_non_architecture_ignored():
    """Test: Non-Architecture items should not be escalated"""
    records = {
        "Test SRE Incident": {
            'category': 'SRE Incident',
            'logged_at': (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d %H:%M:%S"),
            'urgency_level': 'NORMAL',
            'backbase_action_required': 'Assessment Needed'
        }
    }
    escalate_alerts_by_age(records)

    # SRE incidents should not have age_status set by escalate_alerts_by_age
    assert 'age_status' not in records["Test SRE Incident"] or records["Test SRE Incident"].get('age_status') is None, "SRE incidents should not be escalated"
    print("✅ PASS: Non-Architecture categories ignored")

def test_age_status_invalid_date():
    """Test: Invalid date format should set age_status to 'Unknown'"""
    records = {
        "Test Invalid Date": {
            'category': 'Architecture Deprecation',
            'logged_at': 'invalid-date-format',
            'urgency_level': 'NORMAL',
            'backbase_action_required': 'Assessment Needed'
        }
    }
    escalate_alerts_by_age(records)

    assert records["Test Invalid Date"]['age_status'] == 'Unknown', f"Expected 'Unknown', got {records['Test Invalid Date']['age_status']}"
    assert records["Test Invalid Date"]['age_days'] == 'N/A', f"Expected 'N/A', got {records['Test Invalid Date']['age_days']}"
    print("✅ PASS: Invalid date handling")

def test_multiple_records():
    """Test: Multiple records with different ages"""
    records = {
        "Alert 1": {
            'category': 'Architecture Deprecation',
            'logged_at': (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d %H:%M:%S"),
            'urgency_level': 'NORMAL',
            'backbase_action_required': 'Assessment Needed'
        },
        "Alert 2": {
            'category': 'Architecture Deprecation',
            'logged_at': (datetime.now() - timedelta(days=12)).strftime("%Y-%m-%d %H:%M:%S"),
            'urgency_level': 'NORMAL',
            'backbase_action_required': 'Assessment Needed'
        },
        "Alert 3": {
            'category': 'Architecture Deprecation',
            'logged_at': (datetime.now() - timedelta(days=25)).strftime("%Y-%m-%d %H:%M:%S"),
            'urgency_level': 'NORMAL',
            'backbase_action_required': 'Assessment Needed'
        }
    }
    escalate_alerts_by_age(records)

    assert records["Alert 1"]['age_status'] == 'New'
    assert records["Alert 2"]['age_status'] == 'Aging'
    assert records["Alert 3"]['age_status'] == 'Pending'
    print("✅ PASS: Multiple records with different ages")

def main():
    print("=" * 60)
    print("Testing age_status escalation functionality")
    print("=" * 60)

    tests = [
        test_age_status_new,
        test_age_status_aging,
        test_age_status_pending,
        test_age_status_overdue,
        test_age_status_boundary_7_days,
        test_age_status_boundary_8_days,
        test_age_status_non_architecture_ignored,
        test_age_status_invalid_date,
        test_multiple_records
    ]

    passed = 0
    failed = 0

    for test in tests:
        try:
            test()
            passed += 1
        except AssertionError as e:
            print(f"❌ FAIL: {test.__name__}")
            print(f"   {e}")
            failed += 1
        except Exception as e:
            print(f"❌ ERROR: {test.__name__}")
            print(f"   {type(e).__name__}: {e}")
            failed += 1

    print("\n" + "=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print("=" * 60)

    return 0 if failed == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
