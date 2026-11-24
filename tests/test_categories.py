import pytest

from tally.categories import CATEGORIES, add_custom, all_slugs, is_valid, label


def test_categories():
    assert CATEGORIES[0] == "food" and len(CATEGORIES) == 8
    assert label("groceries", "zh") == "买菜日用" and label("food", "en") == "Food"


def test_custom(conn):
    assert not is_valid("pets", conn)
    add_custom(conn, "pets", "Pets", "宠物")
    assert is_valid("pets", conn) and all_slugs(conn)[-1] == "pets"
    assert label("pets", "zh", conn) == "宠物"
    assert "pets" not in all_slugs()


@pytest.mark.parametrize("slug", ["food", "Bad", "a", "1x", "pets"])
def test_custom_rejects(conn, slug):
    add_custom(conn, "pets", "Pets", "宠物")
    with pytest.raises(ValueError):
        add_custom(conn, slug, "X", "X")
