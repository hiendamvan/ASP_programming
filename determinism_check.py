# -*- coding: utf-8 -*-
"""
Đo TÍNH TẤT ĐỊNH của hai judge: chạy lặp nhiều lần trên CÙNG một đầu vào rồi
xem kết quả có đổi không.

Đây là một trong những bằng chứng rẻ nhất và thuyết phục nhất cho luận văn:
một judge dùng để chấm benchmark mà cho kết quả khác nhau giữa các lần chạy thì
mọi con số báo cáo từ nó đều không tái lập được. ASP judge tất định theo thiết
kế (Clingo cho cùng đáp án với cùng tập fact); LLM judge thì không, kể cả khi
đặt temperature=0.

Ghi vào mỗi sample:  judge_verdict_run1..N  và  asp_verdict_run1..N
(để compare_judges.py đọc ở mục "Tính tất định").
"""
import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "asp_judge"))

from llm_judge import judge_item                      # noqa: E402
from asp_judge.extract import extract_facts           # noqa: E402
from asp_judge.encode import solve                    # noqa: E402
from compare_judges import llm_verdict                # noqa: E402


def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    tmp.replace(path)


def main(input_file, n_samples, runs, sleep, provider):
    dataset = load_json(input_file)
    subset = dataset[:n_samples]

    print(f"Đo tính tất định trên {len(subset)} mẫu × {runs} lần chạy")

    for run in range(1, runs + 1):
        print(f"\n===== LƯỢT {run}/{runs} =====")
        for i, item in enumerate(subset):
            # --- LLM judge ---
            try:
                # judge_item ghi đè judge_* nên phải chụp lại ngay sau khi gọi
                judge_item(item, provider_name=provider)
                item[f"judge_verdict_run{run}"] = llm_verdict(item)
                item[f"judge_score_run{run}"] = item.get("judge_score")
            except Exception as e:
                print(f"  [LLM lỗi] {type(e).__name__}: {e}")
                item[f"judge_verdict_run{run}"] = None

            # --- ASP judge ---
            try:
                facts, _ = extract_facts(item["model_answer"], provider=provider)
                verdict, violations, _ = solve(item, facts)
                item[f"asp_verdict_run{run}"] = verdict
            except Exception as e:
                print(f"  [ASP lỗi] {type(e).__name__}: {e}")
                item[f"asp_verdict_run{run}"] = None

            print(f"  [{i+1}/{len(subset)}] {item.get('eval_id')}: "
                  f"LLM={item.get(f'judge_verdict_run{run}')} "
                  f"(score={item.get(f'judge_score_run{run}')}) "
                  f"ASP={item.get(f'asp_verdict_run{run}')}")

            save_json(dataset, input_file)
            time.sleep(sleep)

    # ---- tổng kết ----
    def rate(prefix):
        changed = 0
        for it in subset:
            vals = [it.get(f"{prefix}{r}") for r in range(1, runs + 1)]
            if len(set(vals)) > 1:
                changed += 1
        return changed

    print(f"\n{'=' * 60}")
    print(f"LLM judge đổi kết quả: {rate('judge_verdict_run')}/{len(subset)} mẫu")
    print(f"ASP judge đổi kết quả: {rate('asp_verdict_run')}/{len(subset)} mẫu")
    print(f"Đã ghi vào: {input_file}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Đo tính tất định của hai judge")
    p.add_argument("input_file")
    p.add_argument("--samples", type=int, default=30,
                   help="Số mẫu đầu tiên dùng để đo. Default: 30")
    p.add_argument("--runs", type=int, default=3)
    p.add_argument("--sleep", type=int, default=2)
    p.add_argument("--provider", default=None)
    a = p.parse_args()
    main(a.input_file, a.samples, a.runs, a.sleep, a.provider)
