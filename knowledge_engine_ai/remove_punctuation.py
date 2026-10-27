import string


def remove_punctuation(text: str) -> str:
    """
    Remove all punctuation from the input text, leaving only alphanumeric characters and whitespace.

    :param text: Input text from which punctuation will be removed.
    :return: Text with all punctuation removed.
    """
    return "".join(char for char in text if char.isalnum() or char.isspace())
