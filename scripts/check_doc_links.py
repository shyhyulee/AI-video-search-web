"""檢查 docs/ 底下（含 archive/、prompts/ 子目錄）所有 markdown 連結的檔案與錨點是否存在。

    uv run python scripts/check_doc_links.py

會一起檢查「裸引用」（沒有包成 markdown link 的 `xxx.md#anchor` 寫法），因為程式碼註解與
文件內文都常常這樣寫——專案曾經有 37 處註解指向從未存在過的檔案，一直沒被發現，
見 docs/README.md「維護規則」。

錨點規則沿用 GitHub：標題轉小寫 → 去掉標點與符號 → 空白換成連字號。

刻意提到「某某檔案已不存在」的檔名列在 KNOWN_ABSENT，不會回報。
"""
from __future__ import annotations

import re
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)\)")
HEADING = re.compile(r"^#{1,6}\s+(.*?)\s*$", re.MULTILINE)
# 裸引用：docs/xxx.md#anchor 或 `xxx.md` §N 這類非 markdown-link 的寫法
BARE = re.compile(r"(?<![\w\-(\[/])((?:docs/)?[0-9A-Za-z_一-鿿][0-9A-Za-z_一-鿿-]*\.md)(#[^\s，。）)、`）]*)?")


# 文件裡刻意提到、且明講「已不存在」的檔名。它們是敘述的一部分，不是壞連結。
KNOWN_ABSENT = {
    "AI_Video_Search_搜尋準確率提升規劃.md",   # 原始需求 prompt，從未進過版控
    "Claude_Code_OCR_影片搜尋開發規劃.md",     # 同上
    "development-log.md",                     # 已被 01-development-timeline.md 取代
    "03-excluded-approaches.md",              # 2026-09-02 併進 02 的「已排除方案」一章
    "06-conversational-search-flow.md",       # 2026-09-02 併進 12 的 §7
}


def slug(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)          # 去掉 inline code 反引號
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)  # 連結只留文字
    out = []
    for ch in text.lower():
        if ch.isspace():
            out.append("-")
        elif ch == "-" or ch == "_":
            out.append(ch)
        elif unicodedata.category(ch)[0] in "PS":
            continue  # 標點與符號去掉（含全形＋這類 Sm）
        else:
            out.append(ch)
    return "".join(out)


def anchors_of(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    # 略過 fenced code block 裡的 #
    text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
    return {slug(h) for h in HEADING.findall(text)}


def main() -> int:
    anchor_cache: dict[Path, set[str]] = {}
    problems: list[str] = []

    # rglob 而不是 glob：文件分層之後（archive/、prompts/）子目錄裡的連結一樣要驗，
    # 否則搬進去的那幾份等於失去覆蓋。
    for md in sorted(DOCS.rglob("*.md")):
        text = md.read_text(encoding="utf-8")
        body = re.sub(r"```.*?```", "", text, flags=re.DOTALL)

        targets: list[tuple[str, str]] = []
        for raw in LINK.findall(body):
            if raw.startswith(("http://", "https://", "mailto:")):
                continue
            file_part, _, anchor = raw.partition("#")
            targets.append((file_part, anchor))
        for file_part, anchor in BARE.findall(body):
            targets.append((file_part, anchor.lstrip("#")))

        for file_part, anchor in targets:
            if file_part.rsplit("/", 1)[-1] in KNOWN_ABSENT:
                continue
            if file_part:
                cand = (DOCS / file_part.removeprefix("docs/")) if file_part.startswith("docs/") \
                    else (md.parent / file_part)
                if not cand.exists():
                    cand2 = ROOT / file_part
                    if not cand2.exists():
                        problems.append(f"{md.relative_to(DOCS)}: 檔案不存在 → {file_part}")
                        continue
                    cand = cand2
            else:
                cand = md
            if anchor:
                if cand not in anchor_cache:
                    anchor_cache[cand] = anchors_of(cand)
                if anchor not in anchor_cache[cand]:
                    problems.append(f"{md.relative_to(DOCS)}: 錨點不存在 → {file_part}#{anchor}")

    if problems:
        unique = sorted(set(problems))
        print(f"發現 {len(unique)} 個問題：")
        for p in unique:
            print("  ", p)
        return 1
    print("全部連結與錨點都有效。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
