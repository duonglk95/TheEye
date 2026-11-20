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


def test_dgc_does_not_match_person_name():
    import yaml
    from pathlib import Path
    cfg = yaml.safe_load((Path(__file__).parent.parent / "config" / "companies.yaml").read_text())
    companies = [{**c, "db_id": i} for i, c in enumerate(cfg["companies"])]
    dgc = next(i for i, c in enumerate(cfg["companies"]) if c["ticker"] == "DGC")
    assert _match_company("Cựu Phó Chủ tịch tỉnh Thanh Hóa Lê Đức Giang lĩnh 3 năm tù", companies) is None
    assert _match_company("Hóa chất Đức Giang lãi kỷ lục quý 3", companies) == dgc
    assert _match_company("Cổ phiếu DGC tăng trần", companies) == dgc
