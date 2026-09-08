# -*- coding: utf-8 -*-
"""
Driver ASP-as-a-Judge — cùng giao diện CLI với llm_judge.py.

Ghi thêm vào mỗi sample:
    asp_verdict     -> "pass" | "fail"
    asp_violations  -> [tên lỗi] (rỗng khi pass)
    asp_facts       -> facts đã trích từ câu trả lời
    asp_extract_by  -> "llm" | "regex" | "regex-fallback"
    asp_latency     -> giây cho riêng bước suy diễn Clingo
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extract import extract_facts          # noqa: E402
from encode import solve                   # noqa: E402

SLEEP_SECONDS = 2


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


def judge_dataset(input_file, start_index=1, end_index=None, provider=None,
                  force=False, use_llm=True, output_file=None, sleep=SLEEP_SECONDS):
    input_path = Path(input_file)
    output_path = Path(output_file) if output_file else input_path
    dataset = load_json(input_path)

    total = len(dataset)
    start = max(0, start_index - 1)
    end = total if end_index is None else min(total, end_index)

    print(f"Input : {input_path}")
    print(f"Output: {output_path}")
    print(f"Tổng số mẫu: {total} | Khoảng: {start_index} - {end}")
    print(f"Tầng trích facts: {'LLM' if use_llm else 'regex (không gọi API)'}")

    judged = 0
    api_calls = 0
    t_start = time.time()

    for i in range(start, end):
        item = dataset[i]

        if "model_answer" not in item:
            print(f"[SKIP] không có model_answer ở index {i}")
            continue

        if not force and item.get("asp_verdict"):
            continue

        facts, method = extract_facts(
            item["model_answer"], provider=provider, use_llm=use_llm
        )
        if method != "regex":
            api_calls += 1

        t0 = time.perf_counter()
        verdict, violations, program = solve(item, facts)
        latency = time.perf_counter() - t0

        item["asp_verdict"] = verdict
        item["asp_violations"] = violations
        item["asp_facts"] = facts
        item["asp_extract_by"] = method
        item["asp_latency"] = round(latency, 6)

        save_json(dataset, output_path)
        judged += 1

        gold = item.get("gold_verdict")
        mark = "" if gold is None else (" OK" if gold == verdict else " <-- LỆCH")
        print(f"[{i+1}/{total}] {item.get('eval_id', i)} -> {verdict}"
              f" {violations}{mark}")

        if use_llm and i < end - 1 and sleep:
            time.sleep(sleep)

    elapsed = time.time() - t_start
    print(f"\nXong. Đã chấm {judged} mẫu trong {elapsed:.1f}s")
    print(f"Số lần gọi API: {api_calls}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    p = argparse.ArgumentParser(
        description="ASP-as-a-Judge: trích facts rồi để Clingo phán quyết."
    )
    p.add_argument("input_file")
    p.add_argument("--start", type=int, default=1)
    p.add_argument("--end", type=int, default=None)
    p.add_argument("--output", default=None,
                   help="Mặc định: ghi đè file đầu vào")
    p.add_argument("--provider", default=None, help="groq / openrouter")
    p.add_argument("--force", action="store_true")
    p.add_argument("--no-llm", action="store_true",
                   help="Trích facts bằng regex, không gọi API (nhanh, để debug luật ASP)")
    p.add_argument("--sleep", type=int, default=SLEEP_SECONDS)
    a = p.parse_args()

    judge_dataset(a.input_file, a.start, a.end, a.provider, a.force,
                  not a.no_llm, a.output, a.sleep)
