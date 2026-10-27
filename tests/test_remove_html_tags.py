from knowledge_engine_ai.remove_html_tags import remove_html_tags


def test_remove_html_tags_example_1() -> None:
    assert remove_html_tags("<p>Hello, <b>World</b>!</p>") == "Hello, World!"


def test_remove_html_tags_example_2() -> None:
    assert remove_html_tags("<div><span>Example</span></div>") == "Example"


def test_remove_html_tags_example_3() -> None:
    assert remove_html_tags("No HTML here") == "No HTML here"


def test_remove_html_tags_example_4() -> None:
    assert remove_html_tags('<a href="https://example.com">Link</a>') == "Link"


def test_remove_html_tags_example_5() -> None:
    assert remove_html_tags('<img src="image.jpg" alt="Image">') == ""
