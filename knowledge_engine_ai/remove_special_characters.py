import re


def remove_special_characters(text: str) -> str:
    """
    Removes all special characters from the input text, leaving only alphanumeric characters and whitespace.

    Args:
        text (str): The input string containing special characters.

    Returns:
        str: The string with special characters removed.
    """
    if not text:
        return ""

    pattern = re.compile(r"[^a-zA-Z0-9\s]")
    return re.sub(pattern, "", text)
