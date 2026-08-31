import json
import os

# Danh sách 5 file JSON
input_files = [
    "output_generate/simple_1_3.json",
    "output_generate/simple_4_50.json",
    "output_generate/simple_51_100.json",
    "output_generate/simple_101_150.json",
    "output_generate/simple_150_300.json",
    "output_generate/simple_300_400.json",
    "output_generate/simple_401_600.json"
]

# File output
output_file = "output_generate/simple.json"

all_samples = []

# Đọc và gộp 5 file
for file_path in input_files:
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    print(f"{file_path}: {len(data)} samples")

    all_samples.extend(data)

# Ghi ra file mới
with open(output_file, "w", encoding="utf-8") as f:
    json.dump(all_samples, f, ensure_ascii=False, indent=2)

print("-" * 50)
print(f"Tổng số samples: {len(all_samples)}")
print(f"Đã lưu tại: {output_file}")