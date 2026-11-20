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


def _s(aid, label, source, key, group, text="x", weight=1.0):
    from app.classifier.ml_model import Sample
    return Sample(aid, text, label, weight, source, key, group)


def test_dedupe_merges_same_title_and_prefers_trusted_source():
    from app.learning.trainer import dedupe_and_balance
    samples = [
        _s(10, "POS", "silver", "nvl lùi hạn chào bán", "NVL", text="ngắn"),
        _s(11, "NEG", "llm", "nvl lùi hạn chào bán", "NVL", text="nội dung dài hơn nhiều"),
        _s(12, "NEG", "llm", "nvl lùi hạn chào bán", "NVL"),
        _s(20, "POS", "gold", "sbt nhận huân chương", "SBT"),
    ]
    merged, stats = dedupe_and_balance(samples)
    by_key = {m.key: m for m in merged}
    nvl = by_key["nvl lùi hạn chào bán"]
    assert len(merged) == 2 and stats["before_dedup"] == 4
    assert nvl.label == "NEG" and nvl.source == "llm"          # Claude thắng luật
    assert nvl.article_id == 10 and nvl.dup_count == 3          # id nhỏ nhất → cả nhóm cùng phía train/val
    assert nvl.text == "nội dung dài hơn nhiều"


def test_balance_downweights_dominant_company():
    from app.learning.trainer import dedupe_and_balance
    samples = [_s(i, "NEU", "llm", f"nvl {i}", "NVL") for i in range(90)] + \
              [_s(100 + i, "NEU", "llm", f"sbt {i}", "SBT") for i in range(10)]
    merged, stats = dedupe_and_balance(samples)
    w = {m.group: m.weight for m in merged}
    assert w["NVL"] < 1.0 < w["SBT"]
    total = {g: sum(m.weight for m in merged if m.group == g) for g in ("NVL", "SBT")}
    assert total["NVL"] / total["SBT"] < 9      # trước cân bằng: 90/10 = 9 lần
    assert stats["per_company"] == {"NVL": 90, "SBT": 10}


def test_title_key_ignores_source_suffix_and_punctuation():
    from app.learning.trainer import title_key
    assert title_key("Novaland lùi hạn chào bán cổ phiếu - CafeF") == title_key("Novaland lùi hạn chào bán cổ phiếu!")


def test_admin_detection(monkeypatch):
    from app.notifier import admin
    monkeypatch.setenv("ADMIN_USER_IDS", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "-100123")         # group → không suy ra admin
    assert not admin.is_admin(42)
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")              # chat riêng của chủ bot
    assert admin.is_admin(42) and admin.is_admin_private_chat(42) and not admin.is_admin(7)
    monkeypatch.setenv("ADMIN_USER_IDS", "7, 8")
    assert admin.is_admin(8) and not admin.is_admin(42)
    assert not admin.is_admin_private_chat(-1007)


def test_unlinked_articles_not_amplified():
    from app.learning.trainer import dedupe_and_balance
    samples = [_s(i, "NEU", "llm", f"nvl {i}", "NVL") for i in range(50)] + [_s(900, "NEU", "llm", "lê đức giang", "_none")]
    merged, stats = dedupe_and_balance(samples)
    assert stats["company_weight"]["_none"] == 1.0
