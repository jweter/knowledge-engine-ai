def standardize_text(text: str) -> str:
    """
    Converts text to lowercase, removes leading/trailing whitespace, and replaces multiple spaces with a single space.

    :param text: The input text to standardize.
    :return: The standardized text.
    """
    if not text:
        return ""

    return " ".join(text.lower().split())
