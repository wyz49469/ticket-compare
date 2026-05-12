"""
测试推送链接：生成 weixin://  / alipays:// / 网页版 三种链接及 QR 码。
用手机扫码或直接在微信/支付宝中点击链接测试。

用法: python test_push_links.py
"""

import qrcode
import sys
from urllib.parse import quote, urlencode
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
OUTPUT_DIR = SCRIPT_DIR / "output" / "push_test"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

APP_ID_ALIPAY = "20000135"
APP_ID_WECHAT = "wx3a455a4f1266a42a"
TICKET_PATH = "pages/ticket/query/query"

FROM_CODE = "BJP"
TO_CODE = "CSQ"
DATE = "2026-05-13"


def make_qr(data: str, filename: str) -> Path:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=3,
    )
    qr.add_data(data)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    filepath = OUTPUT_DIR / filename
    img.save(str(filepath))
    return filepath


def main():
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    links = {}

    # 1. weixin:// scheme — 微信内点击跳转12306小程序
    query_raw = f"from_station={FROM_CODE}&to_station={TO_CODE}&date={DATE}"
    links["weixin"] = (
        f"weixin://dl/business/?appid={APP_ID_WECHAT}"
        f"&path={quote(TICKET_PATH, safe='')}"
        f"&query={quote(query_raw, safe='')}"
    )

    # 2. alipays:// scheme — 支付宝内打开12306小程序
    links["alipay"] = f"alipays://platformapi/startapp?appId={APP_ID_ALIPAY}"

    # 3. 网页版 — 12306 官网
    params = {"linktypeid": "dc", "fs": FROM_CODE, "ts": TO_CODE, "date": DATE, "flag": "N,N,Y"}
    links["web"] = "https://kyfw.12306.cn/otn/leftTicket/init?" + urlencode(params)

    # 4. ds.alipay.com 桥接 — 浏览器/微信内唤起支付宝
    links["alipay_bridge"] = f"https://ds.alipay.com/?scheme={quote(links['alipay'], safe='')}"

    print("=" * 70)
    print("  推送链接测试 — 请用手机依次测试以下 4 个链接")
    print("=" * 70)
    print()

    for name, url in links.items():
        label = {"weixin": "微信小程序", "alipay": "支付宝小程序", "web": "网页版降级", "alipay_bridge": "支付宝桥接"}[name]
        print(f"【{label}】")
        print(f"  {url}")
        qr_path = make_qr(url, f"push_{name}.png")
        print(f"  QR: {qr_path}")
        print()

    # 生成 HTML 测试页
    html_path = OUTPUT_DIR / "test_push.html"
    cards = ""
    for name, url in links.items():
        label = {"weixin": "微信小程序 (weixin://)", "alipay": "支付宝小程序 (alipays://)", "web": "网页版降级", "alipay_bridge": "支付宝桥接 (ds.alipay.com)"}[name]
        img = f"push_{name}.png"
        cards += f"""
    <div class="card">
        <h3>测试：{label}</h3>
        <div class="scheme">{url}</div>
        <a class="btn" href="{url}">点击测试</a>
        <br>
        <img src="{img}" width="200" alt="QR">
    </div>"""

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>推送链接测试 — 12306 小程序</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; padding: 16px; background: #f5f5f5; }}
        .card {{ background: white; border-radius: 12px; padding: 16px; margin: 12px 0; box-shadow: 0 2px 8px rgba(0,0,0,0.1); }}
        .card h3 {{ margin-top: 0; font-size: 16px; }}
        .scheme {{ background: #1a1a2e; color: #00ff88; padding: 8px; border-radius: 6px; font-size: 11px; word-break: break-all; margin: 8px 0; }}
        img {{ display: block; margin: 8px auto; border: 1px solid #ddd; border-radius: 8px; }}
        .btn {{ display: inline-block; padding: 10px 20px; background: #1677ff; color: white; border-radius: 6px; text-decoration: none; margin: 4px; font-size: 14px; }}
        h1 {{ font-size: 18px; }}
        .tip {{ background: #fff3cd; padding: 10px; border-radius: 6px; margin: 10px 0; font-size: 13px; }}
    </style>
</head>
<body>
    <h1>推送链接测试 — 12306 购票</h1>
    <p>路线: 北京 → 长沙 | 日期: 2026-05-13</p>
    <div class="tip">
        <b>测试方法：</b>用手机打开本页面，依次点击每个链接，观察是否能打开12306小程序/网页。<br>
        <b>QR码：</b>用微信/支付宝扫对应二维码测试。
    </div>
    {cards}
    <div class="tip">
        <b>预期结果：</b><br>
        1. weixin:// — 微信内点击应打开12306小程序（可能被拦截，因12306未开通明文Scheme）<br>
        2. alipays:// — 支付宝扫/点击可打开12306小程序首页（已确认可用）<br>
        3. 网页版 — 任何环境均可打开，但搜索参数无法预填（12306用Cookie而非URL参数）<br>
        4. 桥接 — 浏览器/微信内点击跳转支付宝打开12306
    </div>
</body>
</html>"""

    html_path.write_text(html, encoding="utf-8")
    print(f"HTML 测试页: {html_path}")
    print()
    print("测试方法：")
    print("  1. 手机浏览器打开 file://{html_path} 或用 QR 码逐个测试")
    print("  2. 将链接发到微信文件传输助手，在微信内点击测试")
    print("  3. 用支付宝扫 alipay QR 码测试")


if __name__ == "__main__":
    main()
