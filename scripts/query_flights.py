"""
查询航班价格信息。
用法: python query_flights.py <出发城市> <到达城市> [日期]
日期格式: YYYY-MM-DD，默认明天
输出: JSON

数据源优先级:
1. 携程 (Ctrip) 内部 API
2. WebSearch 作为兜底（由调用方 AI Agent 处理）
"""

import json
import os
import sys
import ssl
from datetime import date, timedelta, datetime
from urllib import request, parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from stations import load_stations, find_station, search_city

# 携程航班查询 API（反向工程）
CTRIP_URL = "https://flights.ctrip.com/itinerary/api/12808/products"

# 城市 IATA 代码映射（常用中国机场）
CITY_IATA = {
    "北京": "BJS",
    "上海": "SHA",
    "广州": "CAN",
    "深圳": "SZX",
    "成都": "CTU",
    "杭州": "HGH",
    "武汉": "WUH",
    "西安": "XIY",
    "重庆": "CKG",
    "南京": "NKG",
    "昆明": "KMG",
    "长沙": "CSX",
    "厦门": "XMN",
    "青岛": "TAO",
    "天津": "TSN",
    "大连": "DLC",
    "三亚": "SYX",
    "海口": "HAK",
    "哈尔滨": "HRB",
    "沈阳": "SHE",
    "郑州": "CGO",
    "济南": "TNA",
    "福州": "FOC",
    "贵阳": "KWE",
    "南宁": "NNG",
    "南昌": "KHN",
    "合肥": "HFE",
    "太原": "TYN",
    "石家庄": "SJW",
    "乌鲁木齐": "URC",
    "拉萨": "LXA",
    "呼和浩特": "HET",
    "银川": "INC",
    "西宁": "XNN",
    "兰州": "LHW",
}

# 航空公司代码映射
AIRLINE_MAP = {
    "CA": "中国国航",
    "MU": "东方航空",
    "CZ": "南方航空",
    "HU": "海南航空",
    "3U": "四川航空",
    "ZH": "深圳航空",
    "MF": "厦门航空",
    "FM": "上海航空",
    "GS": "天津航空",
    "SC": "山东航空",
    "8L": "祥鹏航空",
    "9C": "春秋航空",
    "KN": "中国联航",
    "HO": "吉祥航空",
    "G5": "华夏航空",
    "EU": "成都航空",
    "NS": "河北航空",
    "BK": "奥凯航空",
    "JD": "首都航空",
    "PN": "西部航空",
}


def get_city_iata(city_name):
    """获取城市 IATA 代码。"""
    # 精确匹配
    for name, code in CITY_IATA.items():
        if name == city_name or name in city_name or city_name in name:
            return code, name

    # 通过车站名推断
    stations = load_stations()
    matches = find_station(stations, city_name)
    if matches:
        # 取车站名中的城市部分
        station_name = matches[0][0]
        for city in CITY_IATA:
            if city in station_name:
                return CITY_IATA[city], city

    return None, city_name


def query_ctrip(from_city, to_city, travel_date):
    """通过携程 API 查询航班。"""
    from_iata, from_name = get_city_iata(from_city)
    to_iata, to_name = get_city_iata(to_city)

    if not from_iata or not to_iata:
        return None

    payload = {
        "flightWay": "Oneway",
        "classType": "ALL",
        "hasChild": False,
        "hasBaby": False,
        "searchIndex": 1,
        "airportParams": [
            {"dcity": from_iata, "acity": to_iata, "dcityname": from_name, "acityname": to_name, "date": travel_date}
        ],
        "army": "false",
    }

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/125.0.0.0 Safari/537.36"
        ),
        "Content-Type": "application/json",
        "Accept": "application/json",
        "Origin": "https://flights.ctrip.com",
        "Referer": "https://flights.ctrip.com/online/list/oneway-{from_iata}-{to_iata}".format(
            from_iata=from_iata.lower(), to_iata=to_iata.lower()
        ),
    }

    try:
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        data = json.dumps(payload).encode("utf-8")
        req = request.Request(CTRIP_URL, data=data, headers=headers, method="POST")
        with request.urlopen(req, timeout=20, context=ctx) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        return _parse_ctrip_result(result, travel_date)
    except Exception as e:
        return {"error": f"携程查询失败: {str(e)}", "source": "ctrip"}


def _parse_ctrip_result(data, travel_date):
    """解析携程 API 返回数据。"""
    flights = []

    if not isinstance(data, dict) or data.get("code") != 0:
        return {"error": "携程返回数据异常", "source": "ctrip", "details": data}

    route_list = data.get("data", {}).get("routeList", [])
    for route in route_list:
        leg = route.get("legs", [{}])[0]
        for flight_item in leg.get("flights", []):
            dep_datetime = flight_item.get("departureDate", "")
            arr_datetime = flight_item.get("arrivalDate", "")

            # 解析时间
            try:
                dep_dt = datetime.fromisoformat(dep_datetime[:19] if dep_datetime else "")
                arr_dt = datetime.fromisoformat(arr_datetime[:19] if arr_datetime else "")
                duration_min = int((arr_dt - dep_dt).total_seconds() / 60)
                dep_time = dep_dt.strftime("%H:%M")
                arr_time = arr_dt.strftime("%H:%M")
            except (ValueError, TypeError):
                duration_min = 0
                dep_time = dep_datetime
                arr_time = arr_datetime

            flight_code = f"{flight_item.get('flightNumber', '')}"

            # 经济舱价格
            economy_price = None
            cabins = flight_item.get("cabins", [])
            for cabin in cabins:
                if cabin.get("cabinClass") == "Y":  # 经济舱
                    economy_price = cabin.get("price", {}).get("price")
                    break

            if not economy_price and cabins:
                economy_price = cabins[0].get("price", {}).get("price")

            flights.append({
                "flight_code": flight_code,
                "airline": AIRLINE_MAP.get(flight_code[:2], flight_code[:2] + "航空"),
                "dep_airport": flight_item.get("dport", {}).get("name", ""),
                "arr_airport": flight_item.get("aport", {}).get("name", ""),
                "dep_time": dep_time,
                "arr_time": arr_time,
                "duration_min": duration_min,
                "duration_str": f"{duration_min // 60}h{duration_min % 60}m",
                "economy_price": economy_price,
                "stops": flight_item.get("stopCount", 0),
                "aircraft": flight_item.get("craftTypeName", ""),
            })

    # 按价格排序
    flights.sort(key=lambda f: f["economy_price"] or float("inf"))

    return {
        "source": "ctrip",
        "from_city": from_city,
        "to_city": to_city,
        "date": travel_date,
        "count": len(flights),
        "flights": flights,
    }


def query_websearch_placeholder(from_city, to_city, travel_date):
    """
    返回 WebSearch 指令，供 AI Agent 执行搜索。
    当携程 API 不可用时使用此兜底方案。
    """
    return {
        "source": "websearch",
        "from_city": from_city,
        "to_city": to_city,
        "fallback": True,
        "search_query": f"{from_city} 到 {to_city} {travel_date} 机票价格",
        "instructions": (
            "携程 API 不可用。请使用 WebSearch 搜索以上关键词，"
            "从搜索结果中提取航班号、出发到达时间、价格信息，"
            "然后调用 compare.py 进行比价。"
        ),
    }


def main():
    if len(sys.argv) < 3:
        print("用法: python query_flights.py <出发城市> <到达城市> [日期]")
        print("日期默认明天，格式 YYYY-MM-DD")
        sys.exit(1)

    from_city = sys.argv[1]
    to_city = sys.argv[2]

    if len(sys.argv) >= 4:
        travel_date = sys.argv[3]
    else:
        travel_date = (date.today() + timedelta(days=1)).isoformat()

    # 先尝试携程 API
    result = query_ctrip(from_city, to_city, travel_date)

    # 如果携程失败，返回 WebSearch 兜底指令
    if result is None or "error" in result:
        fallback = query_websearch_placeholder(from_city, to_city, travel_date)
        if result is None:
            result = fallback
        else:
            result["fallback"] = fallback

    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
