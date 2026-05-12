"""
微信小程序票务付款信息推送。
将选定的出行方案推送到用户微信，或生成可分享的付款卡片。

用法:
  火车票:
    python wechat_push.py --mode train --train-code G89 \
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

# 城市名 → 拼音（携程 URL 参数用）
CITY_PINYIN_MAP = {
    "北京": "beijing", "上海": "shanghai", "广州": "guangzhou",
    "深圳": "shenzhen", "成都": "chengdu", "杭州": "hangzhou",
    "武汉": "wuhan", "西安": "xian", "重庆": "chongqing",
    "南京": "nanjing", "长沙": "changsha", "天津": "tianjin",
    "苏州": "suzhou", "郑州": "zhengzhou", "东莞": "dongguan",
    "青岛": "qingdao", "沈阳": "shenyang", "宁波": "ningbo",
    "昆明": "kunming", "大连": "dalian", "厦门": "xiamen",
    "合肥": "hefei", "佛山": "foshan", "福州": "fuzhou",
    "哈尔滨": "haerbin", "济南": "jinan", "温州": "wenzhou",
    "长春": "changchun", "石家庄": "shijiazhuang",
    "常州": "changzhou", "泉州": "quanzhou", "南宁": "nanning",
    "贵阳": "guiyang", "南昌": "nanchang", "太原": "taiyuan",
    "烟台": "yantai", "嘉兴": "jiaxing", "南通": "nantong",
    "金华": "jinhua", "珠海": "zhuhai", "惠州": "huizhou",
    "徐州": "xuzhou", "海口": "haikou", "兰州": "lanzhou",
    "贵阳": "guiyang", "无锡": "wuxi", "桂林": "guilin",
    "三亚": "sanya", "拉萨": "lasa", "银川": "yinchuan",
    "呼和浩特": "huhehaote", "西宁": "xining",
}


def build_12306_deep_link(from_code, to_code, date_str):
    """
    构建 12306 直达链接。

    返回:
      wechat_scheme — 主链接，微信内点击跳转 12306 小程序
      web_url      — 降级链接，非微信环境 / 小程序不可用时打开网页版
    """
    wechat_scheme = (
        f"weixin://dl/business/?appid={WECHAT_MP_12306_APPID}"
        f"&path={parse.quote(WECHAT_MP_12306_TICKET_PATH, safe='')}"
        f"&query=from_station%3D{from_code}%26to_station%3D{to_code}%26date%3D{date_str}"
    )

    params = {
        "linktypeid": "dc",
        "fs": from_code,
        "ts": to_code,
        "date": date_str,
        "flag": "N,N,Y",
    }
    web_url = "https://kyfw.12306.cn/otn/leftTicket/init?" + parse.urlencode(params)

    return {"wechat_scheme": wechat_scheme, "web_url": web_url}


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


def _extract_city_name(station_name):
    """从车站名提取城市名。北京西→北京，长沙南→长沙。"""
    suffixes = ["虹桥", "南站", "北站", "西站", "东站", "站", "南", "北", "西", "东", "大兴"]
    for s in sorted(suffixes, key=len, reverse=True):
        if station_name.endswith(s) and len(station_name) > len(s):
            return station_name[:-len(s)]
    return station_name


def _city_to_pinyin(city_name):
    """中文城市名→拼音。先查映射表，再尝试从 stations_full.json 推导。"""
    if city_name in CITY_PINYIN_MAP:
        return CITY_PINYIN_MAP[city_name]
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        cache = os.path.join(script_dir, "stations_full.json")
        if os.path.exists(cache):
            with open(cache, "r", encoding="utf-8") as f:
                stations_full = json.load(f)
            for name, info in stations_full.items():
                if name.startswith(city_name) and "pinyin" in info:
                    p = info["pinyin"]
                    for sfx in ["nan", "bei", "xi", "dong", "hongqiao", "zhan", "cheng", "da"]:
                        if p.endswith(sfx) and len(p) > len(sfx):
                            return p[:-len(sfx)]
                    return p
    except Exception:
        pass
    return None


def build_ctrip_train_booking_url(train_code, from_station_cn, to_station_cn, date_str):
    """携程火车票预订确认页 — 直达指定车次，填乘客信息后支付。"""
    return (
        f"https://trains.ctrip.com/webapp/train-main/trainXPage"
        f"?departStation={parse.quote(from_station_cn)}"
        f"&arriveStation={parse.quote(to_station_cn)}"
        f"&departDate={date_str}"
        f"&trainNo={train_code}"
        f"&companyId="
        f"&isStudent=0"
    )


def build_ctrip_app_scheme(from_cn, to_cn, date_str, train_code):
    """携程 App URL Scheme — 唤起携程 App 到指定车次。"""
    return (
        f"ctrip://trainbooking"
        f"?from={parse.quote(from_cn)}"
        f"&to={parse.quote(to_cn)}"
        f"&date={date_str}"
        f"&trainNo={train_code}"
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

    ctrip_url = ""
    ctrip_app = ""

    if args.mode == "train":
        code = args.train_code
        code_label = f"🚄 {code}"

        # 携程 trainXPage 预订确认页（用站名，不需拼音）
        ctrip_url = build_ctrip_train_booking_url(
            args.train_code, args.from_, args.to, args.date
        )
        ctrip_app = build_ctrip_app_scheme(
            args.from_, args.to, args.date, args.train_code
        )

        # 12306 链接始终作为回退
        links_12306 = build_12306_deep_link(
            args.from_code or "", args.to_code or "", args.date
        )

        pay_url = ctrip_url
        platform = "携程 → 12306"
        pay_deadline = "以携程页面为准"
        pay_hint = "点击链接直接进入该车次预订确认页，填写乘客信息后支付"
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
    if args.mode == "train":
        result["link_ctrip_web"] = ctrip_url
        result["link_ctrip_app"] = ctrip_app
        result["link_12306_wechat"] = links_12306["wechat_scheme"]
        result["link_12306_web"] = links_12306["web_url"]
        result["fallback_url"] = links_12306["web_url"]
    return result


def format_payment_card(data):
    """生成可复制的付款卡片文本。"""
    mode_icon = "🚄" if data["mode"] == "train" else "✈️"

    lines = [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"  {mode_icon} 待付款 — {data['platform']}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "",
        f"  {data['route']}",
        f"  日期：{data['date']}",
        f"  {'车次' if data['mode'] == 'train' else '航班'}：{data['code_label']}",
        f"  出发：{data['dep_time']} → 到达：{data['arr_time']}",
        f"  席位：{data['seat']}  票价：¥{data['price']}",
        "",
        "  ── 付款信息 ──",
        f"  截止：{data['pay_deadline']}",
        f"  {data['pay_hint']}",
        "",
    ]

    if data["mode"] == "train":
        if data.get("link_ctrip_web"):
            lines.append(f"  🚄 携程预订直达：{data['link_ctrip_web']}")
        if data.get("link_12306_web"):
            lines.append(f"  🌐 12306 备用：{data['link_12306_web']}")
    else:
        lines.append(f"  👇 点击链接付款")
        lines.append(f"  {data['pay_url']}")

    lines += [
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"  生成时间：{data['generated_at']}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
    ]
    return "\n".join(lines)


def format_payment_card_compact(data):
    """紧凑版付款卡片（适合微信聊天分享）。"""
    lines = [
        f"【待付款】{data['route']}  {data['date']}",
        f"{'车次' if data['mode'] == 'train' else '航班'}：{data['code_label']}  {data['dep_time']}→{data['arr_time']}",
        f"席位：{data['seat']}  ¥{data['price']}  |  截止：{data['pay_deadline']}",
    ]
    if data["mode"] == "train" and data.get("link_ctrip_web"):
        lines.append(f"👇 {data['link_ctrip_web']}")
    else:
        lines.append(f"👇 {data['pay_url']}")
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
