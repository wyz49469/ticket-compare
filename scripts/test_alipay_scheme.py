"""
测试支付宝 URL Scheme 拉起 12306 火车票小程序。
生成多个测试 URL + 对应二维码，手机扫码测试。

用法: python test_alipay_scheme.py
"""

import qrcode
import os
import sys
from urllib.parse import quote, urlencode
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output" / "alipay_test"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# 12306 支付宝小程序
APP_ID = "20000135"

# 测试用的出发站、到达站电报码
FROM_CODE = "BJP"    # 北京
TO_CODE = "CSQ"      # 长沙
DATE = "2026-05-13"


def build_alipay_scheme(page: str = "", query: str = "") -> str:
    """构建 alipays:// URL Scheme"""
    url = f"alipays://platformapi/startapp?appId={APP_ID}"
    if page:
        url += f"&page={quote(page, safe='')}"
    if query:
        url += f"&query={quote(query, safe='')}"
    return url


def build_dsalipay_url(scheme: str) -> str:
    """构建 ds.alipay.com 桥接 URL（用于浏览器/微信内唤起）"""
    return f"https://ds.alipay.com/?scheme={quote(scheme, safe='')}"


def build_web_fallback_url() -> str:
    """12306 网页版链接（降级备用）"""
    params = urlencode({
        "linktypeid": "dc",
        "fs": FROM_CODE,
        "ts": TO_CODE,
        "date": DATE,
        "flag": "N,N,Y",
    })
    return f"https://kyfw.12306.cn/otn/leftTicket/init?{params}"


def generate_qr(data: str, filename: str, label: str):
    """生成二维码图片并保存"""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)

    img = qr.make_image(fill_color="black", back_color="white")
    filepath = OUTPUT_DIR / filename
    img.save(str(filepath))
    print(f"  ✅ QR saved: {filepath}")
    return filepath


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    print("=" * 60)
    print("  支付宝 Scheme 拉起 12306 小程序 — 测试")
    print("=" * 60)
    print()
    print(f"  12306 appId: {APP_ID}")
    print(f"  出发站 ({FROM_CODE}): 北京")
    print(f"  到达站 ({TO_CODE}): 长沙")
    print(f"  日期: {DATE}")
    print()

    # ── 测试 1：只打开 12306 首页 ──
    print("📱 测试 1: 打开 12306 支付宝小程序首页")
    scheme1 = build_alipay_scheme()
    ds1 = build_dsalipay_url(scheme1)
    print(f"   Scheme: {scheme1}")
    print(f"   桥接URL: {ds1}")
    generate_qr(scheme1, "test1_homepage.png", "打开首页")
    print()

    # ── 测试 2：首页 + query 参数 ──
    print("📱 测试 2: 首页 + query 参数（出发站=北京、到达站=长沙、日期=5月13）")
    scheme2 = build_alipay_scheme(query=f"from_station={FROM_CODE}&to_station={TO_CODE}&date={DATE}")
    ds2 = build_dsalipay_url(scheme2)
    print(f"   Scheme: {scheme2}")
    print(f"   桥接URL: {ds2}")
    generate_qr(scheme2, "test2_query_params.png", "首页+query参数")
    print()

    # ── 测试 3：常见购票页路径 ──
    print("📱 测试 3: 常见购票页路径 (pages/ticket/search)")
    # 尝试把参数放在 page 路径里
    page_path = "pages/ticket/search"
    scheme3 = f"alipays://platformapi/startapp?appId={APP_ID}&page={quote(page_path, safe='')}"
    ds3 = build_dsalipay_url(scheme3)
    print(f"   Scheme: {scheme3}")
    print(f"   桥接URL: {ds3}")
    generate_qr(scheme3, "test3_ticket_page.png", "购票页路径")
    print()

    # ── 测试 4：购票页 + 参数 ──
    print("📱 测试 4: 购票页 + query 参数")
    scheme4 = build_alipay_scheme(page=page_path, query=f"from_station={FROM_CODE}&to_station={TO_CODE}&date={DATE}")
    ds4 = build_dsalipay_url(scheme4)
    print(f"   Scheme: {scheme4}")
    print(f"   桥接URL: {ds4}")
    generate_qr(scheme4, "test4_ticket_query.png", "购票页+参数")
    print()

    # ── 测试 5：网页版降级 ──
    print("🌐 测试 5: 网页版降级链接")
    web_url = build_web_fallback_url()
    print(f"   URL: {web_url}")
    generate_qr(web_url, "test5_web_fallback.png", "网页降级")
    print()

    # ── 汇总 ──
    print("=" * 60)
    print("  测试 QR 码已保存到:")
    print(f"  {OUTPUT_DIR}")
    print()
    print("  用支付宝扫每个 QR 码，观察：")
    print("  1. 是否成功唤起支付宝")
    print("  2. 是否打开了 12306 小程序")
    print("  3. 是否跳转到了正确的页面")
    print("  4. 搜索参数是否被预填")
    print("=" * 60)


if __name__ == "__main__":
    main()
