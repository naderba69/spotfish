import os
import json
import math
import requests
import streamlit as st
import folium
import pandas as pd

from streamlit_folium import st_folium
from datetime import datetime, timedelta, date
from concurrent.futures import ThreadPoolExecutor, as_completed
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
APP_TITLE = "🎣 مستشار الصيد الفيزيائي | تونس"
TUNIS_TZ = ZoneInfo("Africa/Tunis")
USER_AGENT = "TunisiaFishingAdvisor/10.4"
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

st.set_page_config(
    page_title="Fishing Advisor Tunisia",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
body{direction:rtl}
.block-container{padding-top:0.8rem}
.go-box{background:#0a3d0a;padding:18px;border-radius:10px;border:2px solid #00ff00}
.warn-box{background:#3d2e0a;padding:18px;border-radius:10px;border:2px solid #ffa500}
.nogo-box{background:#3d0a0a;padding:18px;border-radius:10px;border:2px solid #ff0000}
.spot-card{background:#0a1a2e;padding:14px;border-radius:8px;border:1px solid #1f77b4;margin-bottom:8px}
.top-spot{background:#121826;padding:14px;border-radius:8px;border:1px solid #3b82f6;margin-bottom:8px}
.metric-card{background:#111827;padding:12px;border-radius:8px;border-right:4px solid #3b82f6}
.small-note{font-size:0.9rem;opacity:.9}
.anchor-box{position:relative}
.anchor-overlay{
  position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
  z-index:999; pointer-events:none; font-size:54px;
  text-shadow:0 0 8px rgba(255,0,0,.9)
}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# SESSION
# ══════════════════════════════════════════════════════════════
DEFAULTS = {
    "lat": 36.8333,
    "lon": 11.1000,
    "map_center": [36.8333, 11.1000],
    "day_offset": 1,
    "scan_results": None,
    "deep_result": None,
}
for k, v in DEFAULTS.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════
# TUNISIA COASTAL SPOTS (seed list)
# عدّلها كما تريد. هذه نقاط انطلاق للاستكشاف، وليست "إحداثيات سرية"
# ══════════════════════════════════════════════════════════════
SPOTS = [
    {"name": "رأس أنجلة", "lat": 37.3470, "lon": 9.7440, "region": "بنزرت"},
    {"name": "بنزرت المرسى", "lat": 37.2744, "lon": 9.8628, "region": "بنزرت"},
    {"name": "رأس الدرك", "lat": 37.2742, "lon": 9.8739, "region": "بنزرت"},
    {"name": "غار الملح", "lat": 37.1728, "lon": 10.0872, "region": "بنزرت"},
    {"name": "رفراف", "lat": 37.1889, "lon": 10.1833, "region": "بنزرت"},
    {"name": "سيدي علي المكي", "lat": 37.1470, "lon": 10.2500, "region": "بنزرت"},
    {"name": "المرسى", "lat": 36.8780, "lon": 10.3300, "region": "تونس"},
    {"name": "قمرت", "lat": 36.9200, "lon": 10.2900, "region": "تونس"},
    {"name": "سليمان الشاطئ", "lat": 36.7060, "lon": 10.4920, "region": "نابل"},
    {"name": "الحمامات الشمالية", "lat": 36.4300, "lon": 10.7000, "region": "نابل"},
    {"name": "الحمامات الجنوبية", "lat": 36.3600, "lon": 10.5400, "region": "نابل"},
    {"name": "نابل الشاطئ", "lat": 36.4561, "lon": 10.7376, "region": "نابل"},
    {"name": "قربة", "lat": 36.5780, "lon": 10.8580, "region": "نابل"},
    {"name": "منزل تميم", "lat": 36.7810, "lon": 10.9950, "region": "نابل"},
    {"name": "قليبية", "lat": 36.8333, "lon": 11.1000, "region": "نابل"},
    {"name": "الهوارية", "lat": 37.0539, "lon": 11.0581, "region": "نابل"},
    {"name": "هرقلة", "lat": 36.0330, "lon": 10.5100, "region": "سوسة"},
    {"name": "شط مريم", "lat": 35.9300, "lon": 10.5600, "region": "سوسة"},
    {"name": "سوسة بوجعفر", "lat": 35.8256, "lon": 10.6369, "region": "سوسة"},
    {"name": "المنستير الشاطئ", "lat": 35.7672, "lon": 10.8111, "region": "المنستير"},
    {"name": "صيادة", "lat": 35.6680, "lon": 10.8900, "region": "المنستير"},
    {"name": "المهدية الكورنيش", "lat": 35.5047, "lon": 11.0622, "region": "المهدية"},
    {"name": "الشابة", "lat": 35.2370, "lon": 11.1150, "region": "المهدية"},
    {"name": "صفاقس رأس الطابية", "lat": 34.7333, "lon": 10.7633, "region": "صفاقس"},
    {"name": "قرقنة", "lat": 34.7333, "lon": 11.1167, "region": "صفاقس"},
    {"name": "قابس الشاطئ", "lat": 33.8815, "lon": 10.0982, "region": "قابس"},
    {"name": "بوغرارة", "lat": 33.6500, "lon": 10.7500, "region": "مدنين"},
    {"name": "جربة أجيم", "lat": 33.7167, "lon": 10.7667, "region": "جربة"},
    {"name": "أغير", "lat": 33.7700, "lon": 11.0300, "region": "جربة"},
    {"name": "جرجيس", "lat": 33.5042, "lon": 10.8681, "region": "مدنين"},
]

# ══════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════
def now_tunisia():
    return datetime.now(TUNIS_TZ)

def target_date_from_offset(offset: int) -> date:
    return (now_tunisia().date() + timedelta(days=offset))

def safe_avg(lst):
    return sum(lst) / len(lst) if lst else 0.0

def angle_diff_180(a, b):
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d

def circular_mean(angles_deg):
    if not angles_deg:
        return 0.0
    s = sum(math.sin(math.radians(a)) for a in angles_deg) / len(angles_deg)
    c = sum(math.cos(math.radians(a)) for a in angles_deg) / len(angles_deg)
    return math.degrees(math.atan2(s, c)) % 360

def moon_phase_factor(d: date) -> float:
    delta = (d - date(2024, 1, 11)).days % 29.53
    return round(0.5 + 0.5 * abs(math.cos(2 * math.pi * delta / 29.53)), 3)

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2 +
        math.cos(math.radians(lat1)) *
        math.cos(math.radians(lat2)) *
        math.sin(dlon / 2) ** 2
    )
    return round(2 * R * math.asin(math.sqrt(a)), 1)

def destination_point(lat1, lon1, bearing_deg, distance_km):
    R = 6371.0
    b = math.radians(bearing_deg)
    φ1 = math.radians(lat1)
    λ1 = math.radians(lon1)
    φ2 = math.asin(
        math.sin(φ1) * math.cos(distance_km / R) +
        math.cos(φ1) * math.sin(distance_km / R) * math.cos(b)
    )
    λ2 = λ1 + math.atan2(
        math.sin(b) * math.sin(distance_km / R) * math.cos(φ1),
        math.cos(distance_km / R) - math.sin(φ1) * math.sin(φ2)
    )
    return math.degrees(φ2), math.degrees(λ2)

def fmt_date_ar(d: date):
    names = {
        0: "الاثنين", 1: "الثلاثاء", 2: "الأربعاء", 3: "الخميس",
        4: "الجمعة", 5: "السبت", 6: "الأحد"
    }
    months = {
        1: "جانفي", 2: "فيفري", 3: "مارس", 4: "أفريل", 5: "ماي", 6: "جوان",
        7: "جويلية", 8: "أوت", 9: "سبتمبر", 10: "أكتوبر", 11: "نوفمبر", 12: "ديسمبر"
    }
    return f"{names[d.weekday()]} {d.day} {months[d.month]} {d.year}"

def get_json(url, params, timeout=20):
    r = requests.get(
        url,
        params=params,
        timeout=timeout,
        headers={"User-Agent": USER_AGENT}
    )
    r.raise_for_status()
    return r.json()

def build_lookup(data):
    if not data or "hourly" not in data:
        return {}
    return {t: i for i, t in enumerate(data["hourly"].get("time", []))}

def gv(data, lookup, key, ts, default=0.0):
    if not data or not lookup:
        return default
    idx = lookup.get(ts)
    if idx is None:
        return default
    arr = data["hourly"].get(key, [])
    if idx < len(arr) and arr[idx] is not None:
        try:
            return float(arr[idx])
        except:
            return default
    return default

def parse_iso_dt(ts):
    # Open-Meteo مع timezone=auto يرجع وقت محلي ISO بدون offset غالباً
    return datetime.fromisoformat(ts)

# ══════════════════════════════════════════════════════════════
# API
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def analyze_coast_geometry(lat, lon):
    radius_km = 3.0
    points = []
    for bearing in range(0, 360, 30):
        lat2, lon2 = destination_point(lat, lon, bearing, radius_km)
        points.append({"lat": round(lat2, 4), "lon": round(lon2, 4), "bearing": bearing})

    lats_str = ",".join(str(p["lat"]) for p in points)
    lons_str = ",".join(str(p["lon"]) for p in points)

    try:
        data = get_json(
            "https://api.open-meteo.com/v1/elevation",
            {"latitude": lats_str, "longitude": lons_str},
            timeout=15
        )
        elevations = data.get("elevation", [])
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            return None, "rate_limit"
        return None, f"elevation_http:{e}"
    except Exception as e:
        return None, f"elevation_error:{e}"

    if len(elevations) != len(points):
        return None, "elevation_incomplete"

    sea_b = [p["bearing"] for p, e in zip(points, elevations) if e is not None and e <= 0.5]
    if not sea_b:
        return None, "inland"

    sn = circular_mean(sea_b)
    exposure = round(len(sea_b) / len(points), 3)

    if len(sea_b) >= 2:
        avg_s = sum(math.sin(math.radians(b)) for b in sea_b) / len(sea_b)
        avg_c = sum(math.cos(math.radians(b)) for b in sea_b) / len(sea_b)
        R_bar = min(math.sqrt(avg_s**2 + avg_c**2), 0.9999)
        bay_factor = round(max(0.0, 1.0 - math.degrees(math.sqrt(-2.0 * math.log(R_bar))) / 90.0), 3)
    else:
        bay_factor = 0.5

    if exposure < 0.05:
        coast_type = "بحيرة/سبخة"
    elif exposure > 0.65:
        coast_type = "ساحل مفتوح"
    elif bay_factor > 0.55:
        coast_type = "خليج شبه مغلق"
    else:
        coast_type = "ساحل عادي"

    return {
        "shoreline_normal": round(sn, 1),     # من الشاطئ نحو البحر
        "coast_exposure": exposure,
        "bay_factor": bay_factor,
        "coast_type": coast_type,
    }, None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_weather(lat, lon):
    try:
        data = get_json(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,visibility",
                "past_days": 2,
                "forecast_days": 3,
                "timezone": "auto",
                "cell_selection": "sea"
            },
            timeout=20
        )
        if "hourly" not in data:
            return None, "weather_missing_hourly"
        return data, None
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            return None, "rate_limit"
        return None, f"weather_http:{e}"
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_marine(lat, lon):
    try:
        data = get_json(
            "https://marine-api.open-meteo.com/v1/marine",
            {
                "latitude": lat,
                "longitude": lon,
                "hourly": (
                    "wave_height,wave_direction,wave_period,"
                    "wind_wave_height,wind_wave_direction,wind_wave_period,"
                    "swell_wave_height,swell_wave_direction,swell_wave_period,"
                    "sea_surface_temperature"
                ),
                "past_days": 2,
                "forecast_days": 3,
                "timezone": "auto"
            },
            timeout=20
        )
        if "hourly" not in data:
            return None, "marine_missing_hourly"
        return data, None
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            return None, "rate_limit"
        return None, f"marine_http:{e}"
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_location_name(lat, lon):
    try:
        data = get_json(
            "https://nominatim.openstreetmap.org/reverse",
            {
                "lat": lat,
                "lon": lon,
                "format": "json",
                "accept-language": "ar",
                "zoom": 14
            },
            timeout=8
        )
        a = data.get("address", {})
        return (
            a.get("beach") or a.get("hamlet") or a.get("village") or a.get("suburb") or
            a.get("town") or a.get("city") or a.get("state") or "ساحل تونسي"
        )
    except:
        return "ساحل تونسي"

# ══════════════════════════════════════════════════════════════
# CORE PHYSICS
# ══════════════════════════════════════════════════════════════
def classify_wind(wind_dir_from, sn, ws_eff):
    """
    sn = اتجاه البحر من الشاطئ نحو الخارج
    إذا wind_dir_from ≈ sn => الريح قادمة من البحر => وش
    إذا wind_dir_from ≈ sn+180 => قادمة من البر => بر
    """
    diff = angle_diff_180(wind_dir_from, sn)

    if diff <= 45:
        label = "وش 🟢"
        bonus = +1.5 if 10 <= ws_eff <= 25 else (+0.5 if ws_eff < 10 else -0.5)
    elif diff >= 135:
        label = "بر 🔵"
        bonus = +1.0 if ws_eff <= 15 else (+0.2 if ws_eff <= 25 else -1.2)
    elif diff <= 90:
        label = "جانبي-وش 🟡"
        bonus = -0.5 if ws_eff <= 20 else -1.5
    else:
        label = "جانبي-بر 🟠"
        bonus = -0.8 if ws_eff <= 20 else -2.0

    return label, round(diff, 1), round(bonus, 2)

def analyze_past_48h(marine_data, weather_data, target_date):
    time_array = weather_data["hourly"].get("time", [])
    if not time_array:
        return {
            "avg_wwh": 0.0, "avg_wwp": 0.0,
            "avg_swh": 0.0, "avg_swp": 0.0,
            "is_dirty": False
        }

    target_start = datetime.combine(target_date, datetime.min.time())
    past_start = target_start - timedelta(hours=48)
    lookup = build_lookup(marine_data)

    p_wwh, p_wwp, p_swh, p_swp = [], [], [], []

    for i, ts in enumerate(time_array):
        dt = parse_iso_dt(ts)
        if not (past_start <= dt < target_start):
            continue

        wwh = gv(marine_data, lookup, "wind_wave_height", ts)
        wwp = gv(marine_data, lookup, "wind_wave_period", ts)
        swh = gv(marine_data, lookup, "swell_wave_height", ts)
        swp = gv(marine_data, lookup, "swell_wave_period", ts)

        if wwh > 0.05:
            p_wwh.append(wwh)
        if wwp > 0.05:
            p_wwp.append(wwp)
        if swh > 0.05:
            p_swh.append(swh)
        if swp > 0.05:
            p_swp.append(swp)

    avg_wwh = safe_avg(p_wwh)
    avg_wwp = safe_avg(p_wwp)
    avg_swh = safe_avg(p_swh)
    avg_swp = safe_avg(p_swp)

    is_dirty = (avg_wwh > 1.2) and (avg_wwp < 6.5)

    return {
        "avg_wwh": round(avg_wwh, 2),
        "avg_wwp": round(avg_wwp, 1),
        "avg_swh": round(avg_swh, 2),
        "avg_swp": round(avg_swp, 1),
        "is_dirty": is_dirty
    }

def compute_hourly_analysis(marine_data, weather_data, coast_info, target_date, past):
    sn = coast_info["shoreline_normal"]
    bay = coast_info["bay_factor"]
    exposure = coast_info["coast_exposure"]

    lookup = build_lookup(marine_data)
    times = weather_data["hourly"].get("time", [])
    if not times:
        return None, "no_times"

    wind_spd = weather_data["hourly"].get("wind_speed_10m", [])
    wind_dir = weather_data["hourly"].get("wind_direction_10m", [])
    gusts = weather_data["hourly"].get("wind_gusts_10m", [])
    precip = weather_data["hourly"].get("precipitation", [])
    visibility = weather_data["hourly"].get("visibility", [])

    moon_bonus = max(0.0, (moon_phase_factor(target_date) - 0.55) * 1.2)

    rows = []
    red_flags = set()

    for i, ts in enumerate(times):
        dt = parse_iso_dt(ts)
        if dt.date() != target_date:
            continue

        def w(arr, default=0.0):
            if i < len(arr) and arr[i] is not None:
                try:
                    return float(arr[i])
                except:
                    return default
            return default

        ws = w(wind_spd)
        wd = w(wind_dir)
        gust = w(gusts)
        rain = w(precip)
        vis = w(visibility, 24140.0)
        if vis <= 0:
            vis = 24140.0

        # تأثير الهبّات دون قلب المنطق
        ws_eff = ws + 0.35 * max(0.0, gust - ws)

        wave_h = gv(marine_data, lookup, "wave_height", ts)
        wave_dir = gv(marine_data, lookup, "wave_direction", ts)
        wave_period = gv(marine_data, lookup, "wave_period", ts)

        ww_h = gv(marine_data, lookup, "wind_wave_height", ts)
        ww_dir = gv(marine_data, lookup, "wind_wave_direction", ts)
        ww_p = gv(marine_data, lookup, "wind_wave_period", ts)

        sw_h = gv(marine_data, lookup, "swell_wave_height", ts)
        sw_dir = gv(marine_data, lookup, "swell_wave_direction", ts)
        sw_p = gv(marine_data, lookup, "swell_wave_period", ts)

        sst = gv(marine_data, lookup, "sea_surface_temperature", ts, 18.0)

        # تصحيح الخليج
        ww_h_eff = ww_h * (1.0 - bay * 0.50)
        sw_h_eff = sw_h * (1.0 - bay * 0.30)
        wave_h_eff = wave_h * (1.0 - bay * 0.40)
        total_h = max(wave_h_eff, ww_h_eff + sw_h_eff)

        # الزوايا: الموج من أين يأتي
        wind_label, wind_shore_angle, wind_bonus = classify_wind(wd, sn, ws_eff)
        wave_impact = angle_diff_180(wave_dir, sn)
        ww_impact = angle_diff_180(ww_dir, sn)
        sw_impact = angle_diff_180(sw_dir, sn)

        # التيار الجانبي: فقط إذا الموج يدخل من البحر بزاوية واقعية
        if 10 < wave_impact <= 80 and total_h > 0.05:
            ir = math.radians(wave_impact)
            v_ls = 1.17 * math.sqrt(9.81 * total_h) * math.sin(ir) * math.cos(ir)
        else:
            v_ls = 0.0

        # نضيف مساهمة بسيطة للريح
        v_kmh = max(0.0, (v_ls + ws_eff * 0.015) * 3.6)

        # الجر والرصاص
        if v_kmh > 1.8:
            lead = "سبايك 140غ"
        elif v_kmh > 1.0:
            lead = "هرمي 120غ"
        else:
            lead = "زيتوني 100غ"

        is_cleaning_swell = (
            past["is_dirty"] and
            sw_p >= 8.0 and
            sw_h_eff >= 0.35 and
            sw_impact < 45
        )

        if is_cleaning_swell:
            debris = "Swell ينظف 🟢"
        elif past["is_dirty"]:
            debris = "مدرر / بقايا حشيش 🔴"
        else:
            debris = "نظيف 🟢"

        ecume = "نعم ✅" if ("وش" in wind_label and 0.4 <= total_h <= 1.5 and wave_impact < 55 and ws_eff >= 10) else "لا ❌"

        if total_h > 1.2 and wave_period > 8 and 20 <= wave_impact <= 60:
            rip = "عالي"
        elif total_h > 0.9 and wave_period > 6:
            rip = "متوسط"
        else:
            rip = "منخفض"

        score = 10.0 + wind_bonus + moon_bonus

        if total_h < 0.25:
            score -= 3.0
        elif total_h > 2.2:
            score -= 2.0

        if v_kmh > 2.2:
            score -= 3.5
            red_flags.add("تيار جانبي قوي")
        elif v_kmh > 1.2:
            score -= 1.5

        if ws_eff > 55:
            score -= 5.0
            red_flags.add("ريح عنيفة")
        elif ws_eff > 40:
            score -= 3.0
        elif ws_eff > 30:
            score -= 1.5

        if rain > 3:
            score -= 1.5
        elif rain > 1:
            score -= 0.5

        if vis < 1500:
            score -= 2.0
        elif vis < 3000:
            score -= 1.0

        if sst < 15:
            score -= 1.5
        elif 19 <= sst <= 24:
            score += 0.4

        if ecume == "نعم ✅":
            score += 1.2

        if is_cleaning_swell:
            score += 1.4
        elif past["is_dirty"]:
            score -= 2.0
            red_flags.add("بحر مدرر من إرث 48 ساعة")

        if exposure > 0.75 and total_h > 1.6:
            score -= 1.0

        score = max(0.0, min(10.0, score))

        rows.append({
            "time": ts,
            "hour": dt.hour,
            "score": round(score, 1),
            "wind_kmh": round(ws, 1),
            "gust_kmh": round(gust, 1),
            "ws_eff": round(ws_eff, 1),
            "wind_dir_from": round(wd, 0),
            "wind_type": wind_label,
            "wind_shore_angle": wind_shore_angle,
            "wave_h": round(wave_h_eff, 2),
            "wave_p": round(wave_period, 1),
            "wave_impact": round(wave_impact, 1),
            "ww_h": round(ww_h_eff, 2),
            "ww_p": round(ww_p, 1),
            "sw_h": round(sw_h_eff, 2),
            "sw_p": round(sw_p, 1),
            "sw_impact": round(sw_impact, 1),
            "longshore_kmh": round(v_kmh, 2),
            "lead": lead,
            "rip": rip,
            "debris": debris,
            "ecume": ecume,
            "sst_c": round(sst, 1),
            "rain_mm": round(rain, 1),
            "vis_km": round(vis / 1000, 1)
        })

    if not rows:
        return None, "no_target_rows"

    return rows, sorted(list(red_flags))

def weighted_score(rows):
    prime = set(range(4, 9)) | set(range(17, 24))
    tw = 0.0
    ts = 0.0
    for r in rows:
        w = 2.5 if r["hour"] in prime else 1.0
        tw += w
        ts += r["score"] * w
    return round(ts / tw, 2) if tw else 0.0

def summarize_analysis(rows, coast_info, past, red_flags, target_date):
    w_score = weighted_score(rows)
    simple = round(sum(r["score"] for r in rows) / len(rows), 2)
    best = max(rows, key=lambda x: x["score"])
    avg_ls = round(sum(r["longshore_kmh"] for r in rows) / len(rows), 2)
    avg_ws = round(sum(r["ws_eff"] for r in rows) / len(rows), 1)
    ecume_hours = sum(1 for r in rows if "نعم" in r["ecume"])
    confidence = max(35, 92 - 14 * len(red_flags))

    return {
        "weighted_score": w_score,
        "simple_score": simple,
        "best_hour": best,
        "avg_longshore": avg_ls,
        "avg_wind": avg_ws,
        "ecume_hours": ecume_hours,
        "confidence": confidence,
        "coast": coast_info,
        "past": past,
        "red_flags": red_flags,
        "rows": rows,
        "moon_factor": moon_phase_factor(target_date),
        "target_date": str(target_date),
    }

# ══════════════════════════════════════════════════════════════
# SCOUT
# ══════════════════════════════════════════════════════════════
def quick_score_spot(spot, target_date):
    lat, lon = spot["lat"], spot["lon"]

    coast, err = analyze_coast_geometry(lat, lon)
    if err or not coast:
        return None

    if coast["coast_type"] == "بحيرة/سبخة":
        return None

    marine, err1 = fetch_marine(lat, lon)
    weather, err2 = fetch_weather(lat, lon)
    if err1 or err2 or not marine or not weather:
        return None

    lookup = build_lookup(marine)
    times = weather["hourly"].get("time", [])
    if not times:
        return None

    scores = []
    sn = coast["shoreline_normal"]
    bay = coast["bay_factor"]

    for i, ts in enumerate(times):
        dt = parse_iso_dt(ts)
        if dt.date() != target_date:
            continue

        try:
            ws = float(weather["hourly"]["wind_speed_10m"][i] or 0)
        except:
            ws = 0.0
        try:
            gust = float(weather["hourly"]["wind_gusts_10m"][i] or 0)
        except:
            gust = 0.0
        try:
            wd = float(weather["hourly"]["wind_direction_10m"][i] or 0)
        except:
            wd = 0.0

        wave_h = gv(marine, lookup, "wave_height", ts) * (1.0 - bay * 0.40)
        wave_dir = gv(marine, lookup, "wave_direction", ts)
        sw_p = gv(marine, lookup, "swell_wave_period", ts)
        sst = gv(marine, lookup, "sea_surface_temperature", ts, 18.0)

        ws_eff = ws + 0.35 * max(0.0, gust - ws)
        diff_w = angle_diff_180(wd, sn)
        diff_wave = angle_diff_180(wave_dir, sn)

        s = 10.0
        if diff_w <= 45:
            s += 1.0
        elif diff_w >= 135:
            s += 0.4
        else:
            s -= 1.0

        if wave_h < 0.2:
            s -= 3.0
        elif wave_h > 2.0:
            s -= 1.8

        if 10 < diff_wave <= 80:
            s += 0.3
        elif diff_wave > 90:
            s -= 0.8

        if ws_eff > 45:
            s -= 4.0
        elif ws_eff > 35:
            s -= 2.0

        if sw_p >= 8:
            s += 0.4

        if sst < 15:
            s -= 1.3
        elif 19 <= sst <= 24:
            s += 0.3

        s = max(0.0, min(10.0, s))
        weight = 2.5 if dt.hour in (set(range(4, 9)) | set(range(17, 24))) else 1.0
        scores.append((s, weight))

    if not scores:
        return None

    total = sum(s * w for s, w in scores)
    total_w = sum(w for _, w in scores)
    return round(total / total_w, 2) if total_w else None

@st.cache_data(ttl=3600, show_spinner=False)
def scan_tunisia(target_date_str):
    target_date = date.fromisoformat(target_date_str)
    results = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(quick_score_spot, spot, target_date): spot for spot in SPOTS}
        for f in as_completed(futures):
            spot = futures[f]
            try:
                score = f.result()
                if score is not None:
                    results.append({
                        "name": spot["name"],
                        "region": spot["region"],
                        "lat": spot["lat"],
                        "lon": spot["lon"],
                        "score": score
                    })
            except:
                pass
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

# ══════════════════════════════════════════════════════════════
# REPORTS
# ══════════════════════════════════════════════════════════════
def build_deterministic_report(location_name, summary, alternatives, target_date):
    score = summary["weighted_score"]
    best = summary["best_hour"]
    past = summary["past"]
    conf = summary["confidence"]

    better = alternatives[0] if alternatives else None
    preferred_name = better["name"] if better and better["score"] > score else location_name
    compared_name = location_name if better and better["score"] > score else "البدائل الأضعف"

    # صياغة معادلة الزاوية
    if best["wave_impact"] <= 20:
        wave_phrase = "بزاوية مستقيمة تقريباً"
    elif best["wave_impact"] <= 55:
        wave_phrase = "بزاوية مائلة لكن مازالت قابلة للخدمة"
    else:
        wave_phrase = "بزاوية جانبية مزعجة"

    # تنظيف البحر
    if "ينظف" in best["debris"]:
        debris_phrase = "هناك Swell يخدم كمصفاة ويطرد الوسخ خارج خط الصيد"
    elif "مدرر" in best["debris"]:
        debris_phrase = "إرث الـ48 ساعة مازال يخلّي البحر وسخ ويشد الأعشاب في الخيط"
    else:
        debris_phrase = "البحر في المجمل نظيف وما فيهش فساد كبير"

    # النشاط
    if "نعم" in best["ecume"]:
        fish_phrase = "أحسن نقطة قوة هنا هي حزام الرغوة البيضاء، وهذا عادة يقرّب السمك على الرمل"
    else:
        fish_phrase = "الرغوة البيضاء ليست قوية جداً، لذلك النشاط أقرب لصيد حذر وليس هجوم قوي"

    # القرار
    if score >= 7:
        verdict = "GO"
        verdict_sentence = "السبوت هذا قوي ومقنع جداً لرحلة المساء/الليل."
    elif score >= 5:
        verdict = "GO بحذر"
        verdict_sentence = "السبوت مقبول، لكن النجاح مربوط بالساعة والتثبيت الصحيح."
    else:
        verdict = "NO-GO"
        verdict_sentence = "السبوت هذا مرفوض حالياً لأن المخاطر أعلى من الفائدة."

    alt_line = ""
    if better and better["score"] > score:
        alt_line = (
            f"المقارنة التقنية الصارمة تمنح أفضلية أولية لـ {better['name']} "
            f"({better['score']}/10) مقارنة بـ {location_name} ({score}/10)."
        )
    else:
        alt_line = f"التحليل الداخلي يعطي الأفضلية للموقع الحالي {location_name} على البدائل المتاحة في الجرد."

    return f"""
تحديثات البيانات الحية ليوم {fmt_date_ar(target_date)}، {alt_line}

## 1. معادلة زاوية الموج والتيار الجانبي
- في {location_name}: الموج يدخل {wave_phrase}، وزاوية الاصطدام المحسوبة في أفضل ساعة هي **{best['wave_impact']}°**.
- التيار الجانبي المحسوب يساوي تقريباً **{best['longshore_kmh']} كم/س**، ولذلك توصية التثبيت هي **{best['lead']}**.
- نوع الريح في أفضل نافذة هو **{best['wind_type']}** بسرعة فعلية تقارب **{best['ws_eff']} كم/س**.

## 2. معالجة مخلفات البحر والأعشاب
- إرث آخر 48 ساعة: موج الرياح المتوسط **{past['avg_wwh']} م**.
- حالة البحر السابقة: **{"مدرر" if past["is_dirty"] else "نظيف"}**.
- الخلاصة التقنية: {debris_phrase}.
- تردد السويل في أفضل ساعة يساوي **{best['sw_p']} ث**، وهذا عنصر مهم في قرار "ينظف / ما ينظفش".

## 3. نشاط السمك وحزام الرغوة
- ارتفاع الموج الفعلي في أفضل ساعة هو **{best['wave_h']} م**.
- حالة الرغوة البيضاء (Écume): **{best['ecume']}**.
- {fish_phrase}

------------------------------

## 🎯 القرار النهائي والعملي
**{verdict}** — السكور المرجح **{score}/10** | الثقة **{conf}%**

{verdict_sentence}

### التكتيك المقترح
- **الرصاص:** {best['lead']}
- **أفضل ساعة:** {best['time'][-5:]}
- **المسافة المبدئية:** {"50-70 متر" if best['wave_h'] >= 0.5 else "35-55 متر"}
- **الطعم:** {"دود + ثوم" if "ينظف" in best["debris"] or "نعم" in best["ecume"] else "سردين/طعوم ثابتة"}
- **التحذير الرئيسي:** {" / ".join(summary["red_flags"]) if summary["red_flags"] else "لا توجد رايات حمراء حاسمة"}
""".strip()

def build_ai_payload(location_name, summary, alternatives):
    best = summary["best_hour"]
    payload = {
        "location_name": location_name,
        "weighted_score": summary["weighted_score"],
        "simple_score": summary["simple_score"],
        "confidence": summary["confidence"],
        "red_flags": summary["red_flags"],
        "coast": summary["coast"],
        "past_48h": summary["past"],
        "best_hour": best,
        "avg_longshore": summary["avg_longshore"],
        "avg_wind": summary["avg_wind"],
        "ecume_hours": summary["ecume_hours"],
        "alternatives": alternatives[:3]
    }
    return payload

@st.cache_data(ttl=1800, show_spinner=False)
def generate_ai_report(payload_json, deterministic_text, target_date_str):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None, "GEMINI_API_KEY غير موجود"

    try:
        client = genai.Client(api_key=api_key)

        prompt = f"""
أنت خبير صيد تونسي محترف. مهمتك ليست اختراع قرار جديد، بل شرح القرار الحسابي الموجود.

التاريخ: {target_date_str}

هذه هي البيانات الرقمية الحقيقية الخارجة من المحرك الحسابي:
{payload_json}

وهذا هو التقرير الحتمي الذي كتبه محرك الموقع:
{deterministic_text}

القواعد:
1) القرار النهائي يجب أن يبقى مطابقاً للـ weighted_score والـ red_flags.
2) لا تخترع أي أرقام غير موجودة.
3) اشرح بأسلوب واضح ومهني قريب من هذا الشكل:
   - تحديثات البيانات الحية...
   - 1) زاوية الموج والتيار الجانبي
   - 2) الأعشاب/الفساد/تنظيف السويل
   - 3) نشاط السمك وÉcume
   - القرار العملي والتكتيك
4) إذا كانت البدائل أقوى من الموقع الحالي، اذكر ذلك بصراحة.
5) إذا كان القرار الحسابي NO-GO أو ضعيف، لا تحاول تجميله.

اكتب التقرير بالعربية الواضحة مع لمسة تونسية تقنية.
"""
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.1,
                top_p=0.2,
                max_output_tokens=1800
            )
        )
        return (resp.text or "").strip(), None
    except Exception as e:
        return None, str(e)

# ══════════════════════════════════════════════════════════════
# UI
# ══════════════════════════════════════════════════════════════
st.title(APP_TITLE)
st.markdown("**المحرك الحسابي هو صاحب القرار — والذكاء الاصطناعي يشرح نفس الداتا فقط**")

target_date = target_date_from_offset(st.session_state.day_offset)

c1, c2, c3 = st.columns(3)
with c1:
    if st.button("🔵 اليوم", use_container_width=True):
        st.session_state.day_offset = 0
        st.session_state.deep_result = None
        st.rerun()
with c2:
    if st.button("🟢 غداً", use_container_width=True):
        st.session_state.day_offset = 1
        st.session_state.deep_result = None
        st.rerun()
with c3:
    if st.button("🟡 بعد غد", use_container_width=True):
        st.session_state.day_offset = 2
        st.session_state.deep_result = None
        st.rerun()

target_date = target_date_from_offset(st.session_state.day_offset)
st.info(f"📅 يوم التحليل: **{fmt_date_ar(target_date)}**")

st.divider()

col_map, col_scout = st.columns([2, 1])

with col_scout:
    st.subheader("🏆 ترتيب السبوتات")
    with st.spinner("AI Scout يفحص الساحل التونسي..."):
        scout_results = scan_tunisia(str(target_date))
        st.session_state.scan_results = scout_results

    top5 = scout_results[:5]
    if top5:
        for i, s in enumerate(top5, 1):
            color = "#00ff00" if s["score"] >= 7 else "#ffff00" if s["score"] >= 5 else "#ff8c00"
            st.markdown(f"""
            <div class="top-spot">
              <b>{i}. {s['name']}</b> — {s['region']}<br>
              🎯 <span style="color:{color};font-weight:bold">{s['score']}/10</span><br>
              📍 {s['lat']:.4f}, {s['lon']:.4f}
            </div>
            """, unsafe_allow_html=True)

            if st.button(f"⚓ تمركز على {s['name']}", key=f"go_{i}", use_container_width=True):
                st.session_state.lat = s["lat"]
                st.session_state.lon = s["lon"]
                st.session_state.map_center = [s["lat"], s["lon"]]
                st.session_state.deep_result = None
                st.rerun()

with col_map:
    st.subheader("🗺️ اختر السبوت")
    st.markdown("<div class='small-note'>الأنكر ثابت في الوسط — حرّك الخريطة حتى يصبح السبوت تحته</div>", unsafe_allow_html=True)

    m = folium.Map(
        location=st.session_state.map_center,
        zoom_start=8,
        tiles="CartoDB dark_matter",
        control_scale=True
    )

    for s in scout_results[:10]:
        color = "green" if s["score"] >= 7 else "orange" if s["score"] >= 5 else "red"
        folium.CircleMarker(
            [s["lat"], s["lon"]],
            radius=5,
            color=color,
            fill=True,
            fill_opacity=0.8,
            tooltip=f"{s['name']} — {s['score']}/10"
        ).add_to(m)

    st.markdown("<div class='anchor-box'>", unsafe_allow_html=True)
    map_data = st_folium(
        m,
        width=None,
        height=470,
        returned_objects=["center"],
        key="main_map"
    )
    st.markdown("<div class='anchor-overlay'>⚓</div></div>", unsafe_allow_html=True)

    if map_data and map_data.get("center"):
        center = map_data["center"]
        st.session_state.map_center = [center["lat"], center["lng"]]
        st.session_state.lat = round(center["lat"], 5)
        st.session_state.lon = round(center["lng"], 5)

    st.markdown(f"""
    <div class="spot-card">
      📍 <b>الإحداثيات الحالية تحت الأنكر</b><br>
      Lat: {st.session_state.lat} | Lon: {st.session_state.lon}
    </div>
    """, unsafe_allow_html=True)

st.divider()

if st.button("🔬 Deep Scan للموقع الحالي", type="primary", use_container_width=True):
    with st.spinner("تحليل هندسة الساحل..."):
        coast_info, coast_err = analyze_coast_geometry(st.session_state.lat, st.session_state.lon)

    if coast_err == "rate_limit":
        st.error("Open-Meteo rate limit — حاول بعد دقيقة.")
        st.stop()
    if coast_err == "inland":
        st.error("الموقع الحالي بري. حرّك الخريطة أكثر نحو الشاطئ/البحر.")
        st.stop()
    if coast_err:
        st.error(f"خطأ هندسة الساحل: {coast_err}")
        st.stop()

    if coast_info["coast_type"] == "بحيرة/سبخة":
        st.error("هذا الموقع ليس ساحلاً بحرياً مناسباً.")
        st.stop()

    with st.spinner("جلب بيانات البحر والطقس..."):
        marine_data, marine_err = fetch_marine(st.session_state.lat, st.session_state.lon)
        weather_data, weather_err = fetch_weather(st.session_state.lat, st.session_state.lon)

    if marine_err == "rate_limit" or weather_err == "rate_limit":
        st.error("تجاوز حد الـ API مؤقتاً.")
        st.stop()
    if marine_err or weather_err or not marine_data or not weather_data:
        st.error(f"خطأ جلب الداتا: {marine_err or weather_err}")
        st.stop()

    with st.spinner("تحليل إرث 48 ساعة..."):
        past = analyze_past_48h(marine_data, weather_data, target_date)

    with st.spinner("الحسابات الفيزيائية الدقيقة..."):
        rows, red_flags = compute_hourly_analysis(marine_data, weather_data, coast_info, target_date, past)

    if not rows:
        st.error(f"فشل التحليل: {red_flags}")
        st.stop()

    summary = summarize_analysis(rows, coast_info, past, red_flags, target_date)
    location_name = fetch_location_name(st.session_state.lat, st.session_state.lon)

    current_score = summary["weighted_score"]
    alternatives = [
        s for s in scout_results
        if haversine_km(st.session_state.lat, st.session_state.lon, s["lat"], s["lon"]) > 1.0
        and s["score"] > current_score
    ]

    deterministic_report = build_deterministic_report(location_name, summary, alternatives, target_date)
    ai_payload = build_ai_payload(location_name, summary, alternatives)
    ai_payload_json = json.dumps(ai_payload, ensure_ascii=False, indent=2)

    with st.spinner("Gemini يصوغ التقرير من نفس الداتا..."):
        ai_report, ai_err = generate_ai_report(ai_payload_json, deterministic_report, str(target_date))

    st.session_state.deep_result = {
        "location_name": location_name,
        "summary": summary,
        "deterministic_report": deterministic_report,
        "ai_report": ai_report,
        "ai_err": ai_err,
        "alternatives": alternatives,
        "payload_json": ai_payload_json
    }
    st.rerun()

# ══════════════════════════════════════════════════════════════
# RESULTS
# ══════════════════════════════════════════════════════════════
if st.session_state.deep_result:
    result = st.session_state.deep_result
    summary = result["summary"]
    best = summary["best_hour"]

    st.subheader("⚖️ القرار النهائي")

    if summary["weighted_score"] >= 7.0 and summary["confidence"] >= 70 and not summary["red_flags"]:
        st.markdown(f"""
        <div class="go-box">
          <h2 style="color:#00ff00;text-align:center">✅ GO — ممتاز</h2>
          <p style="text-align:center;font-size:1.15em">
            السكور المرجح: <b>{summary['weighted_score']}/10</b> |
            الثقة: <b>{summary['confidence']}%</b>
          </p>
        </div>
        """, unsafe_allow_html=True)
    elif summary["weighted_score"] >= 5.0:
        st.markdown(f"""
        <div class="warn-box">
          <h2 style="color:#ffd166;text-align:center">🟡 GO بحذر</h2>
          <p style="text-align:center;font-size:1.15em">
            السكور المرجح: <b>{summary['weighted_score']}/10</b> |
            الثقة: <b>{summary['confidence']}%</b>
          </p>
        </div>
        """, unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="nogo-box">
          <h2 style="color:#ff4d4d;text-align:center">🔴 NO-GO</h2>
          <p style="text-align:center;font-size:1.15em">
            السكور المرجح: <b>{summary['weighted_score']}/10</b> |
            الثقة: <b>{summary['confidence']}%</b>
          </p>
        </div>
        """, unsafe_allow_html=True)

    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("أفضل ساعة", best["time"][-5:], delta=f"سكور {best['score']}")
    m2.metric("التيار الجانبي", f"{summary['avg_longshore']} كم/س")
    m3.metric("Écume", f"{summary['ecume_hours']} ساعة")
    m4.metric("القمر", f"{int(summary['moon_factor']*100)}%")
    m5.metric("الرصاص", best["lead"])

    if summary["red_flags"]:
        st.error("🚩 التحذيرات: " + " | ".join(summary["red_flags"]))

    st.markdown("---")
    st.subheader("📍 هوية السبوت")
    st.markdown(f"""
    <div class="spot-card">
      <b>{result['location_name']}</b><br>
      🧭 اتجاه البحر: {summary['coast']['shoreline_normal']}°<br>
      🏖️ نوع الساحل: {summary['coast']['coast_type']}<br>
      📊 انكشاف البحر: {int(summary['coast']['coast_exposure']*100)}%<br>
      🌊 إغلاق الخليج: {int(summary['coast']['bay_factor']*100)}%
    </div>
    """, unsafe_allow_html=True)

    st.subheader("📊 تحليل إرث 48 ساعة")
    p1, p2, p3, p4, p5 = st.columns(5)
    p1.metric("موج الرياح", f"{summary['past']['avg_wwh']} م")
    p2.metric("تردد موج الرياح", f"{summary['past']['avg_wwp']} ث")
    p3.metric("Swell", f"{summary['past']['avg_swh']} م")
    p4.metric("تردد Swell", f"{summary['past']['avg_swp']} ث")
    p5.metric("الحالة", "🔴 مدرر" if summary["past"]["is_dirty"] else "🟢 نظيف")

    st.markdown("---")
    st.subheader("🧮 التقرير الحتمي من محرك الموقع")
    st.markdown(result["deterministic_report"])

    st.markdown("---")
    st.subheader("🧠 تقرير Gemini (شرح لنفس الداتا)")
    if result["ai_err"]:
        st.warning(f"تعذر إنشاء التقرير النصي: {result['ai_err']}")
    elif result["ai_report"]:
        st.markdown(result["ai_report"])
    else:
        st.info("لا يوجد تقرير AI.")

    st.markdown("---")
    st.subheader("📊 الجدول الزمني")
    df = pd.DataFrame(summary["rows"])[[
        "time","score","wind_type","wind_kmh","gust_kmh","ws_eff",
        "wave_h","wave_p","wave_impact","sw_h","sw_p","sw_impact",
        "longshore_kmh","lead","debris","ecume","sst_c","rain_mm","vis_km"
    ]].copy()

    df.columns = [
        "الوقت","السكور","نوع الريح","ريح","هبات","ريح فعلية",
        "موج","تردد موج","زاوية الموج","Swell","تردد Swell","زاوية Swell",
        "تيار جانبي","الرصاص","الأعشاب","Écume","حرارة البحر","مطر","رؤية"
    ]

    def score_style(v):
        if v >= 7:
            return "background:#0a3d0a;color:#00ff00"
        if v >= 5:
            return "background:#3d3d0a;color:#ffff00"
        if v >= 4:
            return "background:#3d2e0a;color:#ffa500"
        return "background:#3d0a0a;color:#ff4d4d"

    styled = df.style.applymap(score_style, subset=["السكور"])
    st.dataframe(styled, use_container_width=True, hide_index=True)

    if result["alternatives"]:
        st.markdown("---")
        st.subheader("💡 بدائل أقوى من الموقع الحالي")
        for alt in result["alternatives"][:3]:
            dist = haversine_km(st.session_state.lat, st.session_state.lon, alt["lat"], alt["lon"])
            diff = round(alt["score"] - summary["weighted_score"], 1)
            st.markdown(f"""
            <div class="spot-card">
              <b>{alt['name']}</b> — {alt['region']}<br>
              🎯 {alt['score']}/10 (<span style="color:#00ff00">+{diff}</span>)<br>
              📏 {dist} كم
            </div>
            """, unsafe_allow_html=True)

            if st.button(f"⚓ انتقل إلى {alt['name']}", key=f"alt_{alt['name']}", use_container_width=True):
                st.session_state.lat = alt["lat"]
                st.session_state.lon = alt["lon"]
                st.session_state.map_center = [alt["lat"], alt["lon"]]
                st.session_state.deep_result = None
                st.rerun()

    with st.expander("🔧 payload المرسل إلى Gemini"):
        st.code(result["payload_json"], language="json")

st.caption("© Tunisia Fishing Advisor | deterministic engine first, AI wording second")
