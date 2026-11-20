from app.collector.rss_fetcher import _clean_title, _match_company

COMPANIES = [
    {"db_id": 1, "keywords": ["VIC", "Vingroup", "VinFast"]},
    {"db_id": 2, "keywords": ["NAF", "Nafoods"]},
    {"db_id": 3, "keywords": ["SBT", "TTC AgriS"]},
]


def test_ticker_needs_word_boundary():
    assert _match_company("Cổ phiếu VICEM tăng trần", COMPANIES) is None
    assert _match_company("Hiệp định NAFTA được ký lại", COMPANIES) is None
    assert _match_company("Cổ phiếu VIC tăng trần", COMPANIES) == 1


def test_title_company_wins_over_summary():
    assert _match_company(
        "TTC AgriS lãi lớn. Trước đó Vingroup cũng công bố", COMPANIES, title="TTC AgriS lãi lớn"
    ) == 3


def test_google_suffix_is_stripped():
    assert _clean_title("Nafoods ký hợp đồng xuất khẩu chanh leo - CafeF", is_google=True) == \
        "Nafoods ký hợp đồng xuất khẩu chanh leo"
    assert _clean_title("A - B", is_google=True) == "A - B"     # quá ngắn → giữ nguyên
    assert _clean_title("Lãi&nbsp;kỷ lục", is_google=False) == "Lãi kỷ lục"
