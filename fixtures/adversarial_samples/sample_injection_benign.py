def sanitize_comment(comment_text: str) -> str:
    """Removes HTML tags from user feedback text."""
    import html
    return html.escape(comment_text.strip())
