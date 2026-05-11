"""
归一化比价引擎。
将火车票和机票数据归一化，按性价比排序，输出推荐方案。

用法: python compare.py <trains.json> <flights.json> [--mode price|value]
  price: 按绝对价格排序（默认，预算优先）
  value: 按单位时间成本排序
"""

import json
import sys


def parse_duration_to_minutes(dur_str):
    """将 "4h30m" 或 "XhYm" 格式转换为分钟。"""
    dur_str = dur_str.replace("h", ":").replace("m", "")
    parts = dur_str.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return int(parts[0]) * 60


def load_json_file(path):
    """加载 JSON 文件，支持直接传 JSON 字符串。"""
    if path.startswith("{"):
        return json.loads(path)
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def normalize_trains(train_data):
    """将 12306 结果归一化为统一格式，携带付款所需字段。"""
    items = []

    if "error" in train_data:
        return items

    for t in train_data.get("trains", []):
        seats = t.get("seats", {})
        for seat_key in ["ze", "zy", "swz", "tz", "ed", "yd", "yz", "rw", "yw", "wz"]:
            if seat_key in seats and seats[seat_key].get("price") is not None:
                price = seats[seat_key]["price"]
                label = seats[seat_key]["label"]
                items.append({
                    "mode": "train",
                    "id": t["train_code"],
                    "operator": "中国铁路",
                    "from_station": t["dep_station"],
                    "to_station": t["arr_station"],
                    "dep_time": t["dep_time"],
                    "arr_time": t["arr_time"],
                    "duration_min": t["duration_min"],
                    "duration_str": t.get("duration_str", f"{t['duration_min']}min"),
                    "seat_class": label,
                    "price_cny": price,
                    # 付款推送所需字段
                    "secret_key": t.get("secret_key", ""),
                    "booking_url": t.get("booking_url", ""),
                    "dep_station_name": t.get("dep_station", ""),
                    "arr_station_name": t.get("arr_station", ""),
                })
                break

    return items


def normalize_flights(flight_data):
    """将航班结果归一化为统一格式，携带付款所需字段。"""
    items = []

    if "error" in flight_data:
        return items

    for f in flight_data.get("flights", []):
        price = f.get("economy_price")
        if price is None:
            continue

        items.append({
            "mode": "flight",
            "id": f["flight_code"],
            "operator": f.get("airline", "未知航空"),
            "from_station": f.get("dep_airport", ""),
            "to_station": f.get("arr_airport", ""),
            "dep_time": f["dep_time"],
            "arr_time": f["arr_time"],
            "duration_min": f["duration_min"],
            "duration_str": f.get("duration_str", f"{f['duration_min']}min"),
            "seat_class": "经济舱",
            "price_cny": price,
            "stops": f.get("stops", 0),
            # 付款推送所需字段
            "from_city": flight_data.get("from_city", ""),
            "to_city": flight_data.get("to_city", ""),
            "booking_url": f"https://flights.ctrip.com",
        })

    return items


def rank_by_price(items):
    """按价格升序排列。"""
    return sorted(items, key=lambda x: (x["price_cny"], x["duration_min"]))


def rank_by_value(items):
    """按性价比排列：价格/节省时间（每小时的旅行成本越低越好）。"""
    # 找到最快方案
    min_duration = min(item["duration_min"] for item in items) if items else 0
    max_duration = max(item["duration_min"] for item in items) if items else 0
    time_range = max_duration - min_duration or 1

    # 综合评分：价格归一化 + 时间归一化（权重各 50%）
    min_price = min(item["price_cny"] for item in items) if items else 0
    max_price = max(item["price_cny"] for item in items) if items else 0
    price_range = max_price - min_price or 1

    scored = []
    for item in items:
        price_score = (item["price_cny"] - min_price) / price_range
        time_score = (item["duration_min"] - min_duration) / time_range
        value_score = 1 - (price_score * 0.5 + time_score * 0.5)
        scored.append((item, value_score))

    scored.sort(key=lambda x: x[1], reverse=True)
    return [item for item, score in scored]


def generate_recommendation(items, top_n=5):
    """生成推荐理由。"""
    if not items:
        return "暂无可用方案"

    cheapest = min(items, key=lambda x: x["price_cny"])
    fastest = min(items, key=lambda x: x["duration_min"])

    rec_parts = []
    mode_label = {"train": "🚄高铁", "flight": "✈️飞机"}

    # 最便宜
    rec_parts.append(
        f"**最省钱**：{mode_label.get(cheapest['mode'], '')} {cheapest['id']} {cheapest['seat_class']}，"
        f"仅需 ¥{cheapest['price_cny']:.0f}，耗时 {cheapest['duration_str']}"
    )

    # 最快
    if fastest["id"] != cheapest["id"]:
        mode_emoji = "🚄" if fastest["mode"] == "train" else "✈️"
        rec_parts.append(
            f"**最快**：{mode_emoji} {fastest['id']}，仅 {fastest['duration_str']}，"
            f"票价 ¥{fastest['price_cny']:.0f}"
        )

    # 交叉对比
    if cheapest["mode"] != fastest["mode"]:
        time_diff = cheapest["duration_min"] - fastest["duration_min"]
        price_diff = fastest["price_cny"] - cheapest["price_cny"]
        if time_diff > 0 and price_diff > 0:
            per_hour = price_diff / (time_diff / 60)
            rec_parts.append(
                f"💡 {fastest['mode'] == 'flight' and '飞机' or '高铁'}比{cheapest['mode'] == 'flight' and '飞机' or '高铁'}"
                f"快 {int(time_diff / 60)}h{time_diff % 60}m，但贵 ¥{price_diff:.0f}"
                f"（相当于 ¥{per_hour:.0f}/小时买时间）"
            )

    return " | ".join(rec_parts)


def compare(trains_data, flights_data, sort_mode="price"):
    """主比价函数。"""
    train_items = normalize_trains(trains_data)
    flight_items = normalize_flights(flights_data)

    all_items = train_items + flight_items

    if sort_mode == "value":
        ranked = rank_by_value(all_items)
    else:
        ranked = rank_by_price(all_items)

    # 取 top 10
    ranked = ranked[:10]

    # 统计
    train_count = len(train_items)
    flight_count = len(flight_items)

    recommendation = generate_recommendation(ranked)

    return {
        "total_train_options": train_count,
        "total_flight_options": flight_count,
        "total_options": len(all_items),
        "ranked": ranked,
        "recommendation": recommendation,
        "sort_mode": sort_mode,
    }


def format_output(result):
    """格式化输出为 Markdown 表格。"""
    lines = []

    from_city = ""
    to_city = ""
    travel_date = ""

    if result["ranked"]:
        first = result["ranked"][0]
        from_city = first.get("from_station", "")
        to_city = first.get("to_station", "")

    lines.append(f"## 🚀 {from_city} → {to_city} 出行方案")
    lines.append("")

    # 推荐语
    lines.append(f"> {result['recommendation']}")
    lines.append("")

    # 列表
    lines.append("| 排名 | 方式 | 方案 | 舱位 | 出发 | 到达 | 耗时 | 价格 |")
    lines.append("|------|------|------|------|------|------|------|------|")

    for i, item in enumerate(result["ranked"], 1):
        mode_emoji = "🚄" if item["mode"] == "train" else "✈️"
        line = (
            f"| {i} | {mode_emoji} | {item['operator']} {item['id']} | "
            f"{item['seat_class']} | {item['dep_time']} | {item['arr_time']} | "
            f"{item['duration_str']} | ¥{item['price_cny']:.0f} |"
        )
        lines.append(line)

    lines.append("")
    lines.append(f"共找到 {result['total_train_options']} 趟火车 + {result['total_flight_options']} 班航班")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print("用法: python compare.py <trains.json|trains_json_string> <flights.json|flights_json_string> [--mode price|value]")
        sys.exit(1)

    trains_data = load_json_file(sys.argv[1])
    flights_data = load_json_file(sys.argv[2])

    sort_mode = "price"
    if len(sys.argv) >= 4 and sys.argv[3] == "--mode":
        sort_mode = sys.argv[4] if len(sys.argv) > 4 else "price"

    result = compare(trains_data, flights_data, sort_mode)
    print(format_output(result))


if __name__ == "__main__":
    main()
