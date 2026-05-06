#!/usr/bin/env python3
"""
晚霞预测 — 双引擎日落质量预报
================================

引擎 1 (主): Sunsethue API — 专业日落质量模型，需要 API key
引擎 2 (兜底): Open-Meteo — 免费天气 API + 小时级云量评分算法

位置解析: 手动配置 > 城市名映射 > 时区兜底

用法:
    python3 predict-sunset.py                    # 默认位置（杭州）
    python3 predict-sunset.py --location 北京     # 指定城市
    python3 predict-sunset.py --lat 30.27 --lng 120.15  # 精确坐标
    python3 predict-sunset.py --date 2026-05-07  # 指定日期
    python3 predict-sunset.py --type sunrise     # 朝霞预测
    python3 predict-sunset.py --discord          # Discord 格式输出

环境变量:
    SUNSETHUE_API_KEY    — Sunsethue API key（可选）
    SUNSET_LOCATION      — 默认城市名（可选，默认 "杭州"）
"""

import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta

# ── 城市坐标映射 ─────────────────────────────────────────────

LOCATION_MAP = {
    "杭州": (30.2741, 120.1551),
    "北京": (39.9042, 116.4074),
    "上海": (31.2304, 121.4737),
    "深圳": (22.5431, 114.0579),
    "广州": (23.1291, 113.2644),
    "成都": (30.5728, 104.0668),
    "南京": (32.0603, 118.7969),
    "苏州": (31.2990, 120.5853),
    "武汉": (30.5928, 114.3055),
    "长沙": (28.2282, 112.9388),
    "重庆": (29.4316, 106.9123),
    "西安": (34.3416, 108.9398),
    "厦门": (24.4798, 118.0894),
    "青岛": (36.0671, 120.3826),
    "大连": (38.9140, 121.6147),
    "昆明": (25.0389, 102.7183),
    "拉萨": (29.6500, 91.1000),
    "丽江": (26.8721, 100.2299),
    "三亚": (18.2528, 109.5120),
    "香港": (22.3193, 114.1694),
    "台北": (25.0330, 121.5654),
}

# 杭州日落摄影佳位
HANGZHOU_SPOTS = [
    ("西湖断桥", "经典机位，日落方向正对宝石山"),
    ("宝石山蛤蟆峰", "俯拍西湖全景+保俶塔，需提前1h爬"),
    ("龙井茶园", "茶山+晚霞，层次感强，春秋季最佳"),
    ("钱塘江边", "开阔江面倒影"),
    ("小河直街", "运河+老街+晚霞，蓝调时刻最佳"),
    ("馒头山", "老杭州生活气息"),
    ("良渚古城", "广阔田野天际线低"),
    ("白塔公园", "铁轨+樱花（春）+晚霞"),
]

TZ_CST = timezone(timedelta(hours=8), "Asia/Shanghai")


# ── 工具函数 ─────────────────────────────────────────────────

def _http_get(url, headers=None):
    """通用 HTTP GET"""
    req = urllib.request.Request(url, headers=headers or {"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"_error": str(e)}


def _hour_index_for_date(hourly_times, target_date, sunset_hour=18):
    """
    找到 target_date 当天 sunset_hour 点在 hourly 数组中的索引。
    如果 sunset_hour 不在，找最接近的下午时段（16-19 点）。
    """
    target_prefix = target_date + "T"
    candidates = []
    for i, t in enumerate(hourly_times):
        if t.startswith(target_prefix):
            h = int(t.split("T")[1].split(":")[0])
            if 16 <= h <= 19:
                candidates.append((abs(h - sunset_hour), i, h))
    if candidates:
        candidates.sort()
        return candidates[0][1]  # 最接近日落的小时索引
    return None


# ── 引擎 1：Sunsethue API ──────────────────────────────────

def predict_sunsethue(lat, lng, date_str, event_type="sunset"):
    """调用 Sunsethue API 获取日落质量预测"""
    api_key = os.environ.get("SUNSETHUE_API_KEY", "")
    if not api_key:
        return None

    params = urllib.parse.urlencode({
        "latitude": lat, "longitude": lng,
        "date": date_str, "type": event_type,
    })
    url = f"https://api.sunsethue.com/event?{params}&key={api_key}"
    data = _http_get(url)
    if "_error" in data:
        return {"error": data["_error"], "source": "sunsethue"}
    return data


# ── 引擎 2：Open-Meteo 免费 API ───────────────────────────

def fetch_openmeteo(lat, lng):
    """从 Open-Meteo 获取天气数据（免费，无 key）"""
    # 同时获取 daily（日落时间+降水）+ hourly（分层云量+湿度）
    params = urllib.parse.urlencode({
        "latitude": lat, "longitude": lng,
        "daily": "sunrise,sunset,precipitation_probability_mean",
        "hourly": "cloud_cover_low,cloud_cover_mid,cloud_cover_high,"
                  "cloud_cover,visibility,"
                  "relative_humidity_2m,precipitation_probability",
        "timezone": "Asia/Shanghai",
        "forecast_days": 3,
    })
    url = f"https://api.open-meteo.com/v1/forecast?{params}"
    return _http_get(url)


def compute_sunset_quality(meteo_data, day_index=0, event_type="sunset"):
    """
    🔬 研究驱动型晚霞评分引擎 v2.0

    基于以下研究结论：
    1. AOD(气溶胶光学厚度) = 最重要的单一特征（Henriksson 2019, Chen 2022）
       → 无AOD数据时用能见度+湿度作代理
    2. 高云（卷云/卷积云 5-13km）是晚霞最佳散射介质，非低云
    3. 总云量 15-70% 为最优区间，非30-60%
    4. 云型配置 > 单层云量，多层云=纹理加分
    5. 湿度40-60%为最佳，>80%产生雾霾使颜色发灰
    """
    daily = meteo_data.get("daily", {})
    hourly = meteo_data.get("hourly", {})
    if not daily or not hourly:
        return None

    time_key = "sunset" if event_type == "sunset" else "sunrise"
    event_time_str = daily.get(time_key, [""] * 3)[day_index] or ""
    date_str = daily.get("time", [""] * 3)[day_index] or ""

    event_hour = 18
    if event_time_str and "T" in event_time_str:
        try:
            event_hour = int(event_time_str.split("T")[1].split(":")[0])
        except (ValueError, IndexError):
            pass

    rain_prob = daily.get("precipitation_probability_mean", [0] * 3)[day_index] or 0
    hourly_times = hourly.get("time", [])
    idx = _hour_index_for_date(hourly_times, date_str, event_hour)

    if idx is None:
        return {"error": f"找不到 {date_str} 日落时段的小时数据"}

    # 取日落前后 3h 窗口
    start_idx = max(0, idx - 1)
    end_idx = min(len(hourly_times), idx + 3)

    def safe_avg(key):
        vals = [v for v in hourly.get(key, [])[start_idx:end_idx] if v is not None]
        return sum(vals) / len(vals) if vals else None

    low_cloud = safe_avg("cloud_cover_low")
    mid_cloud = safe_avg("cloud_cover_mid")
    high_cloud = safe_avg("cloud_cover_high")
    total_cloud = safe_avg("cloud_cover")
    humidity = safe_avg("relative_humidity_2m")
    visibility = safe_avg("visibility")
    vis_km = visibility / 1000 if visibility else None

    # ════════════════════════════════════════════
    # ⭐ v2.0 多因子评分模型
    # ════════════════════════════════════════════

    score = 0.0
    factors = {}  # 各因子明细，用于调试

    def _v(val, fallback=0):
        """安全取值：0 是有效值，None 才是缺失"""
        return val if val is not None else fallback

    # ── 1. 云型配置评分 (权重 ~35%) ──
    # 决定性因素：高云 > 低云，多层 > 单层
    high_is_dominant = _v(high_cloud) >= 30 and _v(low_cloud) < 40
    low_is_dominant = _v(low_cloud) >= 20 and _v(low_cloud) <= 55 and _v(high_cloud) < 40
    multi_layer = _v(high_cloud) > 15 and _v(low_cloud) > 10
    overcast = _v(total_cloud) > 80
    clear_sky = _v(total_cloud) < 10

    if high_is_dominant and not overcast:
        # 🔥 高云晚霞——最佳！卷云/卷积云散射红光最强
        score += 0.40
        factors["cloud_type"] = "high_cloud_dominant"
        factors["cloud_type_score"] = 0.40
    elif low_is_dominant and not overcast:
        # 低云晚霞——也不错，但需要30-55%
        score += 0.28
        factors["cloud_type"] = "low_cloud_dominant"
        factors["cloud_type_score"] = 0.28
    elif _v(total_cloud) >= 10 and _v(total_cloud) <= 75:
        # 混合云——适中
        score += 0.22
        factors["cloud_type"] = "mixed"
        factors["cloud_type_score"] = 0.22
    elif clear_sky:
        # 晴空——无云散射，色彩平淡
        score += 0.05
        factors["cloud_type"] = "clear"
        factors["cloud_type_score"] = 0.05
    elif overcast:
        # 阴天——光线被完全遮挡
        score -= 0.10
        factors["cloud_type"] = "overcast"
        factors["cloud_type_score"] = -0.10

    # 多层云加分（纹理丰富更出片）
    if multi_layer:
        score += 0.08
        factors["multi_layer_bonus"] = 0.08
    elif factors.get("cloud_type") == "high_cloud_dominant" and _v(high_cloud) > 40:
        # 高云单层也有丰富纹理（卷云/卷积云本身纹理漂亮）
        score += 0.04
        factors["high_cloud_texture"] = 0.04

    # ── 2. 能见度评分 (权重 ~25%，AOD代理) ──
    # 能见度 >20km = 通透，12-20km = 良好，<8km = 雾霾
    # （中国城市平均能见度5-10km，15km+已接近通透）
    if vis_km is None:
        factors["visibility_score"] = 0
    elif vis_km >= 20:
        score += 0.18
        factors["visibility_score"] = 0.18
    elif vis_km >= 12:
        score += 0.12
        factors["visibility_score"] = 0.12
    elif vis_km >= 6:
        score += 0.05
        factors["visibility_score"] = 0.05
    else:
        score -= 0.08  # 能见度极差 = 严重雾霾
        factors["visibility_score"] = -0.08

    # ── 3. 湿度评分 (权重 ~15%) ──
    # 40-60% 最佳；>80% 雾蒙蒙；<30% 太干
    if humidity is None:
        factors["humidity_score"] = 0
    elif 40 <= humidity <= 60:
        score += 0.15
        factors["humidity_score"] = 0.15
        factors["humidity_note"] = "optimal"
    elif 30 <= humidity < 40 or 60 < humidity <= 75:
        score += 0.08
        factors["humidity_score"] = 0.08
        factors["humidity_note"] = "good"
    elif humidity > 85:
        score -= 0.10
        factors["humidity_score"] = -0.10
        factors["humidity_note"] = "too_wet"
    else:  # 75-85
        score += 0.04
        factors["humidity_score"] = 0.04
        factors["humidity_note"] = "ok"

    # ── 4. 降水惩罚 (权重 ~10%) ──
    if rain_prob > 50:
        score -= 0.15
        factors["rain_penalty"] = -0.15
    elif rain_prob > 25:
        score -= 0.08
        factors["rain_penalty"] = -0.08
    else:
        factors["rain_penalty"] = 0

    # ── 5. 总云量修正 (权重 ~15%) ──
    # 超过总云量最优区间后的额外扣分
    tc = _v(total_cloud, 50)
    if tc > 75:
        penalty = -0.08 * ((tc - 75) / 25)  # 75%→-0, 100%→-0.08
        score += penalty
        factors["total_cloud_penalty"] = round(penalty, 3)
    elif tc < 10:
        factors["total_cloud_penalty"] = 0
    else:
        # 15-60% 最优区间
        if 15 <= tc <= 60:
            score += 0.05
            factors["total_cloud_bonus"] = 0.05
        factors["total_cloud_penalty"] = 0

    # ── Clamp ──
    score = max(0.0, min(1.0, round(score, 2)))

    # ── 置信度评估 ──
    # 数据越完整 = 置信度越高
    data_points = sum(1 for v in [low_cloud, mid_cloud, high_cloud, total_cloud, humidity, visibility] if v is not None)
    confidence = min(1.0, data_points / 6 + 0.1)

    sunset_time = daily.get("sunset", [""] * 3)[day_index] or ""
    sunrise_time = daily.get("sunrise", [""] * 3)[day_index] or ""

    return {
        "quality": score,
        "source": "open-meteo",
        "confidence": round(confidence, 2),
        "cloud_cover_low": round(low_cloud, 0) if low_cloud else None,
        "cloud_cover_mid": round(mid_cloud, 0) if mid_cloud else None,
        "cloud_cover_high": round(high_cloud, 0) if high_cloud else None,
        "total_cloud_cover": round(total_cloud, 0) if total_cloud else None,
        "visibility_km": round(vis_km, 1) if vis_km else None,
        "rain_probability": round(rain_prob, 0),
        "humidity": round(humidity, 0) if humidity else None,
        "sunset_time": sunset_time,
        "sunrise_time": sunrise_time,
        "factors": factors,
    }


# ── 位置解析 ────────────────────────────────────────────────

def resolve_location(location=None, lat=None, lng=None):
    """级联位置解析：手动坐标 > 城市名 > 环境变量 > 默认杭州"""
    if lat is not None and lng is not None:
        return float(lat), float(lng), f"({lat},{lng})"

    if location:
        loc = LOCATION_MAP.get(location)
        if loc:
            return loc[0], loc[1], location

    env_loc = os.environ.get("SUNSET_LOCATION", "")
    if env_loc:
        loc = LOCATION_MAP.get(env_loc)
        if loc:
            return loc[0], loc[1], env_loc

    return 30.2741, 120.1551, "杭州"


# ── 格式化输出 ──────────────────────────────────────────────

def quality_emoji(score):
    if score >= 0.75: return "🔥"
    if score >= 0.50: return "🌤️"
    if score >= 0.25: return "🌥️"
    return "☁️"


def quality_label(score):
    if score >= 0.75: return "绝佳！火烧云级别 🔥"
    if score >= 0.65: return "不错，值得出工 🌤️"
    if score >= 0.50: return "还行，可拍可不拍 🌤️"
    if score >= 0.35: return "一般，大概率不出彩 🌥️"
    if score >= 0.20: return "偏弱，别抱期望 ☁️"
    return "很差，改天吧 ☁️"


def _utc_to_cst(utc_iso):
    """将 UTC ISO 时间转为 CST HH:MM，带容错"""
    if not utc_iso or "T" not in utc_iso:
        return utc_iso
    try:
        raw = utc_iso.replace("Z", "+00:00")
        dt = datetime.fromisoformat(raw)
        return dt.astimezone(TZ_CST).strftime("%H:%M")
    except Exception:
        return utc_iso[:16]


def _sunset_cst(sunset_iso):
    """从 ISO 时间提取 HH:MM"""
    if not sunset_iso or "T" not in sunset_iso:
        return ""
    return sunset_iso.split("T")[1][:5]


def _est_golden_hour(sunset_time):
    """估计黄金时段（日落前后各 30min）"""
    if not sunset_time:
        return "", ""
    try:
        parts = sunset_time.split(":")
        total_min = int(parts[0]) * 60 + int(parts[1])
        start = f"{((total_min - 30)//60):02d}:{((total_min - 30)%60):02d}"
        end = sunset_time[:5]
        bh_start = f"{((total_min + 10)//60):02d}:{((total_min + 10)%60):02d}"
        bh_end = f"{((total_min + 25)//60):02d}:{((total_min + 25)%60):02d}"
        return f"{start} — {end}", f"{bh_start} — {bh_end}"
    except (ValueError, IndexError):
        return "", ""


def format_discord_message(result, location_name, date_str, event_type):
    """生成 Discord 格式消息"""
    quality = result.get("quality", 0)
    emoji = quality_emoji(quality)
    label = quality_label(quality)
    source = result.get("source", "open-meteo")

    event_label = "晚霞" if event_type == "sunset" else "朝霞"
    icon = "🌅" if event_type == "sunset" else "🌄"

    lines = [
        f"{icon} **{location_name} {event_label}预报** · {date_str}",
        "━" * 30,
        f"{emoji} **评分：{quality:.0%}** — {label}",
    ]

    # 来源
    src_tag = "Sunsethue" if source == "sunsethue" else "Open-Meteo+云量算法"
    lines.append(f"📡 来源：{src_tag}")

    # Sunsethue 独有字段
    if source == "sunsethue":
        cloud = result.get("cloud_cover")
        if cloud is not None:
            lines.append(f"☁️ 云量：{cloud*100:.0f}%")
        if "direction" in result:
            lines.append(f"🧭 日落方向：{result['direction']:.0f}°")

        magics = result.get("magics", {})
        if magics.get("golden_hour"):
            gh = magics["golden_hour"]
            gh_start = _utc_to_cst(gh[0])
            gh_end = _utc_to_cst(gh[1])
            lines.append(f"⏰ 黄金时段：{gh_start} — {gh_end}")
        if magics.get("blue_hour"):
            bh = magics["blue_hour"]
            bh_start = _utc_to_cst(bh[0])
            bh_end = _utc_to_cst(bh[1])
            lines.append(f"⏰ 蓝色时刻：{bh_start} — {bh_end}")
        sunset_t = result.get("sunset_time_local", "")
        if sunset_t:
            lines.insert(3, f"🌇 日落：{sunset_t}")
    else:
        # Open-Meteo 数据
        sunset_t = _sunset_cst(result.get("sunset_time", ""))
        if sunset_t and event_type == "sunset":
            lines.append(f"🌇 日落：{sunset_t}")

        low_c = result.get("cloud_cover_low")
        mid_c = result.get("cloud_cover_mid")
        high_c = result.get("cloud_cover_high")
        total_c = result.get("total_cloud_cover")
        vis = result.get("visibility_km")
        conf = result.get("confidence")

        # 云型描述
        factors = result.get("factors", {})
        cloud_type = factors.get("cloud_type", "")
        if cloud_type == "high_cloud_dominant":
            lines.append("☁️ 云型：高云主导（卷云/卷积云，散射效果最佳 🔥）")
        elif cloud_type == "low_cloud_dominant":
            lines.append("☁️ 云型：低云主导（层积云，效果良好）")
        elif cloud_type == "mixed":
            lines.append("☁️ 云型：混合云层")
        elif cloud_type == "clear":
            lines.append("☁️ 云型：晴空（无云散射，色彩平淡）")
        elif cloud_type == "overcast":
            lines.append("☁️ 云型：阴天（光线被遮挡）")

        # 云量详情
        parts = []
        if low_c is not None: parts.append(f"低{low_c:.0f}%")
        if mid_c is not None: parts.append(f"中{mid_c:.0f}%")
        if high_c is not None: parts.append(f"高{high_c:.0f}%")
        if total_c is not None: parts.append(f"总{total_c:.0f}%")
        if parts:
            lines.append(f"☁️ 云量：{' · '.join(parts)}")

        # 能见度
        if vis is not None:
            lines.append(f"👁️ 能见度：{vis:.1f}km{' ✅通透' if vis >= 20 else ' ✅良好' if vis >= 12 else ' ⚠️一般' if vis >= 6 else ' ❌雾霾'}")

        # 湿度
        hu = result.get("humidity")
        if hu is not None:
            note = factors.get("humidity_note", "")
            icon = "💧" if note == "optimal" else "💧"
            lines.append(f"{icon} 湿度：{hu:.0f}%{' ✅最佳' if note=='optimal' else ' 👍良好' if note=='good' else ' ⚠️偏湿' if note=='too_wet' else ''}")

        # 降水
        rp = result.get("rain_probability", 0)
        if rp > 0:
            lines.append(f"🌧️ 降水概率：{rp:.0f}%")

        # 置信度
        if conf is not None:
            conf_stars = "🟢高" if conf >= 0.85 else "🟡中" if conf >= 0.65 else "🔴低"
            lines.append(f"🎯 置信度：{conf:.0%}（{conf_stars}）")

        gold, blue = _est_golden_hour(sunset_t or "18:40")
        if gold:
            lines.append(f"⏰ 黄金时段（估）：{gold}")
        if blue:
            lines.append(f"⏰ 蓝色时刻（估）：{blue}")

    # 拍摄建议
    lines.append("")
    lines.append("📸 **拍摄建议：**")
    if quality >= 0.75:
        lines.append("• 🔥 今晚必出！提前 1h 到场地踩光")
        lines.append("• 穿暖色系（橙/红/黄）更融晚霞")
        lines.append("• 带反光板/补光灯补面光")
        lines.append("• 三脚架必备（蓝调时刻光线暗）")
    elif quality >= 0.50:
        lines.append("• 值得出工，提前 30min 到")
        lines.append("• 日落方向找开阔地")
        lines.append("• 建议带反光板")
    else:
        lines.append("• 建议改天，或拍室内/夜景")
        lines.append("• 如果去了，调色上多拉饱和度+暖色调")

    # 杭州推荐点位
    if location_name == "杭州" and quality >= 0.25:
        lines.append("")
        lines.append("📍 **推荐机位（杭州）：**")
        limit = 3 if quality < 0.50 else 5
        for spot, desc in HANGZHOU_SPOTS[:limit]:
            lines.append(f"• {spot} — {desc}")

    lines.append("")
    lines.append(f"🕐 预报更新：{datetime.now(TZ_CST).strftime('%H:%M')}")

    return "\n".join(lines)


# ── 主流程 ──────────────────────────────────────────────────

def run_prediction(location=None, lat=None, lng=None,
                   date_str=None, event_type="sunset"):
    """
    执行日落/日出质量预测。
    返回 dict { quality, source, discord_message, short_summary, ... }
    """
    resolved_lat, resolved_lng, location_name = resolve_location(location, lat, lng)

    if not date_str:
        date_str = datetime.now(TZ_CST).strftime("%Y-%m-%d")

    today_str = datetime.now(TZ_CST).strftime("%Y-%m-%d")
    day_index = 0 if date_str == today_str else 1

    # ── 引擎 1：尝试 Sunsethue ──
    result = predict_sunsethue(resolved_lat, resolved_lng, date_str, event_type)
    if result and "error" not in result:
        data = result.get("data", {})
        raw = {
            "quality": data.get("quality", 0.5),
            "cloud_cover": data.get("cloud_cover"),
            "direction": data.get("direction"),
            "magics": data.get("magics", {}),
            "source": "sunsethue",
        }
        # 补全日落时间
        sunset_t_raw = data.get("time", "")
        if sunset_t_raw:
            try:
                dt = datetime.fromisoformat(sunset_t_raw.replace("Z", "+00:00"))
                raw["sunset_time_local"] = dt.astimezone(TZ_CST).strftime("%H:%M")
            except Exception:
                pass
    else:
        # ── 引擎 2：Open-Meteo 兜底 ──
        meteo = fetch_openmeteo(resolved_lat, resolved_lng)
        if "_error" in meteo:
            return {"error": f"Open-Meteo 请求失败: {meteo['_error']}", "source": "failed"}

        raw = compute_sunset_quality(meteo, day_index=day_index, event_type=event_type)
        if raw is None or "error" in (raw or {}):
            return {"error": f"云量解析失败: {raw}", "source": "failed"}

    discord_msg = format_discord_message(raw, location_name, date_str, event_type)
    short_summary = f"{quality_emoji(raw['quality'])} {location_name} {date_str}: {raw['quality']:.0%}"

    return {
        "quality": raw["quality"],
        "source": raw["source"],
        "location": location_name,
        "coordinates": (resolved_lat, resolved_lng),
        "date": date_str,
        "event_type": event_type,
        "short_summary": short_summary,
        "discord_message": discord_msg,
    }


# ── CLI 入口 ────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="🌅 晚霞/朝霞预测")
    parser.add_argument("--location", type=str, default=None)
    parser.add_argument("--lat", type=float, default=None)
    parser.add_argument("--lng", type=float, default=None)
    parser.add_argument("--date", type=str, default=None)
    parser.add_argument("--type", dest="event_type", type=str,
                        default="sunset", choices=["sunset", "sunrise"])
    parser.add_argument("--discord", action="store_true")
    parser.add_argument("--short", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    result = run_prediction(
        location=args.location, lat=args.lat, lng=args.lng,
        date_str=args.date, event_type=args.event_type,
    )

    if "error" in result:
        print(f"❌ {result['error']}")
        sys.exit(1)

    if args.short:
        print(result["short_summary"])
    elif args.json:
        print(json.dumps({
            "quality": result["quality"],
            "source": result["source"],
            "location": result["location"],
            "date": result["date"],
            "short": result["short_summary"],
        }, ensure_ascii=False, indent=2))
    else:
        # --discord or plain
        print(result["discord_message"])


if __name__ == "__main__":
    main()
