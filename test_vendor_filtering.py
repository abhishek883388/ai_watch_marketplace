#!/usr/bin/env python3
"""
Test script to verify vendor filtering logic works correctly
and doesn't generate false positives.
"""

import sys
sys.path.insert(0, '/Users/abhisheks/Documents/ai_watch_marketplace')

from zendesk_watch_agent import (
    contains_vendor_keyword,
    contains_alert_keyword,
    get_vendor_from_tags,
    filter_vendor_alert_tickets,
    MONITORED_VENDORS
)

# Test data: tickets that should be INCLUDED
valid_tickets = [
    {
        'id': 1,
        'subject': 'Twilio SMS API Deprecation Notice',
        'description': 'The Twilio SMS API will be deprecated on 2026-12-31',
        'tags': ['twilio', 'api'],
        'expected': True,
        'reason': 'Has twilio tag + deprecation keyword'
    },
    {
        'id': 2,
        'subject': 'Entrust Certificate Renewal Critical',
        'description': 'Your SSL certificate expires on 2026-09-15. Action required immediately.',
        'tags': ['entrust', 'security'],
        'expected': True,
        'reason': 'Has entrust tag + critical/expires keywords'
    },
    {
        'id': 3,
        'subject': 'Jumio KYC Identity Verification Upgrade',
        'description': 'Breaking change: New identity verification API endpoints required by 2026-10-01',
        'tags': ['jumio'],
        'expected': True,
        'reason': 'Has jumio tag + breaking change keyword'
    },
]

# Test data: tickets that should be EXCLUDED (false positives)
noise_tickets = [
    {
        'id': 101,
        'subject': 'QuickBooks Integration Setup',
        'description': 'Help with QuickBooks and Quicken Express Web Connect integration',
        'tags': ['quickbooks', 'integration'],
        'expected': False,
        'reason': 'No monitored vendor tag, unrelated to alert'
    },
    {
        'id': 102,
        'subject': 'General Security Meeting',
        'description': 'Team meeting about security protocols and payment procedures',
        'tags': ['general', 'meeting'],
        'expected': False,
        'reason': 'No vendor tag, generic security mention'
    },
    {
        'id': 103,
        'subject': 'Payment Processing Update',
        'description': 'System upgrade for internal payment processing tomorrow',
        'tags': ['internal', 'system'],
        'expected': False,
        'reason': 'No vendor tag, generic upgrade mention'
    },
    {
        'id': 104,
        'subject': 'Compliance Checklist Review',
        'description': 'Annual compliance review for all vendors',
        'tags': ['compliance', 'annual'],
        'expected': False,
        'reason': 'No specific vendor tag, generic compliance'
    },
    {
        'id': 105,
        'subject': 'Atomic Billing System',
        'description': 'Issue with atomic operations in billing system',
        'tags': [],
        'expected': False,
        'reason': '"atomic" is not related to Atomic vendor in this context, no tag'
    },
]

def test_filtering():
    """Test the filtering logic with sample tickets."""
    print("=" * 80)
    print("TESTING VENDOR FILTERING LOGIC")
    print("=" * 80)

    all_tickets = valid_tickets + noise_tickets
    filtered, stats = filter_vendor_alert_tickets(all_tickets)
    filtered_ids = {t['id'] for t in filtered}

    print(f"\nFiltering Stats:")
    print(f"  Total tickets: {len(all_tickets)}")
    print(f"  Monitored vendor matches: {stats['monitored_vendor_matches']}")
    print(f"  Tag matches: {stats['tag_matches']}")
    print(f"  Alert keyword matches: {stats['alert_keyword_matches']}")
    print(f"  Final alerts extracted: {len(filtered)}")
    print(f"  Rejected vendors: {stats['rejected_vendors']}")

    print("\n" + "=" * 80)
    print("VALID TICKETS (Should be INCLUDED):")
    print("=" * 80)
    valid_pass = 0
    for ticket in valid_tickets:
        is_included = ticket['id'] in filtered_ids
        status = "✅ PASS" if is_included == ticket['expected'] else "❌ FAIL"
        if is_included == ticket['expected']:
            valid_pass += 1
        print(f"{status} | ID {ticket['id']}: {ticket['subject'][:50]}")
        print(f"       Reason: {ticket['reason']}")
        print(f"       Tags: {ticket['tags']}")
        print(f"       Expected: {ticket['expected']}, Got: {is_included}\n")

    print("=" * 80)
    print("NOISE TICKETS (Should be EXCLUDED):")
    print("=" * 80)
    noise_pass = 0
    for ticket in noise_tickets:
        is_included = ticket['id'] in filtered_ids
        status = "✅ PASS" if is_included == ticket['expected'] else "❌ FAIL"
        if is_included == ticket['expected']:
            noise_pass += 1
        print(f"{status} | ID {ticket['id']}: {ticket['subject'][:50]}")
        print(f"       Reason: {ticket['reason']}")
        print(f"       Tags: {ticket['tags']}")
        print(f"       Expected: {ticket['expected']}, Got: {is_included}\n")

    print("=" * 80)
    print("RESULTS:")
    print("=" * 80)
    total_pass = valid_pass + noise_pass
    total_tests = len(valid_tickets) + len(noise_tickets)
    print(f"✅ Valid tickets passed: {valid_pass}/{len(valid_tickets)}")
    print(f"✅ Noise reduction passed: {noise_pass}/{len(noise_tickets)}")
    print(f"✅ Total passed: {total_pass}/{total_tests}")

    if total_pass == total_tests:
        print("\n🎉 ALL TESTS PASSED! No noise being generated.")
        return True
    else:
        print(f"\n❌ {total_tests - total_pass} TEST(S) FAILED")
        return False

def test_tag_matching():
    """Test tag-based vendor detection."""
    print("\n" + "=" * 80)
    print("TESTING TAG-BASED VENDOR DETECTION:")
    print("=" * 80)

    test_cases = [
        (['twilio', 'alert'], 'twilio', 'Tag should match'),
        (['entrust', 'security'], 'entrust', 'Tag should match'),
        (['jumio'], 'jumio', 'Tag should match'),
        (['quickbooks'], None, 'Unmonitored vendor tag'),
        ([], None, 'No tags'),
        (['alert', 'security'], None, 'Only alert tags, no vendor'),
    ]

    pass_count = 0
    for tags, expected, description in test_cases:
        result = get_vendor_from_tags(tags)
        status = "✅" if result == expected else "❌"
        if result == expected:
            pass_count += 1
        print(f"{status} Tags {tags} → {result} (expected {expected})")
        print(f"   {description}\n")

    print(f"✅ Tag matching: {pass_count}/{len(test_cases)} passed")
    return pass_count == len(test_cases)

if __name__ == "__main__":
    print("\n🔍 TESTING ZENDESK WATCH AGENT FILTERING LOGIC\n")

    tag_test = test_tag_matching()
    filter_test = test_filtering()

    print("\n" + "=" * 80)
    if tag_test and filter_test:
        print("✅ ALL TESTS PASSED - No noise being generated!")
        print("The agent is ready for production use.")
    else:
        print("❌ SOME TESTS FAILED - Please review the logic")
    print("=" * 80 + "\n")
