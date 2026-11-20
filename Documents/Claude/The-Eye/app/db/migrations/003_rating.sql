-- Chấm tin 1 chạm (1–5): lưu mức người dùng chọn bên cạnh nhãn POS/NEU/NEG
ALTER TABLE training_labels ADD COLUMN IF NOT EXISTS rating SMALLINT;
