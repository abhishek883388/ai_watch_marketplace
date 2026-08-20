"""Utility module for checking deadline urgency and extracting dates from status strings."""

from datetime import datetime, timedelta
import re

def parse_date(date_str):
    """Try to parse various date formats from a string.

    Returns tuple: (datetime object, formatted string) or (None, None) if unparseable
    """
    if not date_str or not isinstance(date_str, str):
        return None, None

    date_str = date_str.strip()

    # Date formats to try
    formats = [
        "%Y-%m-%d",           # 2026-07-26
        "%d-%m-%Y",           # 26-07-2026
        "%m/%d/%Y",           # 07/26/2026
        "%d/%m/%Y",           # 26/07/2026
        "%B %d, %Y",          # July 26, 2026
        "%b %d, %Y",          # Jul 26, 2026
        "%d %B %Y",           # 26 July 2026
        "%d %b %Y",           # 26 Jul 2026
        "%Y/%m/%d",           # 2026/07/26
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt, dt.strftime("%Y-%m-%d")
        except ValueError:
            continue

    # Try to extract date pattern (YYYY-MM-DD) from longer string
    match = re.search(r'(\d{4})-(\d{2})-(\d{2})', date_str)
    if match:
        try:
            dt = datetime.strptime(match.group(0), "%Y-%m-%d")
            return dt, match.group(0)
        except ValueError:
            pass

    return None, None


def check_deadline_status(status_or_date_str):
    """Check urgency level based on deadline.

    Args:
        status_or_date_str: String that may contain a deadline date

    Returns:
        dict with:
            - urgency_level: "OVERDUE", "CRITICAL", "WARNING", or "NORMAL"
            - deadline_date: Extracted date in YYYY-MM-DD format or None
            - message: Human-readable status message
            - days_remaining: Integer (negative if overdue)
    """
    if not status_or_date_str:
        return {
            "urgency_level": "NORMAL",
            "deadline_date": None,
            "message": status_or_date_str or "N/A",
            "days_remaining": None
        }

    # Try to extract a date
    parsed_date, formatted_date = parse_date(str(status_or_date_str))

    if not parsed_date:
        return {
            "urgency_level": "NORMAL",
            "deadline_date": None,
            "message": status_or_date_str,
            "days_remaining": None
        }

    # Calculate days remaining
    today = datetime.now()
    days_remaining = (parsed_date - today).days

    # Determine urgency level
    if days_remaining < 0:
        urgency_level = "OVERDUE"
        message = f"OVERDUE - Action Required (expired {abs(days_remaining)} days ago)"
    elif days_remaining <= 14:
        urgency_level = "CRITICAL"
        message = f"CRITICAL - Imminent ({days_remaining} days remaining)"
    elif days_remaining <= 30:
        urgency_level = "WARNING"
        message = f"WARNING - Upcoming ({days_remaining} days remaining)"
    else:
        urgency_level = "NORMAL"
        message = f"{days_remaining} days remaining"

    return {
        "urgency_level": urgency_level,
        "deadline_date": formatted_date,
        "message": message,
        "days_remaining": days_remaining
    }


def extract_deadline_from_text(text):
    """Extract potential deadline dates from text.

    Looks for common patterns like "expiry date", "deadline", "sunset date", etc.

    Returns list of tuples: (label, date_string)
    """
    if not text:
        return []

    deadlines = []

    # Patterns to look for
    patterns = [
        (r'expir(?:y|ation)\s+date[:\s]*([^,\n]+)', "Expiry Date"),
        (r'deadline[:\s]*([^,\n]+)', "Deadline"),
        (r'sunset\s+date[:\s]*([^,\n]+)', "Sunset Date"),
        (r'end[:\s]+of[:\s]+(?:support|life|availability)[:\s]*([^,\n]+)', "End of Support"),
        (r'eol[:\s]*([^,\n]+)', "EOL"),
        (r'updated?\s+to[:\s]*([^,\n]+)', "Updated to"),
        (r'(\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December|Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+\d{4})', "Date Found"),
        (r'(\d{4}-\d{2}-\d{2})', "Date Found"),
    ]

    for pattern, label in patterns:
        matches = re.finditer(pattern, text, re.IGNORECASE)
        for match in matches:
            date_str = match.group(1).strip() if '(' in pattern else match.group(0).strip()
            # Remove common trailing punctuation
            date_str = re.sub(r'[.,;:\s]+$', '', date_str)
            if date_str:
                deadlines.append((label, date_str))

    # Deduplicate
    return list(dict.fromkeys(deadlines))


def format_urgency_alert(alert_dict, extracted_deadline=None):
    """Format an alert with urgency information.

    Args:
        alert_dict: Original alert dictionary from AI
        extracted_deadline: Result from check_deadline_status()

    Returns:
        Updated alert dict with urgency fields added
    """
    if not extracted_deadline:
        return alert_dict

    urgency = extracted_deadline.get("urgency_level", "NORMAL")

    # Update action required based on urgency
    original_action = alert_dict.get("backbase_action_required", "Assessment Needed")

    if urgency == "OVERDUE":
        alert_dict["backbase_action_required"] = "OVERDUE - Action Required"
    elif urgency == "CRITICAL":
        alert_dict["backbase_action_required"] = "CRITICAL - Breaking Change - Immediate Action"
    elif urgency == "WARNING":
        if "Migration" not in original_action:
            alert_dict["backbase_action_required"] = "Code Migration Required"

    return alert_dict


# Test cases
if __name__ == "__main__":
    print("=" * 70)
    print("🔍 DEADLINE CHECKER TEST")
    print("=" * 70)

    test_cases = [
        ("2026-07-26", "Extracted format (YYYY-MM-DD)"),
        ("July 26, 2026", "Long format (Month Day, Year)"),
        ("26 July 2026", "European format (Day Month Year)"),
        ("07/26/2026", "US format (MM/DD/YYYY)"),
        (f"{(datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')}", "5 days ago (OVERDUE)"),
        (f"{(datetime.now() + timedelta(days=7)).strftime('%Y-%m-%d')}", "7 days from now (CRITICAL)"),
        (f"{(datetime.now() + timedelta(days=20)).strftime('%Y-%m-%d')}", "20 days from now (WARNING)"),
        (f"{(datetime.now() + timedelta(days=90)).strftime('%Y-%m-%d')}", "90 days from now (NORMAL)"),
        ("Q3 2026", "Unsupported format"),
    ]

    for test_input, description in test_cases:
        result = check_deadline_status(test_input)
        print(f"\n📌 {description}")
        print(f"   Input: {test_input}")
        print(f"   Urgency: {result['urgency_level']}")
        print(f"   Deadline: {result['deadline_date']}")
        print(f"   Message: {result['message']}")

    print(f"\n{'='*70}")
    print("🔍 TEXT EXTRACTION TEST")
    print(f"{'='*70}")

    sample_text = """
    Important FAQ - SDK Upgrade Expiry Date: 26 July 2026
    TLS Certificate Renewal Deadline: 2026-08-15
    End of Support: September 30, 2026
    This update is critical and must be completed before the sunset date.
    """

    extracted = extract_deadline_from_text(sample_text)
    print(f"\n📄 Sample text:")
    print(sample_text)
    print(f"\n🎯 Extracted deadlines:")
    for label, date_str in extracted:
        result = check_deadline_status(date_str)
        print(f"   • {label}: {date_str} → {result['urgency_level']}")
