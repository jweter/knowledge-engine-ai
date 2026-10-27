from knowledge_engine_ai.remove_special_characters import remove_special_characters


def test_remove_special_characters_example_1() -> None:
    assert remove_special_characters("Hello, World!") == "Hello World"


def test_remove_special_characters_example_2() -> None:
    assert remove_special_characters("Python3.12") == "Python312"


def test_remove_special_characters_example_3() -> None:
    assert remove_special_characters("123@#$$%^&*()") == "123"


def test_remove_special_characters_example_4() -> None:
    assert remove_special_characters("No special characters here") == "No special characters here"


def test_remove_special_characters_example_5() -> None:
    assert remove_special_characters("") == ""
