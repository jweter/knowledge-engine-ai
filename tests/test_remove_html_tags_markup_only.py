from knowledge_engine_ai.remove_html_tags import remove_html_tags


def test_a_quoted_greater_than_inside_an_attribute_does_not_leak_the_tag() -> None:
    assert remove_html_tags('<a title="1 > 0">Link</a>') == "Link"


def test_a_multiline_opening_tag_is_removed_completely() -> None:
    assert remove_html_tags('<div\n class="content">Hello</div>') == "Hello"


def test_comparison_operators_in_plain_text_are_preserved() -> None:
    assert remove_html_tags("x < 5 and y > 3") == "x < 5 and y > 3"


def test_ordinary_markup_is_still_stripped() -> None:
    assert remove_html_tags("<p>Hello, <b>World</b>!</p>") == "Hello, World!"
    assert remove_html_tags('<img src="image.jpg" alt="Image">') == ""
    assert remove_html_tags("") == ""
