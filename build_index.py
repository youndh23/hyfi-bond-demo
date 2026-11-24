"""Rebuild the offline evidence index from the issuer's original PDF."""
import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
from tempfile import NamedTemporaryFile
from urllib.request import Request, urlopen

import numpy as np
import onnxruntime as ort
from pypdf import PdfReader
from tokenizers import Tokenizer


ROOT = Path(__file__).resolve().parent
SOURCE = "https://www.samsungsem.com/resources/file/kr/ir/archive/2025_Separate_Audit_Report.pdf"
MODEL = "Xenova/paraphrase-multilingual-MiniLM-L12-v2"
REVISION = "2c4055b12046f11709e9df2c122e59ffbdc2f900"
MODEL_URL = f"https://huggingface.co/{MODEL}/resolve/{REVISION}"
ASSETS = {
    "report.pdf": (SOURCE, "9d1515773ef97e54f1e4a34c42acb48871ed7192955c15997465b21c174af91c"),
    "tokenizer.json": (f"{MODEL_URL}/tokenizer.json", "b60b6b43406a48bf3638526314f3d232d97058bc93472ff2de930d43686fa441"),
    "model.onnx": (f"{MODEL_URL}/onnx/model_quantized.onnx", "66fc00f5f29afcaff34092e1bdd20008ca3918265a82fb9695a551e510cc4ebc"),
}
MAX_SEQUENCE = 128
INDEX_BUDGET = 1024
DATES = {"당기말": "2025-12-31", "전기말": "2024-12-31"}
COLUMNS = ["3개월 이내", "3개월 초과~1년 이내", "1년 초과~5년 이내", "계"]
QUESTIONS = [
    ("단기차입금", "1년 내 상환할 단기차입금은 얼마인가?"),
    ("리스부채", "1년 내 지급할 리스부채는 얼마인가?"),
    ("매입채무및기타채무", "1년 내 지급할 매입채무 및 기타채무는 얼마인가?"),
    ("담보부차입금", "1년 내 상환할 담보부차입금만 따로 확인할 수 있는가?"),
]


def digest(path):
    with path.open("rb") as stream:
        return sha256(stream.read()).hexdigest()


def get_asset(cache, name):
    url, expected = ASSETS[name]
    path = cache / name
    if path.exists() and digest(path) == expected:
        return path
    cache.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=cache, delete=False) as temp:
        pending = Path(temp.name)
    try:
        with urlopen(Request(url, headers={"User-Agent": "HYFI-class-demo/1.0"}), timeout=120) as response, pending.open("wb") as output:
            shutil.copyfileobj(response, output)
        if digest(pending) != expected:
            raise ValueError(f"원본 파일의 해시가 달라졌습니다. 출처를 다시 확인하세요: {name}")
        os.replace(pending, path)
    finally:
        pending.unlink(missing_ok=True)
    return path


def parse_evidence(pages):
    # This parser supports the two period tables in note 26-3 of the pinned report.
    matches = [(n, s) for n, s in enumerate(pages, 1)
               if re.search(r"^26-3\s*유동성위험\s*$", s, re.M)]
    if len(matches) != 1:
        raise ValueError("유동성위험 주석을 한 곳으로 확정할 수 없습니다.")
    page, text = matches[0]
    blocks = re.split(r"^\(\d\)\s*(당기말|전기말)\s*$", text, flags=re.M)
    if blocks[1::2] != list(DATES):
        raise ValueError("당기말과 전기말 만기표를 확인하세요.")
    result = []
    for period, block in zip(blocks[1::2], blocks[2::2]):
        lines = [s.strip() for s in block.splitlines() if s.strip()]
        header = "구분3개월이내3개월~1년1년~5년계"
        if len(lines) < 3 or re.sub(r"\s", "", lines[0]) != "(단위:천원)" or re.sub(r"\s", "", lines[1]) != header:
            raise ValueError("단위 또는 만기 구간이 예상과 다릅니다.")
        period_rows = []
        for line in lines[2:]:
            label, *cells = line.split()
            if len(cells) != 4 or not all(re.fullmatch(r"-|\d{1,3}(?:,\d{3})*", s) for s in cells):
                raise ValueError(f"열을 확정할 수 없는 행: {line}")
            numbers = [0 if s == "-" else int(s.replace(",", "")) for s in cells]
            if abs(sum(numbers[:3]) - numbers[3]) > 1:
                raise ValueError(f"행 합계 불일치: {label}")
            if label == "계":
                for col, total in enumerate(numbers):
                    if abs(sum(r["values"][col] for r in period_rows) - total) > 1:
                        raise ValueError("열 합계 불일치")
                break
            period_rows.append(dict(date=DATES[period], label=label, values=numbers,
                                    cells=cells, unit="천원", page=page))
        else:
            raise ValueError("합계 행 누락")
        if len({r["label"] for r in period_rows}) != len(period_rows):
            raise ValueError("항목명이 중복됩니다.")
        result.extend(period_rows)
    return result


def evidence_text(row):
    cells = " / ".join(f"{name} {value}" for name, value in zip(COLUMNS, row["cells"]))
    return f"삼성전기 별도 {row['date']} 유동성위험 만기표. {row['label']} (천원). {cells}"


class Encoder:
    def __init__(self, tokenizer, model):
        self.tokenizer = Tokenizer.from_file(str(tokenizer))
        self.tokenizer.no_truncation()
        self.tokenizer.no_padding()
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = ort.InferenceSession(str(model), sess_options=options, providers=["CPUExecutionProvider"])

    def embed(self, text):
        encoding = self.tokenizer.encode(text)
        count = len(encoding.ids)
        if count > MAX_SEQUENCE:
            raise ValueError(f"모델 입력 상한 초과: {count} > {MAX_SEQUENCE}")
        inputs = {"input_ids": encoding.ids, "attention_mask": encoding.attention_mask,
                  "token_type_ids": encoding.type_ids}
        feeds = {node.name: np.array([inputs[node.name]], dtype=np.int64) for node in self.session.get_inputs()}
        # Single unpadded sequence, so all hidden states participate in mean pooling.
        hidden = self.session.run(None, feeds)[0][0]
        pooled = hidden.mean(axis=0)
        vector = pooled / np.linalg.norm(pooled)
        return {"tokens": count, "vector": [round(float(v), 6) for v in vector]}


def build(cache):
    assets = {name: get_asset(cache, name) for name in ASSETS}
    pages = [page.extract_text() for page in PdfReader(assets["report.pdf"]).pages]
    rows = parse_evidence(pages)
    encoder = Encoder(assets["tokenizer.json"], assets["model.onnx"])
    full_count = sum(len(encoder.tokenizer.encode(s, add_special_tokens=False).ids) for s in pages)
    index_count = 0
    for row in rows:
        text = evidence_text(row)
        count = len(encoder.tokenizer.encode(text).ids)
        if index_count + count > INDEX_BUDGET:
            raise ValueError("색인 전체 토큰 예산을 초과했습니다.")
        row.update(encoder.embed(text))
        index_count += count
    questions = [dict(label=label, text=text, **encoder.embed(text)) for label, text in QUESTIONS]
    return dict(source=SOURCE, model=MODEL, pages=len(pages), originalTokens=full_count,
                indexTokens=index_count, sequenceLimit=MAX_SEQUENCE, indexBudget=INDEX_BUDGET,
                columns=COLUMNS, rows=rows, questions=questions)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".cache")
    args = parser.parse_args()
    data = build(args.cache)
    dest = ROOT / "evidence.js"
    with NamedTemporaryFile(mode="w", encoding="utf-8", dir=ROOT, delete=False) as temp:
        temp.write("const EVIDENCE = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n")
        pending = temp.name
    os.replace(pending, dest)
    print(f"{data['pages']} pages / {data['originalTokens']} source tokens / {data['indexTokens']} index tokens")
    print("Question tokens:", [q["tokens"] for q in data["questions"]])


if __name__ == "__main__":
    main()
