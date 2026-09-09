import re
import ipaddress
import urllib.parse
from typing import Tuple, Optional, Set

# Allowed canonical platform hosts
GITHUB_HOSTS: Set[str] = {"github.com", "www.github.com"}
LEETCODE_HOSTS: Set[str] = {"leetcode.com", "www.leetcode.com", "leetcode.cn"}
CODEFORCES_HOSTS: Set[str] = {"codeforces.com", "www.codeforces.com"}
KAGGLE_HOSTS: Set[str] = {"kaggle.com", "www.kaggle.com"}
LINKEDIN_HOSTS: Set[str] = {"linkedin.com", "www.linkedin.com"}

ALL_PLATFORM_HOSTS: Set[str] = (
    GITHUB_HOSTS | LEETCODE_HOSTS | CODEFORCES_HOSTS | KAGGLE_HOSTS | LINKEDIN_HOSTS
)


def is_private_ip(hostname: str) -> bool:
    """Check if hostname resolves directly to a private, loopback, or reserved IP address (SSRF check)."""
    clean_host = hostname.strip().lower()
    if clean_host in ("localhost", "127.0.0.1", "0.0.0.0", "::1", "local"):
        return True
    try:
        ip = ipaddress.ip_address(clean_host)
        return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local
    except ValueError:
        return False


def validate_platform_url(url_or_handle: str, allowed_hosts: Set[str]) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validate that an input string is either:
    1. A valid URL matching allowed platform hosts (and not a private IP / lookalike), OR
    2. A simple alphanumeric handle/username without protocols or slashes.

    Returns:
      (is_valid, extracted_path_or_handle, error_reason)
    """
    if not url_or_handle or not str(url_or_handle).strip():
        return False, None, "Empty URL or handle provided"

    raw = str(url_or_handle).strip()

    # Reject blatant SSRF characters or schemes
    if any(raw.lower().startswith(s) for s in ("file://", "ftp://", "gopher://", "ldap://", "dict://")):
        return False, None, "Unsupported URL scheme"

    # If scheme not present but looks like a URL (contains '.' and '/')
    if "://" not in raw and ("/" in raw or "." in raw):
        raw = "https://" + raw

    # Parse URL if scheme present
    if "://" in raw:
        parsed = urllib.parse.urlparse(raw)
        hostname = (parsed.hostname or "").lower()

        # Reject private/loopback IPs
        if is_private_ip(hostname):
            return False, None, f"Host '{hostname}' resolves to a private or restricted network address"

        # Check against allowed platform hosts
        if hostname not in allowed_hosts:
            return False, None, f"Host '{hostname}' is not a recognized platform domain ({', '.join(sorted(allowed_hosts))})"

        path = parsed.path.strip("/")
        return True, path, None

    # Handle case: pure username / handle (e.g. "tourist", "octocat")
    if re.match(r"^[a-zA-Z0-9_\-\.]{1,100}$", raw):
        return True, raw, None

    return False, None, "Invalid URL or handle format"


def extract_username_from_path(path: str, platform: str) -> Optional[str]:
    """
    Extract username / handle from a normalized platform URL path.
    Examples:
      LeetCode: 'u/john_doe' -> 'john_doe', 'john_doe' -> 'john_doe'
      Codeforces: 'profile/tourist' -> 'tourist', 'tourist' -> 'tourist'
      Kaggle: 'john_doe' -> 'john_doe'
      LinkedIn: 'in/john-doe-123' -> 'john-doe-123'
    """
    if not path:
        return None

    parts = [p for p in path.split("/") if p]
    if not parts:
        return None

    if platform == "leetcode":
        if parts[0] == "u" and len(parts) >= 2:
            return parts[1]
        return parts[0]

    elif platform == "codeforces":
        if parts[0] == "profile" and len(parts) >= 2:
            return parts[1]
        return parts[0]

    elif platform == "linkedin":
        if parts[0] == "in" and len(parts) >= 2:
            return parts[1]
        return parts[0]

    elif platform == "kaggle":
        return parts[0]

    elif platform == "github":
        return parts[0]

    return parts[0]
