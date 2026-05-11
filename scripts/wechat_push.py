"""
微信小程序票务付款信息推送。
将选定的出行方案（含付款链接）推送到用户微信，或生成可分享的付款卡片。

用法:
  火车票:
    python wechat_push.py --mode train --train-code G89 --secret-key abc123 \
        --from 北京西 --to 长沙南 --from-code BJP --to-code CSQ \
        --date 2026-05-13 --dep-time 09:00 --arr-time 14:30 \
        --seat 二等座 --price 649

  机票:
    python wechat_push.py --mode flight --flight-code CA1234 --airline 中国国航 \
        --from 北京 --to 上海 --from-iata BJS --to-iata SHA \
        --date 2026-05-13 --dep-time 08:00 --arr-time 10:15 \
        --seat 经济舱 --price 850

环境变量（可选，用于微信订阅消息推送）:
  WECHAT_APPID       微信小程序 AppID
  WECHAT_SECRET      微信小程序 AppSecret
  WECHAT_OPENID      接收用户的 OpenID
  WECHAT_TEMPLATE_ID 订阅消息模板 ID（默认使用通用模板）
"""

import argparse
import json
import os
import ssl
import sys
from datetime import datetime
from urllib import request, parse


WECHAT_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
WECHAT_SEND_URL = "https://api.weixin.qq.com/cgi-bin/message/subscribe/send"

DEFAULT_TEMPLATE_ID = "t7kX0Yx9mZ3nL4oP5qR6sT8uV1wX2yA3bC4dE5fG6hI"

# 12306 付款时限（分钟）
PAYMENT_DEADLINE_12306_MIN = 30

# 铁路12306 微信小程序配置
WECHAT_MP_12306_APPID = "wx3a455a4f1266a42a"
WECHAT_MP_12306_TICKET_PATH = "pages/ticket/query/query"


def build_12306_deep_link(from_code, to_code, date_str, secret_key=""):
    """
    构建 12306 预订直达链接。
    
    返回 dict 包含：
    - wechat_scheme: weixin:// 协议，微信内点击跳转小程序
    - wxaurl_scheme: https://wxaurl.cn 明文 Scheme
    - web_url: kyfw 网页链接兜底
    """
    # weixin:// 协议链接（微信内点击直接跳转小程序）
    wechat_scheme = (
        f"weixin://dl/business/?appid={WECHAT_MP_12306_APPID}"
        f"&path={parse.quote(WECHAT_MP_12306_TICKET_PATH, safe='')}"
        f"&query=from_station%3D{from_code}%26to_station%3D{to_code}%26date%3D{date_str}"
    )
    
    # 明文 URL Scheme（微信官方格式）
    wxaurl_scheme = (
        f"https://wxaurl.cn/{WECHAT_MP_12306_APPID}"
        f"/{parse.quote(WECHAT_MP_12306_TICKET_PATH, safe='')}"
        f"?from_station={from_code}&to_station={to_code}&date={date_str}"
    )
    
    # kyfw 网页链接兜底
    params = {
        "linktypeid": "dc",
        "fs": from_code,
        "ts": to_code,
        "date": date_str,
        "flag": "N,N,Y",
    }
    web_url = "https://kyfw.12306.cn/otn/leftTicket/init?" + parse.urlencode(params)
    
    return {
        "wechat_scheme": wechat_scheme,
        "wxaurl_scheme": wxaurl_scheme,
        "web_url": web_url,
    }


def build_ctrip_deep_link(from_iata, to_iata, date_str):
    """
    构建携程机票预订直达链接。
    预填出发/到达城市和日期，用户可直接筛选航班并下单。
    """
    from_iata = from_iata.upper()
    to_iata = to_iata.upper()
    return (
        f"https://flights.ctrip.com/online/list/"
        f"oneway-{from_iata.lower()}-{to_iata.lower()}"
        f"?depdate={date_str}"
    )


def get_access_token(appid, secret):
    """获取微信 access_token。"""
    params = {
        "grant_type": "client_credential",
        "appid": appid,
        "secret": secret,
    }
    url = WECHAT_TOKEN_URL + "?" + parse.urlencode(params)

    ctx = ssl.create_default_context()
    req = request.Request(url)
    try:
        with request.urlopen(req, timeout=15, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return None, f"获取 access_token 失败: {e}"

    if "access_token" in data:
        return data["access_token"], None
    return None, data.get("errmsg", "未知错误")


def send_subscribe_message(access_token, openid, template_id, payment_data):
    """发送票务付款订阅消息到微信。"""
    url = WECHAT_SEND_URL + "?access_token=" + access_token

    body = {
        "touser": openid,
        "template_id": template_id,
        "page": payment_data["pay_url"],
        "data": {
            "thing1": {"value": payment_data["route"]},
            "time2": {"value": f"{payment_data['date']} {payment_data['dep_time']}"},
            "thing3": {"value": payment_data["code_label"]},
            "character_string4": {"value": f"{payment_data['seat']} ¥{payment_data['price']}"},
            "thing5": {"value": payment_data["pay_hint"]},
        },
        "miniprogram": {
            "appid": os.environ.get("WECHAT_APPID", ""),
            "pagepath": payment_data["pay_url"],
        } if os.environ.get("WECHAT_APPID") else None,
    }

    # 清理 None 值
    if body["miniprogram"] is None:
        del body["miniprogram"]

    ctx = ssl.create_default_context()
    req = request.Request(
        url,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with request.urlopen(req, timeout=15, context=ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return False, f"推送请求失败: {e}"

    if result.get("errcode") == 0:
        return True, "推送成功"
    return False, result.get("errmsg", f"推送失败: {json.dumps(result, ensure_ascii=False)}")


def build_payment_data(args):
    """从命令行参数构建付款信息数据结构。"""
    now = datetime.now()

    if args.mode == "train":
        code = args.train_code
        code_label = f"[TRAIN] {code}"
        links = build_12306_deep_link(
            args.from_code or "", args.to_code or "", args.date, args.secret_key or ""
        )
        pay_url = links["wechat_scheme"]
        platform = "12306"
        pay_deadline = "30分钟内"
        pay_hint = "请在30分钟内登录12306完成付款，超时订单自动取消"
    else:
        code = args.flight_code
        airline = args.airline or ""
        code_label = f"[FLIGHT] {code} {airline}".strip()
        pay_url = build_ctrip_deep_link(
            args.from_iata or "", args.to_iata or "", args.date
        )
        platform = "携程"
        pay_deadline = "以页面为准"
        pay_hint = "点击链接前往携程完成预订和付款"

    result = {
        "mode": args.mode,
        "platform": platform,
        "code": code,
        "code_label": code_label,
        "route": f"{args.from_} → {args.to}",
        "date": args.date,
        "dep_time": args.dep_time,
        "arr_time": args.arr_time,
        "seat": args.seat,
        "price": args.price,
        "pay_url": pay_url or args.booking_url or "",
        "pay_deadline": pay_deadline,
        "pay_hint": pay_hint,
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
    }
    if args.mode == "train" and args.from_code and args.to_code:
        result["link_wechat_scheme"] = links["wechat_scheme"]
        result["link_wxaurl_scheme"] = links["wxaurl_scheme"]
        result["link_web_url"] = links["web_url"]
    return result


def format_payment_card(data):
    """生成可复制的付款卡片文本。"""
    platform_icons = {"train": "[12306]", "flight": "[携程]"}

    lines = [
        "========================================",
        f"  {platform_icons.get(data['mode'], '')} 待付款 — 出行票务",
        "========================================",
        "",
        f"  {data['route']}",
        f"  日期：{data['date']}",
        f"  {'车次' if data['mode'] == 'train' else '航班'}：{data['code_label']}",
        f"  出发：{data['dep_time']}  →  到达：{data['arr_time']}",
        f"  席位：{data['seat']}",
        f"  票价：¥{data['price']}",
        "",
        "----------------------------------------",
        f"  付款截止：{data['pay_deadline']}",
        f"  {data['pay_hint']}",
        "----------------------------------------",
        "",
        f"  📱 微信小程序（点击直达12306购票页）：",
        f"  {data.get('link_wechat_scheme', data['pay_url'])}",
        f"  🌐 网页备用：",
        f"  {data.get('link_web_url', '')}",
        "",
        "========================================",
        f"  生成时间：{data['generated_at']}",
        "  长按复制以上信息，分享给微信好友",
        "  微信内点击小程序链接直接跳转铁路12306",
        "========================================",
    ]
    return "\n".join(lines)


def format_payment_card_compact(data):
    """紧凑版付款卡片（适合微信聊天分享）。"""
    lines = [
        f"【待付款】{data['route']}",
        f"日期：{data['date']}",
        f"{'车次' if data['mode'] == 'train' else '航班'}：{data['code_label']}",
        f"时间：{data['dep_time']} → {data['arr_time']}",
        f"席位：{data['seat']} | 票价：¥{data['price']}",
        f"付款截止：{data['pay_deadline']}",
        f"立即付款：{data['pay_url']}",
    ]
    return "\n".join(lines)


def main():
    # 确保 stdout 使用 UTF-8，避免 Windows GBK 编码报错
    if sys.stdout.encoding != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="微信小程序票务付款信息推送")
    parser.add_argument("--mode", required=True, choices=["train", "flight"],
                        help="出行方式")
    # 火车参数
    parser.add_argument("--train-code", help="车次（火车时必填）")
    parser.add_argument("--secret-key", help="12306 secret_key（用于预订）")
    parser.add_argument("--from-code", help="出发站电报码（如 BJP）")
    parser.add_argument("--to-code", help="到达站电报码（如 CSQ）")
    # 飞机参数
    parser.add_argument("--flight-code", help="航班号（飞机时必填）")
    parser.add_argument("--airline", help="航空公司（飞机时选填）")
    parser.add_argument("--from-iata", help="出发城市 IATA 代码（如 BJS）")
    parser.add_argument("--to-iata", help="到达城市 IATA 代码（如 SHA）")
    # 通用参数
    parser.add_argument("--from", dest="from_", required=True, help="出发站/城市名")
    parser.add_argument("--to", required=True, help="到达站/城市名")
    parser.add_argument("--date", required=True, help="出发日期 YYYY-MM-DD")
    parser.add_argument("--dep-time", required=True, help="出发时间 HH:MM")
    parser.add_argument("--arr-time", required=True, help="到达时间 HH:MM")
    parser.add_argument("--seat", required=True, help="席位/舱位")
    parser.add_argument("--price", required=True, help="票价（数字）")
    parser.add_argument("--booking-url", help="自定义购票链接（覆盖自动生成的）")
    parser.add_argument("--openid", help="接收者 OpenID（覆盖环境变量）")

    args = parser.parse_args()

    # 校验 mode-specific 参数
    if args.mode == "train" and not args.train_code:
        print("错误：火车模式需要 --train-code 参数")
        sys.exit(1)
    if args.mode == "flight" and not args.flight_code:
        print("错误：飞机模式需要 --flight-code 参数")
        sys.exit(1)

    payment_data = build_payment_data(args)

    # 检查微信配置
    appid = os.environ.get("WECHAT_APPID", "")
    secret = os.environ.get("WECHAT_SECRET", "")
    openid = args.openid or os.environ.get("WECHAT_OPENID", "")
    template_id = os.environ.get("WECHAT_TEMPLATE_ID", DEFAULT_TEMPLATE_ID)

    if appid and secret and openid:
        print(f"[WeChatPush] 正在推送付款信息到微信 (OpenID: {openid[:6]}***)...")
        access_token, err = get_access_token(appid, secret)
        if err:
            print(f"[WeChatPush] {err}")
            print("[WeChatPush] 回退到可分享付款卡片模式\n")
            print(format_payment_card(payment_data))
            sys.exit(1)

        success, msg = send_subscribe_message(
            access_token, openid, template_id, payment_data
        )
        if success:
            print(json.dumps({
                "status": "pushed",
                "message": "付款信息已推送到微信，请在付款截止前完成支付",
                "payment": payment_data,
            }, ensure_ascii=False, indent=2))
        else:
            print(f"[WeChatPush] 推送失败: {msg}")
            print("[WeChatPush] 回退到可分享付款卡片模式\n")
            print(format_payment_card(payment_data))
    else:
        missing = []
        if not appid:
            missing.append("WECHAT_APPID")
        if not secret:
            missing.append("WECHAT_SECRET")
        if not openid:
            missing.append("WECHAT_OPENID")

        print(json.dumps({
            "status": "card_only",
            "message": f"微信推送未配置（缺少: {', '.join(missing)}）",
            "payment": payment_data,
            "shareable_card": format_payment_card(payment_data),
            "shareable_card_compact": format_payment_card_compact(payment_data),
        }, ensure_ascii=False, indent=2))
        print()
        print(format_payment_card(payment_data))


if __name__ == "__main__":
    main()
