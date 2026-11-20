from datetime import datetime, timedelta

from app.classifier.rule_based import read_article
from app.learning.trainer import _gold_by_article, silver_label
from app.notifier.rating import ids_from_markup, keyboard, rating_to_label
from tests.test_rule_based import HONOR_BODY, HONOR_TITLE


def test_silver_requires_full_body():
    assert silver_label(read_article("Lợi nhuận tăng, doanh thu tăng", "", "")) is None


def test_silver_positive_from_full_article():
    assert silver_label(read_article(HONOR_TITLE, "", HONOR_BODY)) == "POS"


def test_silver_skips_mixed_articles():
    body = ("Doanh thu tăng mạnh trong quý vừa qua nhờ xuất khẩu. "
            "Tuy nhiên công ty bị phạt vì vi phạm quy định về thuế. "
            "Lợi nhuận giảm do chi phí tài chính tăng cao.")
    assert silver_label(read_article("Kết quả quý 3", "", body)) is None


def test_gold_majority_vote_then_latest():
    t0 = datetime(2026, 1, 1)
    rows = [
        (1, "POS", t0, 5), (1, "POS", t0 + timedelta(1), 4), (1, "NEG", t0 + timedelta(2), 1),  # đa số POS
        (2, "NEG", t0, 2), (2, "NEU", t0 + timedelta(1), None),                                # hoà → mới nhất
    ]
    gold = _gold_by_article(rows)
    assert gold[1] == ("POS", 2.5)          # 🤩 (3.0) + 🙂 (2.0) → 2.5
    assert gold[2] == ("NEU", 3.0)          # nút cũ / /fix → chắc chắn


def test_rating_scale_maps_to_labels():
    assert [rating_to_label(r) for r in range(1, 6)] == ["NEG", "NEG", "NEU", "POS", "POS"]


def test_rating_keyboard_single_and_multi():
    one = keyboard([7])["inline_keyboard"]
    assert [b["text"] for b in one[0]] == ["🔴 Xấu", "⚪ Thường", "🟢 Tốt"]
    assert one[0][2]["callback_data"] == "r:7:5"

    multi = keyboard([7, 8], counts={8: {5: 2}})["inline_keyboard"]
    assert [b["text"] for b in multi[1]] == ["2.", "🔴 Xấu", "⚪ Thường", "🟢 Tốt 2"]

    class Btn:
        def __init__(self, d): self.callback_data = d
    class Markup:
        inline_keyboard = [[Btn(b["callback_data"]) for b in row] for row in multi]
    assert ids_from_markup(Markup()) == [7, 8]


def test_menu_button_pattern():
    from app.notifier.menu import BUTTON_PATTERN
    for ok in ("📊 NAF", "📋 Tổng quan", "🟢 Tin tốt", "🔴 Tin xấu", "🔔 Bật thông báo", "🔕 Tắt thông báo"):
        assert BUTTON_PATTERN.match(ok), ok
    for bad in ("📊 NAF hôm nay thế nào", "NAF", "tin tốt"):
        assert not BUTTON_PATTERN.match(bad), bad
