from datetime import datetime, timedelta

from app.classifier.rule_based import read_article
from app.learning.trainer import _gold_by_article, silver_label
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
        (1, "POS", t0), (1, "POS", t0 + timedelta(1)), (1, "NEG", t0 + timedelta(2)),   # đa số POS
        (2, "NEG", t0), (2, "NEU", t0 + timedelta(1)),                                  # hoà → mới nhất
    ]
    assert _gold_by_article(rows) == {1: "POS", 2: "NEU"}
