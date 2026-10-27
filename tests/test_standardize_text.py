from knowledge_engine_ai.standardize_text import standardize_text


def test_standardize_text_example_1() -> None:
    assert standardize_text(" Hello World ") == "hello world"


def test_standardize_text_example_2() -> None:
    assert standardize_text("Python is great") == "python is great"


def test_standardize_text_example_3() -> None:
    assert standardize_text(" Leading and trailing ") == "leading and trailing"


def test_standardize_text_example_4() -> None:
    assert standardize_text("SingleWord") == "singleword"


def test_standardize_text_example_5() -> None:
    assert standardize_text(" ") == ""
