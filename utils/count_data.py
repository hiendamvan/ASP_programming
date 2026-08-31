import json

# Đường dẫn đến file JSON
file_path = "./output_generate/simple.json"

# Đọc file JSON
with open(file_path, "r", encoding="utf-8") as f:
    data = json.load(f)

# Đếm số sample
num_samples = len(data)

print(f"Số lượng sample: {num_samples}")