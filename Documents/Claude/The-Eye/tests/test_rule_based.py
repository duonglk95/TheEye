from app.classifier.rule_based import classify, read_article, split_sentences

HONOR_TITLE = "TTC AgriS đón nhận Huân chương Lao động hạng Nhất"
HONOR_BODY = (
    "Sáng 20/11, TTC AgriS long trọng tổ chức lễ đón nhận Huân chương Lao động hạng Nhất. "
    "Đây là sự ghi nhận đóng góp to lớn của doanh nghiệp trong phát triển nông nghiệp bền vững. "
    "Niên độ vừa qua, doanh thu tăng 18% và lợi nhuận tăng mạnh so với cùng kỳ, vượt kế hoạch đề ra. "
    "Công ty cũng mở rộng thị trường xuất khẩu sang hơn 50 quốc gia và vùng lãnh thổ."
)


def test_negated_negative_keyword_is_ignored():
    label, _, _ = classify("Công ty khẳng định không vi phạm quy định công bố thông tin")
    assert label == "NEU"


def test_negated_positive_becomes_weak_negative():
    label, score, _ = classify("Lợi nhuận không đạt kế hoạch năm")
    assert label == "NEG"
    assert score < 0.6          # tín hiệu yếu → % thấp, không phải 95%


def test_single_keyword_is_not_overconfident():
    label, score, _ = classify("Hòa Phát trúng thầu dự án mới")
    assert label == "POS"
    assert 0.4 <= score <= 0.6  # 1 bằng chứng ≈ 50%, không phải 95% như trước


def test_more_evidence_more_confidence():
    _, one, _ = classify("Doanh thu tăng")
    _, many, _ = classify("Doanh thu tăng, lợi nhuận tăng, vượt kế hoạch, lãi kỷ lục")
    assert many > one


def test_full_article_reveals_good_news_hidden_from_headline():
    reading = read_article(HONOR_TITLE, "Lễ đón nhận diễn ra sáng 20/11", HONOR_BODY)
    assert reading.label == "POS"
    assert reading.body_sentences >= 3
    assert reading.body_pos_sentences >= 2
    assert reading.method.endswith("+full")


def test_word_boundary_matching():
    # "lỗ" không được khớp trong "lỗi"? (keyword "lỗ ròng" phải khớp nguyên cụm)
    label, _, _ = classify("Khắc phục lỗi ròng rã nhiều tháng")
    assert label == "NEU"


def test_split_sentences_drops_short_noise():
    parts = split_sentences("Xem thêm\nĐây là một câu đủ dài để được giữ lại trong bài.\nTin liên quan")
    assert parts == ["Đây là một câu đủ dài để được giữ lại trong bài."]
