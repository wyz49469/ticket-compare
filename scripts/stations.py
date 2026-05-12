"""
12306 车站名称 → 代码映射。
从 12306 下载 station_name.js 并解析为 JSON 缓存。
"""

import json
import os
import re
import ssl
import sys
from urllib import request

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CACHE_FILE = os.path.join(SCRIPT_DIR, "stations.json")
CACHE_FILE_FULL = os.path.join(SCRIPT_DIR, "stations_full.json")

STATION_URL = (
    "https://kyfw.12306.cn/otn/resources/js/framework/"
    "station_name.js?station_version=1.9378"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )
}


def download_stations():
    """下载并解析 station_name.js，返回 {站名: 代码} 字典。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = request.Request(STATION_URL, headers=HEADERS)
    with request.urlopen(req, timeout=15, context=ctx) as resp:
        text = resp.read().decode("utf-8")

    # 解析 @站名拼音|站名|代码|拼音|简拼|序号 格式
    stations = {}
    stations_full = {}
    for m in re.finditer(r"@[^|]+\|([^|]+)\|([A-Z]+)\|([^|]+)\|[^|]+\|\d+", text):
        name = m.group(1)
        code = m.group(2)
        pinyin = m.group(3)
        stations[name] = code
        stations_full[name] = {"code": code, "pinyin": pinyin}

    with open(CACHE_FILE, "w", encoding="utf-8") as f:
        json.dump(stations, f, ensure_ascii=False, indent=2)
    with open(CACHE_FILE_FULL, "w", encoding="utf-8") as f:
        json.dump(stations_full, f, ensure_ascii=False, indent=2)

    return stations


def load_stations(force_refresh=False):
    """加载车站映射（优先用缓存）。"""
    if not force_refresh and os.path.exists(CACHE_FILE):
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return download_stations()


def load_stations_with_pinyin(force_refresh=False):
    """加载含拼音的车站映射 {name: {code, pinyin}}（优先用缓存）。"""
    if not force_refresh and os.path.exists(CACHE_FILE_FULL):
        with open(CACHE_FILE_FULL, "r", encoding="utf-8") as f:
            return json.load(f)
    download_stations()
    if os.path.exists(CACHE_FILE_FULL):
        with open(CACHE_FILE_FULL, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def find_station(stations, city):
    """根据城市名找车站代码。优先精确匹配，再模糊匹配。"""
    # 精确匹配
    for name, code in stations.items():
        if city == name:
            return [(name, code)]

    # 城市名匹配（如 "北京" → 北京南/北京西/北京/北京北）
    results = []
    for name, code in stations.items():
        if city in name:
            results.append((name, code))

    return results if results else []


def get_main_station(stations, city):
    """获取该城市的主车站代码（优先选含"南"或直接匹配城市名的车站）。"""
    matches = find_station(stations, city)
    if not matches:
        return None

    # 优先：直接匹配城市名字的主站
    for name, code in matches:
        if name == city or name == city + "站":
            return code, name

    # 其次：城市名 + 南
    for name, code in matches:
        if name == city + "南":
            return code, name

    # 其次：城市名
    for name, code in matches:
        if name == city:
            return code, name

    # 兜底：第一个匹配
    return matches[0][1], matches[0][0]


def search_city(stations, keyword):
    """模糊搜索车站，返回匹配列表。"""
    results = []
    kw = keyword.lower()
    for name, code in stations.items():
        if kw in name.lower() or kw in code.lower():
            results.append((name, code))
    return results


if __name__ == "__main__":
    stations = load_stations()
    print(f"已加载 {len(stations)} 个车站")

    if len(sys.argv) > 1:
        query = sys.argv[1]
        matches = search_city(stations, query)
        if matches:
            for name, code in matches:
                print(f"  {name} → {code}")
        else:
            print(f"  未找到匹配 '{query}' 的车站")
    else:
        # 示例城市
        for city in ["北京", "上海", "广州", "深圳", "成都", "杭州", "武汉", "西安"]:
            code = get_main_station(stations, city)
            if code:
                print(f"  {city} → {code[0]} ({code[1]})")
