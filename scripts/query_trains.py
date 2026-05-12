"""
查询 12306 余票信息。
用法: python query_trains.py <出发城市> <到达城市> <日期>
日期格式: YYYY-MM-DD，默认明天
输出: JSON
"""

import json
import os
import re
import sys
import ssl
from datetime import date, timedelta
from urllib import request, parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from stations import load_stations, get_main_station, find_station

QUERY_URL = "https://kyfw.12306.cn/otn/leftTicket/queryU"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    ),
    "Cookie": "RAIL_EXPIRATION=999999999999; RAIL_DEVICEID=dummy",
    "Accept": "*/*",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Referer": "https://kyfw.12306.cn/otn/leftTicket/init",
}

# 12306 席位类型代码 → 中文名
SEAT_CODE_MAP = {
    "9": ("swz", "商务座"),
    "P": ("tz", "特等座"),
    "M": ("zy", "一等座"),
    "O": ("ze", "二等座"),
    "6": ("gr", "高级软卧"),
    "4": ("rw", "软卧"),
    "3": ("yw", "硬卧"),
    "2": ("rz", "软座"),
    "1": ("yz", "硬座"),
    "W": ("wz", "无座"),
    "F": ("dw", "动卧"),
    "A": ("gjrw", "高级动卧"),
    "I": ("yd", "一等卧"),
    "J": ("ed", "二等卧"),
}

# 可用性字段索引映射（字段 [23]-[33]）
AVAIL_IDXS = {
    "9": 23,   # 商务座
    "P": 24,   # 特等座
    "M": 25,   # 一等座
    "O": 26,   # 二等座
    "6": 27,   # 高级软卧
    "4": 28,   # 软卧
    "3": 29,   # 硬卧
    "2": 30,   # 软座
    "1": 31,   # 硬座
    "W": 32,   # 无座
    "F": 45,   # 动卧
    "A": 46,   # 高级动卧
    "I": 45,   # 一等卧 (共享 F 索引)
    "J": 46,   # 二等卧 (共享 A 索引)
}


def parse_packed_prices(price_str):
    """
    解析复合价格字符串。
    格式: <席位代码><7位价格(毫元)><2位标记>...
    每块 10 字符，重复至字符串结束。
    返回 {seat_key: {"label": ..., "price": ...}, ...}
    """
    if not price_str:
        return {}

    prices = {}
    pos = 0
    while pos + 10 <= len(price_str):
        code = price_str[pos]
        price_raw = price_str[pos + 1 : pos + 8]
        # flags = price_str[pos + 8 : pos + 10]

        if code in SEAT_CODE_MAP:
            key, label = SEAT_CODE_MAP[code]
            try:
                price_yuan = int(price_raw) / 1000.0
            except ValueError:
                pos += 10
                continue

            # 如果有重复的席位（如不同折扣），保留最低价
            if key not in prices or price_yuan < prices[key]["price"]:
                prices[key] = {"label": label, "price": price_yuan}

        pos += 10

    # 处理不到 10 字符的尾部
    if pos < len(price_str):
        remaining = price_str[pos:]
        code = remaining[0]
        if code in SEAT_CODE_MAP:
            key, label = SEAT_CODE_MAP[code]
            try:
                price_raw = remaining[1:].split("O")[0].split("M")[0].split("9")[0].split("P")[0].split("W")[0]
                # Last block might be shorter - try common separators
                price_raw = "".join(c for c in remaining[1:] if c.isdigit())
                if price_raw:
                    price_yuan = int(price_raw) / 1000.0
                    if key not in prices or price_yuan < prices[key]["price"]:
                        prices[key] = {"label": label, "price": price_yuan}
            except (ValueError, IndexError):
                pass

    return prices


def parse_availability(parts):
    """从响应字段中提取各席位余票状态。"""
    avail = {}
    for code, idx in AVAIL_IDXS.items():
        if code in SEAT_CODE_MAP and idx < len(parts):
            key, label = SEAT_CODE_MAP[code]
            val = parts[idx]
            if val and val != "*" and val != "无":
                avail[key] = {"label": label, "count": val}
    return avail


def parse_duration(dur_str):
    parts = dur_str.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def format_duration(minutes):
    h = minutes // 60
    m = minutes % 60
    return f"{h}h{m:02d}m" if m else f"{h}h"


def query_tickets(from_city, to_city, travel_date):
    stations = load_stations()

    from_matches = find_station(stations, from_city)
    if not from_matches:
        return {"error": f"未找到出发车站: '{from_city}'，请输入完整城市名，如 '北京南'"}
    from_info = get_main_station(stations, from_city)
    if not from_info:
        return {"error": f"无法确定出发站代码: '{from_city}'"}
    from_code = from_info[0]

    to_matches = find_station(stations, to_city)
    if not to_matches:
        return {"error": f"未找到到达车站: '{to_city}'，请输入完整城市名，如 '上海虹桥'"}
    to_info = get_main_station(stations, to_city)
    if not to_info:
        return {"error": f"无法确定到达站代码: '{to_city}'"}
    to_code = to_info[0]

    params = {
        "leftTicketDTO.train_date": travel_date,
        "leftTicketDTO.from_station": from_code,
        "leftTicketDTO.to_station": to_code,
        "purpose_codes": "ADULT",
    }
    url = QUERY_URL + "?" + parse.urlencode(params)

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = request.Request(url, headers=HEADERS)
        with request.urlopen(req, timeout=20, context=ctx) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": f"12306 查询失败: {str(e)}"}

    if not data.get("status") or not data.get("data"):
        return {"error": "12306 返回数据异常", "details": data}

    result_rows = data["data"].get("result", [])
    station_map = data["data"].get("map", {})

    trains = []
    for row in result_rows:
        parts = row.split("|")
        if len(parts) < 40:
            continue

        secret_key = parts[0]
        train_code = parts[3]
        dep_station_code = parts[6]
        arr_station_code = parts[7]
        dep_time = parts[8]
        arr_time = parts[9]
        duration_str = parts[10]
        duration_min = parse_duration(duration_str)
        can_buy = parts[11]

        dep_station_name = station_map.get(dep_station_code, dep_station_code)
        arr_station_name = station_map.get(arr_station_code, arr_station_code)

        # 解析价格（从复合字段 [39]）
        price_str_primary = parts[39] if len(parts) > 39 else ""
        prices = {}
        if price_str_primary:
            prices = parse_packed_prices(price_str_primary)

        # 补充字段 [47]（部分车次的价格在另一个字段）
        if len(parts) > 47 and len(prices) < 2:
            extra = parse_packed_prices(parts[47])
            for k, v in extra.items():
                if k not in prices:
                    prices[k] = v

        # 解析可用性
        avail = parse_availability(parts)

        # 合并价格和可用性
        seats = {}
        for key, price_info in prices.items():
            if key in avail:
                seats[key] = {
                    "label": price_info["label"],
                    "price": price_info["price"],
                    "count": avail[key]["count"],
                }
            else:
                seats[key] = {
                    "label": price_info["label"],
                    "price": price_info["price"],
                    "count": "有",
                }

        # 只有可用性没有价格的（兜底）
        for key, avail_info in avail.items():
            if key not in seats:
                seats[key] = {
                    "label": avail_info["label"],
                    "price": None,
                    "count": avail_info["count"],
                }

        trains.append({
            "train_code": train_code,
            "secret_key": secret_key,
            "dep_station": dep_station_name,
            "arr_station": arr_station_name,
            "dep_station_code": dep_station_code,
            "arr_station_code": arr_station_code,
            "dep_time": dep_time,
            "arr_time": arr_time,
            "duration_min": duration_min,
            "duration_str": format_duration(duration_min),
            "can_buy": can_buy == "Y",
            "seats": seats,
            "booking_url": "https://kyfw.12306.cn/otn/leftTicket/init?linktypeid=dc"
        })

    trains.sort(key=lambda t: t["dep_time"])

    return {
        "from_city": from_city,
        "to_city": to_city,
        "date": travel_date,
        "count": len(trains),
        "trains": trains,
    }


def main():
    if len(sys.argv) < 3:
        print("用法: python query_trains.py <出发城市> <到达城市> [日期]")
        print("日期默认明天，格式 YYYY-MM-DD")
        sys.exit(1)

    from_city = sys.argv[1]
    to_city = sys.argv[2]

    if len(sys.argv) >= 4 and not sys.argv[3].startswith("--"):
        travel_date = sys.argv[3]
    else:
        travel_date = (date.today() + timedelta(days=1)).isoformat()

    result = query_tickets(from_city, to_city, travel_date)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
