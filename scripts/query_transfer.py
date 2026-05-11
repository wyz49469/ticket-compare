"""
中转路线搜索引擎。
当 A→B 无直达或直达不满足截止时间时，搜索 1-2 次中转方案。

用法: python query_transfer.py <出发城市> <到达城市> <日期> [--deadline HH:MM] [--max-transfer 2]
"""

import json
import sys
import os
from datetime import date, timedelta

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
from stations import load_stations, find_station, get_main_station
from query_trains import query_tickets
from query_flights import query_ctrip

# 全国枢纽城市（按区域分组）
HUBS = {
    "north": ["北京", "天津", "石家庄"],
    "northeast": ["沈阳", "哈尔滨", "长春", "大连"],
    "east": ["上海", "南京", "杭州", "济南", "合肥"],
    "central": ["郑州", "武汉", "长沙", "南昌"],
    "south": ["广州", "深圳", "南宁"],
    "southwest": ["成都", "重庆", "贵阳", "昆明"],
    "northwest": ["西安", "兰州", "乌鲁木齐"],
}

# 区域归属（按省份/地理位置）
REGION_MAP = {
    # 东北
    "哈尔滨": "northeast", "齐齐哈尔": "northeast", "牡丹江": "northeast",
    "长春": "northeast", "吉林": "northeast",
    "沈阳": "northeast", "大连": "northeast",
    "漠河": "northeast", "加格达奇": "northeast", "黑河": "northeast",
    # 华北
    "北京": "north", "天津": "north", "石家庄": "north", "太原": "north",
    "呼和浩特": "north",
    # 华东
    "上海": "east", "南京": "east", "杭州": "east", "合肥": "east",
    "济南": "east", "青岛": "east", "福州": "east", "厦门": "east",
    # 华中
    "郑州": "central", "武汉": "central", "长沙": "central", "南昌": "central",
    "岳阳": "central",
    # 华南
    "广州": "south", "深圳": "south", "南宁": "south", "海口": "south", "三亚": "south",
    # 西南
    "成都": "southwest", "重庆": "southwest", "贵阳": "southwest",
    "昆明": "southwest", "拉萨": "southwest",
    # 西北
    "西安": "northwest", "兰州": "northwest", "乌鲁木齐": "northwest",
    "西宁": "northwest", "银川": "northwest",
}


def get_region(city):
    """获取城市所属区域。"""
    for name in REGION_MAP:
        if name in city or city in name:
            return REGION_MAP[name]
    return None


def select_hubs(from_city, to_city, max_hubs=4):
    """
    根据出发和到达城市，选择合理的中转枢纽。
    优先选择地理上位于两地之间的枢纽。
    """
    from_region = get_region(from_city)
    to_region = get_region(to_city)

    candidates = []

    # 规则1：如果跨大区，优先选连接两区的枢纽
    if from_region and to_region and from_region != to_region:
        # 中部枢纽几乎总是好选择
        if from_region != "central" and to_region != "central":
            candidates.extend(HUBS["central"])
        # 北京是通用枢纽
        if from_region != "north" and to_region != "north":
            candidates.extend(HUBS["north"])
        # 如果一方是东北，加沈阳/哈尔滨
        if from_region == "northeast" or to_region == "northeast":
            candidates.extend(HUBS["northeast"])
        # 如果一方是西北，加西安/兰州
        if from_region == "northwest" or to_region == "northwest":
            candidates.extend(HUBS["northwest"])
        # 如果一方是西南，加成都/重庆
        if from_region == "southwest" or to_region == "southwest":
            candidates.extend(HUBS["southwest"])

    # 规则2：出发地和目的地的本区枢纽
    if from_region:
        candidates.extend(HUBS.get(from_region, []))
    if to_region:
        candidates.extend(HUBS.get(to_region, []))

    # 去重并排除出发/到达城市本身
    unique = []
    for c in candidates:
        if c not in unique and c not in from_city and c not in to_city:
            unique.append(c)

    return unique[:max_hubs]


def parse_time(t):
    """解析 HH:MM 为分钟数。"""
    parts = t.split(":")
    return int(parts[0]) * 60 + int(parts[1])


def format_duration(minutes):
    h = minutes // 60
    m = minutes % 60
    return f"{h}h{m:02d}m" if m else f"{h}h"


def search_one_transfer(from_city, to_city, travel_date, deadline_min=None):
    """
    搜索 1 次中转方案：A → Hub → B。
    使用精确的 datetime 计算到达日期和换乘时间。
    """
    from datetime import datetime, timedelta
    hubs = select_hubs(from_city, to_city, max_hubs=5)
    results = []

    base_date = datetime.fromisoformat(travel_date)

    for hub in hubs:
        leg1 = query_tickets(from_city, hub, travel_date)
        if "error" in leg1:
            continue

        # Hub→B 查询日期范围（出发日 + 后 2 天，覆盖长距离到达）
        dates_to_check = [travel_date]
        for offset in [1, 2]:
            dates_to_check.append((base_date + timedelta(days=offset)).strftime('%Y-%m-%d'))

        for d2 in dates_to_check:
            leg2 = query_tickets(hub, to_city, d2)
            if "error" in leg2:
                continue

            for t1 in leg1.get("trains", []):
                # Leg1: departure datetime = base_date + dep_time
                t1_dep_dt = _make_dt(base_date, t1["dep_time"])
                t1_arr_dt = t1_dep_dt + timedelta(minutes=t1["duration_min"])

                for t2 in leg2.get("trains", []):
                    # Leg2: departure datetime = d2 + dep_time
                    t2_base = datetime.fromisoformat(d2)
                    t2_dep_dt = _make_dt(t2_base, t2["dep_time"])
                    t2_arr_dt = t2_dep_dt + timedelta(minutes=t2["duration_min"])

                    # 换乘时间：t2 出发 - t1 到达
                    transfer_min = int((t2_dep_dt - t1_arr_dt).total_seconds() / 60)

                    if transfer_min < 30:
                        continue  # 换乘不足 30 分钟
                    if transfer_min > 24 * 60:
                        continue  # 换乘超过 24 小时不合理，排除

                    # 总时间：最终到达 - 最初出发
                    total_min = int((t2_arr_dt - t1_dep_dt).total_seconds() / 60)

                    # 检查截止时间
                    if deadline_min is not None:
                        deadline_dt = _make_dt(base_date, "%02d:%02d" % (deadline_min // 60, deadline_min % 60))
                        # 如果 deadline 在 base_date 之后几天
                        # 简化：计算 total_min 是否超过 deadline 允许的范围
                        # deadline = 从 base_date 00:00 起算的分钟数
                        if total_min > deadline_min:
                            continue

                    # 提取价格
                    t1_price = _get_best_price(t1)
                    t2_price = _get_best_price(t2)

                    results.append({
                        "transfers": 1,
                        "legs": [
                            {
                                "mode": "train",
                                "from": from_city, "to": hub,
                                "train_code": t1["train_code"],
                                "dep_time": t1["dep_time"], "arr_time": t1["arr_time"],
                                "duration_str": t1["duration_str"], "duration_min": t1["duration_min"],
                                "date": travel_date,
                                "dep_dt_str": t1_dep_dt.strftime("%m/%d %H:%M"),
                                "arr_dt_str": t1_arr_dt.strftime("%m/%d %H:%M"),
                                "seat": t1.get("_best_seat_label", ""),
                                "price": t1_price,
                            },
                            {
                                "mode": "train",
                                "from": hub, "to": to_city,
                                "train_code": t2["train_code"],
                                "dep_time": t2["dep_time"], "arr_time": t2["arr_time"],
                                "duration_str": t2["duration_str"], "duration_min": t2["duration_min"],
                                "date": d2,
                                "dep_dt_str": t2_dep_dt.strftime("%m/%d %H:%M"),
                                "arr_dt_str": t2_arr_dt.strftime("%m/%d %H:%M"),
                                "seat": t2.get("_best_seat_label", ""),
                                "price": t2_price,
                            },
                        ],
                        "transfer_at": hub,
                        "transfer_min": transfer_min,
                        "total_duration_min": total_min,
                        "total_duration_str": format_duration(total_min),
                        "total_price": t1_price + t2_price,
                    })

    # 排序：换乘次数 > 总时间 > 总价
    results.sort(key=lambda r: (r["transfers"], r["total_duration_min"], r["total_price"]))
    return results


def _make_dt(base_date, time_str):
    """构造 datetime：base_date + time_str (HH:MM)。"""
    from datetime import datetime, timedelta
    parts = time_str.split(":")
    h, m = int(parts[0]), int(parts[1])
    return base_date.replace(hour=h, minute=m, second=0, microsecond=0)


def _get_best_price(train):
    """获取车次的最佳可购票价（优先二等座/硬座）。"""
    seats = train.get("seats", {})
    priority = ["ze", "yz", "zy", "yw", "rw", "swz"]

    best_price = None
    best_label = ""
    for key in priority:
        if key in seats and seats[key].get("price") is not None:
            best_price = seats[key]["price"]
            best_label = seats[key]["label"]
            break

    if best_price is None:
        for key, info in seats.items():
            if info.get("price") is not None:
                best_price = info["price"]
                best_label = info["label"]
                break

    # 临时存储标签
    train["_best_seat_label"] = best_label
    return best_price or 0


def format_transfer_output(results, from_city, to_city, travel_date):
    """格式化中转方案输出。"""
    if not results:
        return f"## [TRANSFER] {from_city} → {to_city}\n\n> 未找到可行的中转方案"

    lines = [
        f"## [TRANSFER] {from_city} → {to_city} 中转方案 | {travel_date}",
        "",
        f"> 无直达车次，找到 {len(results)} 个中转方案",
        "",
    ]

    # 展示 top 5
    for i, r in enumerate(results[:5], 1):
        lines.append(f"### 方案 {i}：经 **{r['transfer_at']}** 中转（1次换乘）")
        lines.append("")
        lines.append("| 段 | 方式 | 车次 | 日期 | 出发 | 到达 | 耗时 | 席位 | 价格 |")
        lines.append("|----|------|------|------|------|------|------|------|------|")

        for j, leg in enumerate(r["legs"]):
            seg_label = ["①", "②"][j]
            lines.append(
                f"| {seg_label} {leg['from']}→{leg['to']} | [TRAIN] | {leg['train_code']} | "
                f"{leg['date']} | {leg['dep_time']} | {leg['arr_time']} | "
                f"{leg['duration_str']} | {leg['seat']} | Y{leg['price']:.0f} |"
            )

        lines.append("")
        lines.append(f"| 换乘 | 在 **{r['transfer_at']}** 等候 **{format_duration(r['transfer_min'])}** |")
        lines.append(f"| **总计** | **Y{r['total_price']:.0f}** | **{r['total_duration_str']}** |")
        lines.append("")

    return "\n".join(lines)


def main():
    if len(sys.argv) < 3:
        print("用法: python query_transfer.py <出发城市> <到达城市> <日期> [--deadline HH:MM]")
        sys.exit(1)

    from_city = sys.argv[1]
    to_city = sys.argv[2]
    travel_date = sys.argv[3] if len(sys.argv) >= 4 else (date.today() + timedelta(days=1)).isoformat()

    deadline_min = None
    if "--deadline" in sys.argv:
        idx = sys.argv.index("--deadline")
        if idx + 1 < len(sys.argv):
            deadline_min = parse_time(sys.argv[idx + 1])

    # 先检查直达
    direct = query_tickets(from_city, to_city, travel_date)
    has_direct = "error" not in direct and direct.get("count", 0) > 0

    if has_direct and deadline_min is None:
        print(json.dumps({
            "has_direct": True,
            "direct_count": direct["count"],
            "message": f"已有 {direct['count']} 趟直达车次，无需中转。如需中转方案请加 --deadline 参数",
        }, ensure_ascii=False, indent=2))
        return

    # 搜索中转方案
    results = search_one_transfer(from_city, to_city, travel_date, deadline_min)

    output = format_transfer_output(results, from_city, to_city, travel_date)
    print(output)


if __name__ == "__main__":
    main()
