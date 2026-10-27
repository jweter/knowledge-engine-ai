import re


def remove_html_tags(text: str) -> str:
    """
    Removes HTML tags from a given string, preserving only the text content.

    Args:
        text (str): The input string containing HTML tags.

    Returns:
        str: The string with HTML tags removed.
    """
    if not text:
        return ""

    clean = re.compile("<.*?>")
    return re.sub(clean, "", text)
