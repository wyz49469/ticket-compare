"""
测试 12306 支付宝小程序接受的具体参数名和页面路径。
生成多个不同参数组合的测试 URL。

用法: python test_alipay_params.py
"""

import qrcode
import sys
from urllib.parse import quote
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output" / "alipay_test"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

APP_ID = "20000135"
FROM_CODE = "BJP"
TO_CODE = "CSQ"
DATE = "2026-05-13"

# 尝试不同的页面路径
PAGE_PATHS = [
    ("首页", ""),
    ("pages/index/index", "pages/index/index"),
    ("pages/ticket/search", "pages/ticket/search"),
    ("pages/train/search", "pages/train/search"),
    ("pages/search/index", "pages/search/index"),
    ("pages/ticket/index", "pages/ticket/index"),
]

# 尝试不同的参数名组合（12306 可能用不同命名）
QUERY_VARIANTS = [
    # 蛇形命名
    ("蛇形: from_station + to_station + date", f"from_station={FROM_CODE}&to_station={TO_CODE}&date={DATE}"),
    # 驼峰命名
    ("驼峰: fromStation + toStation + date", f"fromStation={FROM_CODE}&toStation={TO_CODE}&date={DATE}"),
    # departure/arrival
    ("出发/到达: departure + arrival + date", f"departure={FROM_CODE}&arrival={TO_CODE}&date={DATE}"),
    # 中文参数名
    ("中文: 出发站 + 到达站 + 日期", f"出发站={FROM_CODE}&到达站={TO_CODE}&日期={DATE}"),
    # deprecated 12306 web params
    ("12306 Web: fs + ts + date", f"fs={FROM_CODE}&ts={TO_CODE}&date={DATE}"),
    # from/to
    ("简写: from + to + date", f"from={FROM_CODE}&to={TO_CODE}&date={DATE}"),
    # start/end
    ("起点/终点: start + end + date", f"start={FROM_CODE}&end={TO_CODE}&date={DATE}"),
    # trainDate
    ("trainDate: fromStation + toStation + trainDate", f"fromStation={FROM_CODE}&toStation={TO_CODE}&trainDate={DATE}"),
    # city name
    ("城市名: from_city=北京 + to_city=长沙 + date", f"from_city=北京&to_city=长沙&date={DATE}"),
    # full chinese
    ("完整中文: 始发站=北京 + 终到站=长沙 + 出发日期=2026-05-13", f"始发站=北京&终到站=长沙&出发日期={DATE}"),
]


def generate_qr_and_url(page_path: str, query: str, label: str, filename: str):
    """生成 Scheme URL + QR 码"""
    url = f"alipays://platformapi/startapp?appId={APP_ID}"
    if page_path:
        url += f"&page={quote(page_path, safe='')}"
    if query:
        url += f"&query={quote(query, safe='')}"

    # QR
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    filepath = OUTPUT_DIR / filename
    img.save(str(filepath))

    return url, filepath


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    print("=" * 70)
    print("  12306 支付宝小程序 — 参数名 & 页面路径 穷举测试")
    print("=" * 70)
    print()

    test_cases = []

    # 套路 A: 首页 + 各种 query 参数组合
    print("🔍 套路 A: 只跳首页，变化 query 参数名")
    print("-" * 50)
    for idx, (label, query_str) in enumerate(QUERY_VARIANTS):
        filename = f"param_a{idx+1}.png"
        url, filepath = generate_qr_and_url("", query_str, label, filename)
        test_cases.append((label, url, filepath))
        print(f"  {label}")
        print(f"  → {url}")
    print()

    # 套路 B: 购票页路径 + 各种 query 组合
    print("🔍 套路 B: 尝试不同 page 路径 + 蛇形参数")
    print("-" * 50)
    base_query = f"from_station={FROM_CODE}&to_station={TO_CODE}&date={DATE}"
    for path_label, page_path in PAGE_PATHS:
        if not page_path:
            continue
        safe_name = page_path.replace("/", "_").replace(".", "_")
        filename = f"path_{safe_name}.png"
        url, filepath = generate_qr_and_url(page_path, base_query, path_label, filename)
        test_cases.append((f"path={page_path}", url, filepath))
        print(f"  {path_label}")
        print(f"  → {url}")
    print()

    # 套路 C: 尝试把参数直接拼在 page 路径里
    print("🔍 套路 C: page 路径直接带参数（不用 query 字段）")
    print("-" * 50)
    for idx, (param_label, query_str) in enumerate(QUERY_VARIANTS[:4]):  # 只试前 4 种
        page_with_params = f"pages/ticket/search?{query_str}"
        filename = f"pinline_c{idx+1}.png"
        url = f"alipays://platformapi/startapp?appId={APP_ID}&page={quote(page_with_params, safe='?=&')}"
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=3)
        qr.add_data(url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        filepath = OUTPUT_DIR / filename
        img.save(str(filepath))
        test_cases.append((f"page内联参数: {query_str[:50]}...", url, filepath))
        print(f"  {param_label}")
        print(f"  → {url}")
    print()

    # 汇总
    print("=" * 70)
    print(f"  ✅ 共生成 {len(test_cases)} 个测试")
    print(f"  输出目录: {OUTPUT_DIR}")
    print()
    print("  测试方法：")
    print("  1. 支付宝先扫 '参数名' 系列的 QR（套路 A）")
    print("  2. 看哪个参数名能让 12306 预填正确")
    print("  3. 再用正确的参数名 + page 路径组合测试")
    print("=" * 70)


if __name__ == "__main__":
    main()
