import random

import numpy as np
import pytest

from app.classifier import ml_model
from app.classifier.ml_model import LABELS, Sample, build_text

POS_SENT = ["doanh thu tăng mạnh so với cùng kỳ", "lợi nhuận vượt kế hoạch năm", "ký kết hợp đồng lớn với đối tác",
            "mở rộng thị trường xuất khẩu", "được vinh danh tại lễ trao giải", "nhận huân chương lao động hạng nhất",
            "ghi nhận đóng góp to lớn của doanh nghiệp", "cổ phiếu tăng trần nhờ kết quả ấn tượng"]
NEG_SENT = ["lỗ ròng hàng trăm tỷ đồng", "bị khởi tố vì sai phạm", "doanh thu giảm sâu", "bị phạt vì vi phạm thuế",
            "nợ xấu tăng cao", "cắt giảm nhân sự hàng loạt", "cổ phiếu bị cảnh báo", "đóng cửa nhà máy"]
NEU_SENT = ["thông báo ngày đăng ký cuối cùng", "họp đại hội đồng cổ đông thường niên", "bổ nhiệm phó tổng giám đốc",
            "công bố thông tin về giao dịch", "thay đổi địa chỉ trụ sở", "chốt danh sách cổ đông"]
POOLS = {"POS": POS_SENT, "NEG": NEG_SENT, "NEU": NEU_SENT}


def _make_samples(n=300, seed=0):
    rng = random.Random(seed)
    out = []
    for i in range(1, n + 1):
        label = LABELS[i % 3]
        sents = rng.sample(POOLS[label], 3) + rng.sample(NEU_SENT, 1)
        rng.shuffle(sents)
        title = f"Công ty ABC {sents[0]}"
        # 15% nhãn nhiễu để mô hình không thể chắc chắn 100%
        if rng.random() < 0.15:
            label = rng.choice([l for l in LABELS if l != label])
        out.append(Sample(i, build_text(title, sents[1], ". ".join(sents[2:])), label, 1.0,
                          "gold" if i % 2 else "silver"))
    return out


def test_not_enough_data_returns_reason():
    bundle, report = ml_model.train(_make_samples(20), version=1)
    assert bundle is None
    assert "Chưa đủ dữ liệu" in report["reason"]


@pytest.fixture(scope="module")
def trained():
    return ml_model.train(_make_samples(), version=1)


def test_train_produces_calibrated_model(trained):
    bundle, report = trained
    assert bundle is not None
    assert report["val"]["n"] >= 15
    assert report["val"]["accuracy"] > 0.6
    assert 0.05 <= bundle.temperature <= 20
    assert report["val"]["ece"] < 0.2
    assert "val_gold" in report


def test_learns_phrases_rules_do_not_know(trained):
    bundle, _ = trained
    text = build_text("Nafoods nhận huân chương lao động", "ghi nhận đóng góp to lớn của doanh nghiệp", "")
    probs = bundle.predict_proba([text])[0]
    assert LABELS[int(probs.argmax())] == "POS"
    assert abs(probs.sum() - 1) < 1e-6
    phrases = bundle.explain(text, "POS")
    assert any("huân chương" in p or "đóng góp" in p for p in phrases)


def test_roundtrip_serialization(trained):
    bundle, _ = trained
    restored = ml_model.ModelBundle.from_bytes(bundle.to_bytes())
    text = build_text("Công ty bị khởi tố", "lỗ ròng hàng trăm tỷ đồng", "")
    assert np.allclose(restored.predict_proba([text]), bundle.predict_proba([text]))


def test_temperature_scaling_fixes_overconfidence():
    rng = np.random.default_rng(0)
    y = rng.integers(0, 3, 2000)
    # logits đúng hướng nhưng bị phóng đại ×5 → tự tin quá mức
    true_logits = rng.normal(0, 1, (2000, 3))
    true_logits[np.arange(2000), y] += 1.0
    over = true_logits * 5
    raw_ece = ml_model.calibration_report(ml_model.softmax(over), y)["ece"]
    t = ml_model.fit_temperature(over, y)
    cal_ece = ml_model.calibration_report(ml_model.softmax(over / t), y)["ece"]
    assert t > 2
    assert cal_ece < raw_ece / 2


def test_validation_split_is_deterministic():
    ids = range(1, 1001)
    a = [i for i in ids if ml_model.is_validation(i)]
    b = [i for i in ids if ml_model.is_validation(i)]
    assert a == b
    assert 150 < len(a) < 250
