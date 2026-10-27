from knowledge_engine_ai.remove_punctuation import remove_punctuation


def test_remove_punctuation_example_1() -> None:
    assert remove_punctuation("Hello, world!") == "Hello world"


def test_remove_punctuation_example_2() -> None:
    assert remove_punctuation("No punctuation here") == "No punctuation here"


def test_remove_punctuation_example_3() -> None:
    assert remove_punctuation("123,456.78!@#") == "12345678"


def test_remove_punctuation_example_4() -> None:
    assert remove_punctuation("") == ""


def test_remove_punctuation_example_5() -> None:
    assert remove_punctuation("...") == ""
