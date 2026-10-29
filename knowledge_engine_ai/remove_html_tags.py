from html.parser import HTMLParser


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

    class HTMLStripper(HTMLParser):
        def __init__(self) -> None:
            super().__init__()
            self.text: list[str] = []

        def handle_data(self, data: str) -> None:
            self.text.append(data)

    stripper = HTMLStripper()
    stripper.feed(text)
    stripper.close()
    return "".join(stripper.text)
