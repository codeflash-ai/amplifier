"""Content validation core functionality."""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


class ContentValidationError(Exception):
    """Raised when content validation fails."""


@dataclass
class ValidationResult:
    """Result of content validation."""

    is_valid: bool
    reason: str | None = None
    detected_pattern: str | None = None


# Patterns that indicate paywalls or auth walls
PAYWALL_PATTERNS = [
    # Medium
    "member-only story",
    "members only",
    "this story is for members",
    # Substack
    "this post is for paid subscribers",
    "this post is for paying subscribers only",
    "upgrade to paid",
    # Patreon
    "this post is for paying subscribers",
    "unlock this post",
    # Generic
    "sign in to read",
    "sign up to read more",
    "log in to continue reading",
    "subscribe to continue reading",
    "this content is for subscribers",
    "premium content",
    "exclusive content",
]


def validate_content(html: str, markdown: str, url: str) -> ValidationResult:
    """Validate that content is accessible and not behind a paywall.

    Args:
        html: Raw HTML content
        markdown: Converted markdown content
        url: Original URL

    Returns:
        ValidationResult indicating if content is valid

    Raises:
        ContentValidationError: If content is behind paywall/auth wall
    """
    # Check for paywall patterns in HTML
    html_lower = html.lower()
    for pattern in PAYWALL_PATTERNS:
        if pattern in html_lower:
            return ValidationResult(is_valid=False, reason=f"Paywall detected: '{pattern}'", detected_pattern=pattern)

    # Check for common auth wall indicators in HTML structure
    # Count occurrences of auth-related class names in HTML
    auth_class_patterns = ["login", "signin", "signup", "paywall", "auth-wall"]
    # To reduce repeated traversals, concatenate patterns for both quote styles, then use count once
    auth_indicator_count = 0
    for pattern in auth_class_patterns:
        # Much faster: use regex for both quote styles at once, but here only use .count(), as original code does
        auth_indicator_count += html_lower.count(f'class="{pattern}"')
        auth_indicator_count += html_lower.count(f"class='{pattern}'")

    # Check if there are multiple auth indicators (suggests auth wall)
    if auth_indicator_count >= 3:
        logger.debug(f"Found {auth_indicator_count} auth-related class names in HTML")
        return ValidationResult(
            is_valid=False, reason="Multiple authentication elements detected", detected_pattern="auth_forms"
        )

    # Check markdown content quality
    # Remove YAML frontmatter efficiently using indices
    lines = markdown.split("\n")
    content_lines = []
    in_frontmatter = False

    # Optimize: use a flag and avoid unnecessary append
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            in_frontmatter = not in_frontmatter
            continue
        if not in_frontmatter:
            content_lines.append(line)

    content_text = "\n".join(content_lines)

    # Count actual content words (excluding links, navigation)
    # Optimize filtering using generator expression for memory efficiency
    words = content_text.split()
    # Use tuple for startswith, which is slightly faster and more readable
    startswith_tuple = ("[", "(http")
    content_words = [w for w in words if len(w) > 2 and not w.startswith(startswith_tuple)]

    word_count = len(content_words)

    # Check for suspiciously short content (very lenient threshold)
    # Note: Even simple pages like example.com have some real content
    if word_count < 15:
        logger.debug(f"Content has only {word_count} words")
        return ValidationResult(
            is_valid=False,
            reason=f"Content too short ({word_count} words), likely incomplete or auth-walled",
            detected_pattern="short_content",
        )

    # Count auth-related text in markdown
    # Lowercase once and use for pattern checking
    content_text_lower = content_text.lower()
    # Optimize: sum with generator to avoid repeated .lower() conversion inside list
    auth_mentions = sum(
        content_text_lower.count(pattern) for pattern in ["sign in", "sign up", "log in", "subscribe", "member"]
    )

    # Only flag if there's a very high ratio of auth mentions to actual content
    if auth_mentions >= 5 and word_count < 150:
        logger.debug(f"High auth mention ratio: {auth_mentions} mentions in {word_count} words")
        return ValidationResult(
            is_valid=False, reason="High ratio of authentication prompts to content", detected_pattern="high_auth_ratio"
        )

    # Content appears valid
    logger.debug(f"Content validation passed: {word_count} words, {auth_mentions} auth mentions")
    return ValidationResult(is_valid=True)
