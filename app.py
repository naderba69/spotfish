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
# 1. CONFIG
# ══════════════════════════════════════════════════════════════
TUNIS_TZ    = ZoneInfo("Africa/Tunis")
USER_AGENT  = "TunisiaFishingAdvisor/10.5"
GEMINI_MODEL = "gemini-2.5-flash"

st.set_page_config(
    page_title="🎣 مستشار الصيد | تونس",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
body{direction:rtl}
.block-container{padding-top:.6rem}
.go-box{
    background:linear-gradient(135deg,#0a3d0a,#0d520d);
    padding:20px;border-radius:12px;
    border:2px solid #00ff00;
    box-shadow:0 4px 14px rgba(0,255,0,.25);
    margin:12px 0
}
.warn-box{
    background:linear-gradient(135deg,#3d2e0a,#52400d);
    padding:20px;border-radius:12px;
    border:2px solid #ffa500;
    margin:12px 0
}
.nogo-box{
    background:linear-gradient(135deg,#3d0a0a,#520d0d);
    padding:20px;border-radius:12px;
    border:2px solid #ff0000;
    box-shadow:0 4px 14px rgba(255,0,0,.25);
    margin:12px 0
}
.spot-card{
    background:#0a1a2e;padding:13px;
    border-radius:8px;border:1px solid #1f77b4;
    margin-bottom:8px
}
.top-spot{
    background:#111c2d;padding:13px;
    border-radius:8px;border:1px solid #3b82f6;
    margin-bottom:8px;transition:transform .2s
}
.top-spot:hover{transform:scale(1.02)}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# 2. SESSION STATE
# ══════════════════════════════════════════════════════════════
_DEF = {
    "lat": 36.8333,
    "lon": 11.1000,
    "map_center": [36.8333, 11.1000],
    "day_offset": 1,
    "scan_results": None,
    "deep_result": None,
}
for k, v in _DEF.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════
# 3. SPOTS DATABASE
# ══════════════════════════════════════════════════════════════
SPOTS = [
    {"name": "رأس أنجلة",           "lat": 37.3470, "lon":  9.7440, "region": "بنزرت"},
    {"name": "بنزرت المرسى",         "lat": 37.2744, "lon":  9.8628, "region": "بنزرت"},
    {"name": "رأس الدرك",            "lat": 37.2742, "lon":  9.8739, "region": "بنزرت"},
    {"name": "غار الملح",            "lat": 37.1728, "lon": 10.0872, "region": "بنزرت"},
    {"name": "رفراف",                "lat": 37.1889, "lon": 10.1833, "region": "بنزرت"},
    {"name": "سيدي علي المكي",       "lat": 37.1470, "lon": 10.2500, "region": "بنزرت"},
    {"name": "طبرقة",                "lat": 36.9544, "lon":  8.7578, "region": "جندوبة"},
    {"name": "المرسى",               "lat": 36.8780, "lon": 10.3300, "region": "تونس"},
    {"name": "قمرت",                 "lat": 36.9200, "lon": 10.2900, "region": "تونس"},
    {"name": "سليمان الشاطئ",        "lat": 36.7060, "lon": 10.4920, "region": "نابل"},
    {"name": "الحمامات الشمالية",    "lat": 36.4300, "lon": 10.7000, "region": "نابل"},
    {"name": "الحمامات الجنوبية",    "lat": 36.3600, "lon": 10.5400, "region": "نابل"},
    {"name": "نابل الشاطئ",          "lat": 36.4561, "lon": 10.7376, "region": "نابل"},
    {"name": "قربة",                 "lat": 36.5780, "lon": 10.8580, "region": "نابل"},
    {"name": "منزل تميم",            "lat": 36.7810, "lon": 10.9950, "region": "نابل"},
    {"name": "قليبية",               "lat": 36.8333, "lon": 11.1000, "region": "نابل"},
    {"name": "الهوارية",             "lat": 37.0539, "lon": 11.0581, "region": "نابل"},
    {"name": "هرقلة",                "lat": 36.0330, "lon": 10.5100, "region": "سوسة"},
    {"name": "شط مريم",              "lat": 35.9300, "lon": 10.5600, "region": "سوسة"},
    {"name": "سوسة بوجعفر",          "lat": 35.8256, "lon": 10.6369, "region": "سوسة"},
    {"name": "المنستير الشاطئ",      "lat": 35.7672, "lon": 10.8111, "region": "المنستير"},
    {"name": "صيادة",                "lat": 35.6680, "lon": 10.8900, "region": "المنستير"},
    {"name": "المهدية الكورنيش",     "lat": 35.5047, "lon": 11.0622, "region": "المهدية"},
    {"name": "الشابة",               "lat": 35.2370, "lon": 11.1150, "region": "المهدية"},
    {"name": "صفاقس رأس الطابية",    "lat": 34.7333, "lon": 10.7633, "region": "صفاقس"},
    {"name": "قرقنة",                "lat": 34.7333, "lon": 11.1167, "region": "صفاقس"},
    {"name": "قابس الشاطئ",          "lat": 33.8815, "lon": 10.0982, "region": "قابس"},
    {"name": "بوغرارة",              "lat": 33.6500, "lon": 10.7500, "region": "مدنين"},
    {"name": "جربة أجيم",            "lat": 33.7167, "lon": 10.7667, "region": "جربة"},
    {"name": "أغير",                 "lat": 33.7700, "lon": 11.0300, "region": "جربة"},
    {"name": "جرجيس",                "lat": 33.5042, "lon": 10.8681, "region": "مدنين"},
]

# ══════════════════════════════════════════════════════════════
# 4. MATH HELPERS
# ══════════════════════════════════════════════════════════════
def safe_avg(lst):
    return sum(lst) / len(lst) if lst else 0.0

def angle_diff_180(a, b):
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d

def circular_mean(angles):
    if not angles:
        return 0.0
    s = sum(math.sin(math.radians(a)) for a in angles) / len(angles)
    c = sum(math.cos(math.radians(a)) for a in angles) / len(angles)
    return math.degrees(math.atan2(s, c)) % 360

def moon_phase_factor(d: date) -> float:
    delta = (d - date(2024, 1, 11)).days % 29.53
    return round(0.5 + 0.5 * abs(math.cos(2 * math.pi * delta / 29.53)), 3)

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) *
         math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return round(2 * R * math.asin(math.sqrt(a)), 1)

def destination_point(lat1, lon1, bearing_deg, dist_km):
    R = 6371.0
    b = math.radians(bearing_deg)
    φ1 = math.radians(lat1)
    λ1 = math.radians(lon1)
    φ2 = math.asin(
        math.sin(φ1) * math.cos(dist_km / R) +
        math.cos(φ1) * math.sin(dist_km / R) * math.cos(b)
    )
    λ2 = λ1 + math.atan2(
        math.sin(b) * math.sin(dist_km / R) * math.cos(φ1),
        math.cos(dist_km / R) - math.sin(φ1) * math.sin(φ2)
    )
    return math.degrees(φ2), math.degrees(λ2)

def fmt_date_ar(d: date) -> str:
    days   = ["الاثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت","الأحد"]
    months = {1:"جانفي",2:"فيفري",3:"مارس",4:"أفريل",5:"ماي",6:"جوان",
              7:"جويلية",8:"أوت",9:"سبتمبر",10:"أكتوبر",11:"نوفمبر",12:"ديسمبر"}
    return f"{days[d.weekday()]} {d.day} {months[d.month]} {d.year}"

def parse_dt(ts: str) -> datetime:
    return datetime.fromisoformat(ts)

def target_date_from_offset(offset: int) -> date:
    return datetime.now(TUNIS_TZ).date() + timedelta(days=offset)

# ══════════════════════════════════════════════════════════════
# 5. HTTP HELPERS
# ══════════════════════════════════════════════════════════════
def get_json(url, params, timeout=20):
    r = requests.get(
        url, params=params, timeout=timeout,
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
        except Exception:
            return default
    return default

# ══════════════════════════════════════════════════════════════
# 6. API CALLS  (cached)
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def analyze_coast(lat: float, lon: float):
    """
    12 نقطة حول الإحداثيات بنصف قطر 3 كم.
    نقاط بارتفاع ≤ 0.5م → بحر.
    shoreline_normal = المتوسط الدائري لاتجاهات البحر
                     = الاتجاه من الشاطئ نحو البحر.
    """
    bearings = range(0, 360, 30)
    pts = [destination_point(lat, lon, b, 3.0) for b in bearings]

    lats_s = ",".join(str(round(p[0], 4)) for p in pts)
    lons_s = ",".join(str(round(p[1], 4)) for p in pts)

    try:
        data  = get_json("https://api.open-meteo.com/v1/elevation",
                         {"latitude": lats_s, "longitude": lons_s}, timeout=12)
        elevs = data.get("elevation", [])
    except requests.HTTPError as e:
        code = e.response.status_code if e.response else 0
        return None, "rate_limit" if code == 429 else f"elev_http_{code}"
    except Exception as e:
        return None, f"elev_err:{e}"

    if len(elevs) != len(pts):
        return None, "elev_incomplete"

    sea_b = [b for b, e in zip(bearings, elevs) if e is not None and e <= 0.5]
    if not sea_b:
        return None, "inland"

    sn       = circular_mean(sea_b)
    exposure = round(len(sea_b) / len(pts), 3)

    if len(sea_b) >= 2:
        avg_s = safe_avg([math.sin(math.radians(b)) for b in sea_b])
        avg_c = safe_avg([math.cos(math.radians(b)) for b in sea_b])
        R_bar = min(math.sqrt(avg_s**2 + avg_c**2), 0.9999)
        bay   = round(max(0.0, 1.0 - math.degrees(
                    math.sqrt(-2.0 * math.log(R_bar))) / 90.0), 3)
    else:
        bay = 0.5

    if exposure < 0.05:
        ctype = "بحيرة/سبخة"
    elif exposure > 0.65:
        ctype = "ساحل مفتوح"
    elif bay > 0.55:
        ctype = "خليج شبه مغلق"
    else:
        ctype = "ساحل عادي"

    return {
        "shoreline_normal": round(sn, 1),
        "coast_exposure"  : exposure,
        "bay_factor"      : bay,
        "coast_type"      : ctype,
    }, None


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_marine(lat: float, lon: float):
    try:
        data = get_json("https://marine-api.open-meteo.com/v1/marine", {
            "latitude" : lat, "longitude": lon,
            "hourly"   : ("wave_height,wave_direction,wave_period,"
                          "wind_wave_height,wind_wave_direction,wind_wave_period,"
                          "swell_wave_height,swell_wave_direction,swell_wave_period,"
                          "sea_surface_temperature"),
            "past_days": 2, "forecast_days": 3, "timezone": "auto"
        }, timeout=20)
        if "hourly" not in data:
            return None, "marine_no_hourly"
        return data, None
    except requests.HTTPError as e:
        code = e.response.status_code if e.response else 0
        return None, "rate_limit" if code == 429 else f"marine_http_{code}"
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_weather(lat: float, lon: float):
    try:
        data = get_json("https://api.open-meteo.com/v1/forecast", {
            "latitude" : lat, "longitude": lon,
            "hourly"   : ("wind_speed_10m,wind_direction_10m,"
                          "wind_gusts_10m,precipitation,visibility"),
            "past_days": 2, "forecast_days": 3, "timezone": "auto"
        }, timeout=20)
        if "hourly" not in data:
            return None, "weather_no_hourly"
        return data, None
    except requests.HTTPError as e:
        code = e.response.status_code if e.response else 0
        return None, "rate_limit" if code == 429 else f"weather_http_{code}"
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_location_name(lat: float, lon: float) -> str:
    try:
        data = get_json("https://nominatim.openstreetmap.org/reverse", {
            "lat": lat, "lon": lon, "format": "json",
            "accept-language": "ar", "zoom": 14
        }, timeout=8)
        a = data.get("address", {})
        return (a.get("beach") or a.get("hamlet") or a.get("village") or
                a.get("suburb") or a.get("town") or
                a.get("city") or a.get("state") or "ساحل تونسي")
    except Exception:
        return "ساحل تونسي"

# ══════════════════════════════════════════════════════════════
# 7. PHYSICS ENGINE
# ══════════════════════════════════════════════════════════════
def classify_wind(wd_from: float, sn: float, ws_eff: float):
    """
    wd_from = اتجاه مصدر الريح (FROM) — نفس مفهوم Windy
    sn      = اتجاه الشاطئ → البحر
    إذا wd_from ≈ sn  → الريح قادمة من البحر → وش
    إذا wd_from ≈ sn+180 → قادمة من البر → بر
    """
    diff = angle_diff_180(wd_from, sn)

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


def past_48h_analysis(marine, weather, tgt_date: date) -> dict:
    times      = weather["hourly"].get("time", [])
    lookup     = build_lookup(marine)
    tgt_start  = datetime.combine(tgt_date, datetime.min.time())
    past_start = tgt_start - timedelta(hours=48)

    p_wwh, p_wwp, p_swh, p_swp = [], [], [], []
    for ts in times:
        dt = parse_dt(ts)
        if not (past_start <= dt < tgt_start):
            continue
        wwh = gv(marine, lookup, "wind_wave_height",  ts)
        wwp = gv(marine, lookup, "wind_wave_period",  ts)
        swh = gv(marine, lookup, "swell_wave_height", ts)
        swp = gv(marine, lookup, "swell_wave_period", ts)
        if wwh > 0.05:
            p_wwh.append(wwh); p_wwp.append(wwp)
        if swh > 0.05:
            p_swh.append(swh); p_swp.append(swp)

    avg_wwh = safe_avg(p_wwh)
    avg_wwp = safe_avg(p_wwp)
    return {
        "avg_wwh" : round(avg_wwh, 2),
        "avg_wwp" : round(avg_wwp, 1),
        "avg_swh" : round(safe_avg(p_swh), 2),
        "avg_swp" : round(safe_avg(p_swp), 1),
        "is_dirty": (avg_wwh > 1.2) and (avg_wwp < 6.5),
    }


def compute_hourly(marine, weather, coast, tgt_date: date, past: dict):
    sn       = coast["shoreline_normal"]
    bay      = coast["bay_factor"]
    exposure = coast["coast_exposure"]

    lookup = build_lookup(marine)
    times  = weather["hourly"].get("time", [])

    wind_spd = weather["hourly"].get("wind_speed_10m",    [])
    wind_dir = weather["hourly"].get("wind_direction_10m", [])
    gusts    = weather["hourly"].get("wind_gusts_10m",    [])
    precip   = weather["hourly"].get("precipitation",     [])
    vis_arr  = weather["hourly"].get("visibility",        [])

    moon_b = max(0.0, (moon_phase_factor(tgt_date) - 0.55) * 1.2)
    rows, red_flags = [], set()

    def _w(arr, idx, default=0.0):
        if idx < len(arr) and arr[idx] is not None:
            try:
                return float(arr[idx])
            except Exception:
                return default
        return default

    for i, ts in enumerate(times):
        dt = parse_dt(ts)
        if dt.date() != tgt_date:
            continue

        ws   = _w(wind_spd, i)
        wd   = _w(wind_dir, i)
        gust = _w(gusts,    i)
        rain = _w(precip,   i)
        vis  = _w(vis_arr,  i, 24140.0) or 24140.0

        # تأثير الهبات المنطقي
        ws_eff = ws + 0.35 * max(0.0, gust - ws)

        wave_h   = gv(marine, lookup, "wave_height",           ts)
        wave_dir = gv(marine, lookup, "wave_direction",        ts)
        wave_p   = gv(marine, lookup, "wave_period",           ts)
        ww_h     = gv(marine, lookup, "wind_wave_height",      ts)
        ww_dir   = gv(marine, lookup, "wind_wave_direction",   ts)
        ww_p     = gv(marine, lookup, "wind_wave_period",      ts)
        sw_h     = gv(marine, lookup, "swell_wave_height",     ts)
        sw_dir   = gv(marine, lookup, "swell_wave_direction",  ts)
        sw_p     = gv(marine, lookup, "swell_wave_period",     ts)
        sst      = gv(marine, lookup, "sea_surface_temperature", ts, 18.0)

        # تأثير الخليج على الأمواج
        ww_h_eff   = ww_h   * (1.0 - bay * 0.50)
        sw_h_eff   = sw_h   * (1.0 - bay * 0.30)
        wave_h_eff = wave_h * (1.0 - bay * 0.40)
        total_h    = max(wave_h_eff, ww_h_eff + sw_h_eff)

        # الزوايا — كلها بمعيار FROM كـ Windy
        wind_label, wind_shore_a, wind_bonus = classify_wind(wd, sn, ws_eff)
        wave_impact = angle_diff_180(wave_dir, sn)
        ww_impact   = angle_diff_180(ww_dir,   sn)
        sw_impact   = angle_diff_180(sw_dir,   sn)

        # التيار الجانبي — فقط للأمواج القادمة من البحر بزاوية واقعية
        if 10 < wave_impact <= 80 and total_h > 0.05:
            ir  = math.radians(wave_impact)
            v_ls = 1.17 * math.sqrt(9.81 * total_h) * math.sin(ir) * math.cos(ir)
        else:
            v_ls = 0.0
        v_kmh = max(0.0, (v_ls + ws_eff * 0.015) * 3.6)

        # توصية الرصاص
        if v_kmh > 1.8:
            lead = "سبايك 140غ"
        elif v_kmh > 1.0:
            lead = "هرمي 120غ"
        else:
            lead = "زيتوني 100غ"

        # حالة الأعشاب
        clean_swell = (
            past["is_dirty"] and
            sw_p >= 8.0 and sw_h_eff >= 0.35 and sw_impact < 45
        )
        if clean_swell:
            debris = "Swell ينظف 🟢"
        elif past["is_dirty"]:
            debris = "مدرر/بقايا حشيش 🔴"
        else:
            debris = "نظيف 🟢"

        # Écume
        ecume = (
            "نعم ✅"
            if "وش" in wind_label and 0.4 <= total_h <= 1.5
                and wave_impact < 55 and ws_eff >= 10
            else "لا ❌"
        )

        # Rip
        if total_h > 1.2 and wave_p > 8 and 20 <= wave_impact <= 60:
            rip = "عالي ⚠️"
        elif total_h > 0.9 and wave_p > 6:
            rip = "متوسط"
        else:
            rip = "منخفض"

        # ━━━ SCORING ━━━
        score = 10.0 + wind_bonus + moon_b

        if total_h < 0.25:
            score -= 3.0
        elif total_h > 2.2:
            score -= 2.0

        if v_kmh > 2.2:
            score -= 3.5;  red_flags.add("تيار جانبي قوي")
        elif v_kmh > 1.2:
            score -= 1.5

        if ws_eff > 55:
            score -= 5.0;  red_flags.add("ريح عنيفة >55 كم/س")
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

        if clean_swell:
            score += 1.4
        elif past["is_dirty"]:
            score -= 2.0;  red_flags.add("بحر مدرر من إرث 48 ساعة")

        if exposure > 0.75 and total_h > 1.6:
            score -= 1.0

        score = round(max(0.0, min(10.0, score)), 1)

        rows.append({
            "time"           : ts[-5:],
            "hour"           : dt.hour,
            "score"          : score,
            "wind_kmh"       : round(ws, 1),
            "gust_kmh"       : round(gust, 1),
            "ws_eff"         : round(ws_eff, 1),
            "wind_dir_from"  : round(wd, 0),
            "wind_type"      : wind_label,
            "wind_shore_a"   : wind_shore_a,
            "wave_h"         : round(wave_h_eff, 2),
            "wave_p"         : round(wave_p, 1),
            "wave_impact"    : round(wave_impact, 1),
            "ww_h"           : round(ww_h_eff, 2),
            "ww_p"           : round(ww_p, 1),
            "sw_h"           : round(sw_h_eff, 2),
            "sw_p"           : round(sw_p, 1),
            "sw_impact"      : round(sw_impact, 1),
            "longshore_kmh"  : round(v_kmh, 2),
            "lead"           : lead,
            "rip"            : rip,
            "debris"         : debris,
            "ecume"          : ecume,
            "sst_c"          : round(sst, 1),
            "rain_mm"        : round(rain, 1),
            "vis_km"         : round(vis / 1000, 1),
        })

    return rows, sorted(red_flags)


def weighted_score(rows) -> float:
    prime = set(range(4, 9)) | set(range(17, 24))
    tw = ts = 0.0
    for r in rows:
        w = 2.5 if r["hour"] in prime else 1.0
        tw += w; ts += r["score"] * w
    return round(ts / tw, 2) if tw else 0.0


def build_summary(rows, coast, past, red_flags, tgt_date: date) -> dict:
    ws = weighted_score(rows)
    best = max(rows, key=lambda x: x["score"])
    return {
        "weighted_score"  : ws,
        "simple_score"    : round(safe_avg([r["score"] for r in rows]), 2),
        "best_hour"       : best,
        "avg_longshore"   : round(safe_avg([r["longshore_kmh"] for r in rows]), 2),
        "avg_wind"        : round(safe_avg([r["ws_eff"]         for r in rows]), 1),
        "ecume_hours"     : sum(1 for r in rows if "نعم" in r["ecume"]),
        "confidence"      : max(35, 92 - 14 * len(red_flags)),
        "coast"           : coast,
        "past"            : past,
        "red_flags"       : red_flags,
        "rows"            : rows,
        "moon"            : moon_phase_factor(tgt_date),
        "target_date"     : str(tgt_date),
    }

# ══════════════════════════════════════════════════════════════
# 8. AI SCOUT
# ══════════════════════════════════════════════════════════════
def _quick_score(spot: dict, tgt_date: date):
    coast, err = analyze_coast(spot["lat"], spot["lon"])
    if err or not coast or coast["coast_type"] == "بحيرة/سبخة":
        return None

    marine, e1 = fetch_marine(spot["lat"], spot["lon"])
    weather, e2 = fetch_weather(spot["lat"], spot["lon"])
    if e1 or e2 or not marine or not weather:
        return None

    lookup = build_lookup(marine)
    sn     = coast["shoreline_normal"]
    bay    = coast["bay_factor"]
    times  = weather["hourly"].get("time", [])
    scores = []

    for i, ts in enumerate(times):
        if parse_dt(ts).date() != tgt_date:
            continue

        def _w(arr, default=0.0):
            if i < len(arr) and arr[i] is not None:
                try:    return float(arr[i])
                except: return default
            return default

        ws    = _w(weather["hourly"].get("wind_speed_10m",    []))
        gust  = _w(weather["hourly"].get("wind_gusts_10m",    []))
        wd    = _w(weather["hourly"].get("wind_direction_10m", []))
        wave_h   = gv(marine, lookup, "wave_height",          ts) * (1 - bay * 0.40)
        wave_dir = gv(marine, lookup, "wave_direction",       ts)
        sw_p     = gv(marine, lookup, "swell_wave_period",    ts)
        sst      = gv(marine, lookup, "sea_surface_temperature", ts, 18.0)

        ws_eff   = ws + 0.35 * max(0.0, gust - ws)
        diff_w   = angle_diff_180(wd,       sn)
        diff_wave= angle_diff_180(wave_dir, sn)

        sc = 10.0
        sc += 1.0 if diff_w <= 45 else (0.4 if diff_w >= 135 else -1.0)
        sc -= 3.0 if wave_h < 0.2 else (1.8 if wave_h > 2.0 else 0.0)
        sc += 0.3 if 10 < diff_wave <= 80 else (-0.8 if diff_wave > 90 else 0.0)
        sc -= 4.0 if ws_eff > 45 else (2.0 if ws_eff > 35 else 0.0)
        sc += 0.4 if sw_p >= 8 else 0.0
        sc -= 1.3 if sst < 15 else (-0.3 if 19 <= sst <= 24 else 0.0)
        sc = max(0.0, min(10.0, sc))

        hr = parse_dt(ts).hour
        w  = 2.5 if hr in (set(range(4, 9)) | set(range(17, 24))) else 1.0
        scores.append((sc, w))

    if not scores:
        return None
    total = sum(s * w for s, w in scores)
    tw    = sum(w for _, w in scores)
    return round(total / tw, 2) if tw else None


@st.cache_data(ttl=3600, show_spinner=False)
def scan_tunisia(tgt_date_str: str) -> list:
    tgt = date.fromisoformat(tgt_date_str)
    results = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {ex.submit(_quick_score, s, tgt): s for s in SPOTS}
        for f in as_completed(futures):
            spot  = futures[f]
            score = f.result()
            if score is not None:
                results.append({
                    "name"  : spot["name"],
                    "region": spot["region"],
                    "lat"   : spot["lat"],
                    "lon"   : spot["lon"],
                    "score" : score,
                })
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

# ══════════════════════════════════════════════════════════════
# 9. DETERMINISTIC REPORT
# ══════════════════════════════════════════════════════════════
def deterministic_report(loc_name: str, summary: dict,
                          alternatives: list, tgt_date: date) -> str:
    score = summary["weighted_score"]
    best  = summary["best_hour"]
    past  = summary["past"]
    conf  = summary["confidence"]

    alt   = alternatives[0] if alternatives else None

    # مقارنة
    if alt and alt["score"] > score:
        compare_line = (
            f"المقارنة التقنية الصارمة تمنح الأفضلية لـ **{alt['name']}** "
            f"({alt['score']}/10) مقارنة بـ {loc_name} ({score}/10)."
        )
    else:
        compare_line = (
            f"التحليل الداخلي يعطي الأفضلية للموقع الحالي "
            f"**{loc_name}** ({score}/10) على البدائل المتاحة."
        )

    # زاوية الموج
    wi = best["wave_impact"]
    if wi <= 20:
        wave_phrase = "بزاوية مستقيمة تقريباً — مثالي"
    elif wi <= 55:
        wave_phrase = "بزاوية مائلة قابلة للخدمة"
    else:
        wave_phrase = "بزاوية جانبية مزعجة"

    # الأعشاب
    if "ينظف" in best["debris"]:
        debris_phrase = "Swell ينظف الخط ويطرد الوسخ خارج منطقة الصيد"
    elif "مدرر" in best["debris"]:
        debris_phrase = "إرث الـ48 ساعة يبقي البحر وسخاً ويشدّ الأعشاب في الخيط"
    else:
        debris_phrase = "البحر نظيف وما فيه فساد يُذكر"

    # رغوة
    if "نعم" in best["ecume"]:
        fish_phrase = "حزام الرغوة البيضاء متوقع — يقرّب السمك على الرمل"
    else:
        fish_phrase = "رغوة ضعيفة — صيد حذر أكثر من هجوم قوي"

    # قرار
    if score >= 7:
        verdict = "✅ GO — ممتاز"
        tactic  = "اذهب للسبوت — رحلة المساء/الليل مثالية"
    elif score >= 5:
        verdict = "🟡 GO بحذر"
        tactic  = "اذهب لكن انتبه للتيار وتحقق من الساعة"
    else:
        verdict = "🔴 NO-GO"
        tactic  = "لا تذهب لهذا السبوت اليوم — البدائل أفضل"

    dist = (f"{best['wave_h']*60:.0f}-{best['wave_h']*80:.0f} متر"
            if best["wave_h"] >= 0.5 else "35-55 متر")

    bait = ("دود + ثوم" if ("ينظف" in best["debris"] or "نعم" in best["ecume"])
            else "سردين/طعوم ثابتة")

    flags_txt = " | ".join(summary["red_flags"]) if summary["red_flags"] else "لا توجد"

    return f"""
تحديثات البيانات الحية ليوم {fmt_date_ar(tgt_date)}، {compare_line}

## 1. معادلة زاوية الموج والتيار الجانبي
- الموج يدخل {wave_phrase} — الزاوية المحسوبة في أفضل ساعة: **{wi}°**
- نوع الريح في أفضل نافذة: **{best['wind_type']}** — سرعة فعلية: **{best['ws_eff']} كم/س**
- التيار الجانبي: **{best['longshore_kmh']} كم/س** → الرصاص الموصى به: **{best['lead']}**

## 2. معالجة مخلفات البحر والأعشاب
- متوسط موج الرياح الـ48 ساعة السابقة: **{past['avg_wwh']} م / {past['avg_wwp']} ث**
- الحالة السابقة: **{"مدرر" if past["is_dirty"] else "نظيف"}**
- {debris_phrase}
- تردد السويل في أفضل ساعة: **{best['sw_p']} ث** (≥8 ث = مصفاة طبيعية)

## 3. نشاط السمك وحزام الرغوة
- ارتفاع الموج الفعلي: **{best['wave_h']} م**
- Écume (رغوة بيضاء): **{best['ecume']}**
- {fish_phrase}
- حرارة البحر: **{best['sst_c']}°C**

---

## 🎯 القرار النهائي ({score}/10 | ثقة {conf}%)
**{verdict}**

{tactic}

▸ الرصاص: **{best['lead']}**
▸ أفضل ساعة: **{best['time']}**
▸ المسافة: **{dist}**
▸ الطعم: **{bait}**
▸ تيار الساحب (Rip): **{best['rip']}**
▸ التحذيرات: {flags_txt}
""".strip()

# ══════════════════════════════════════════════════════════════
# 10. GEMINI REPORT  — SDK google-genai الجديد
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=1800, show_spinner=False)
def generate_ai_report(payload_json: str,
                       det_report: str,
                       tgt_date_str: str):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None, "GEMINI_API_KEY غير موجود في متغيرات البيئة"

    try:
        client = genai.Client(api_key=api_key)

        prompt = f"""
أنت خبير صيد تونسي محترف.
مهمتك: شرح القرار الحسابي فقط — لا تخترع قراراً جديداً.

التاريخ: {tgt_date_str}

── البيانات الرقمية الحقيقية من المحرك ──
{payload_json}

── التقرير الحتمي من المحرك ──
{det_report}

القواعد الصارمة:
1. القرار النهائي يجب أن يبقى مطابقاً للـ weighted_score والـ red_flags.
2. لا تخترع أرقاماً غير موجودة في البيانات.
3. اتبع الهيكل التالي حرفياً:
   - تحديثات البيانات الحية ليوم [التاريخ]، المقارنة التقنية تمنح الأفضلية...
   - ## 1. زاوية الموج والتيار الجانبي
   - ## 2. الأعشاب / الفساد / تنظيف Swell
   - ## 3. نشاط السمك وÉcume
   - ## 🎯 القرار العملي والتكتيك
4. إذا البدائل أقوى — اذكر ذلك بصراحة.
5. إذا القرار NO-GO — لا تجمّله.

اكتب بالعربية التقنية مع لمسة تونسية واضحة.
"""
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.05,
                top_p=0.15,
                max_output_tokens=2000,
            )
        )
        text = (resp.text or "").strip()
        return text, None

    except Exception as e:
        return None, f"خطأ Gemini: {e}"

# ══════════════════════════════════════════════════════════════
# 11. UI
# ══════════════════════════════════════════════════════════════
st.title("🎣 مستشار الصيد الفيزيائي | تونس v10.5")
st.markdown("**المحرك الحسابي هو صاحب القرار — Gemini يشرح نفس الداتا فقط**")

# ── اختيار اليوم ──
c1, c2, c3 = st.columns(3)
with c1:
    if st.button("🔵 اليوم",   use_container_width=True):
        st.session_state.day_offset = 0
        st.session_state.deep_result = None
        st.rerun()
with c2:
    if st.button("🟢 غداً",    use_container_width=True):
        st.session_state.day_offset = 1
        st.session_state.deep_result = None
        st.rerun()
with c3:
    if st.button("🟡 بعد غد", use_container_width=True):
        st.session_state.day_offset = 2
        st.session_state.deep_result = None
        st.rerun()

tgt_date = target_date_from_offset(st.session_state.day_offset)
st.info(f"📅 يوم التحليل: **{fmt_date_ar(tgt_date)}**")
st.divider()

col_map, col_scout = st.columns([2, 1])

# ── Scout ──
with col_scout:
    st.subheader("🏆 ترتيب السبوتات")
    with st.spinner("AI Scout يفحص الساحل التونسي..."):
        scout = scan_tunisia(str(tgt_date))
        st.session_state.scan_results = scout

    for i, s in enumerate(scout[:6], 1):
        color = "#00ff00" if s["score"] >= 7 else "#ffff00" if s["score"] >= 5 else "#ff8c00"
        st.markdown(f"""
        <div class="top-spot">
          <b>{i}. {s['name']}</b> — {s['region']}<br>
          🎯 <span style="color:{color};font-weight:bold;font-size:1.1em">{s['score']}/10</span><br>
          <small>📍 {s['lat']:.4f}, {s['lon']:.4f}</small>
        </div>
        """, unsafe_allow_html=True)

        if st.button(f"⚓ تمركز على {s['name']}", key=f"go_{i}",
                     use_container_width=True):
            st.session_state.lat        = s["lat"]
            st.session_state.lon        = s["lon"]
            st.session_state.map_center = [s["lat"], s["lon"]]
            st.session_state.deep_result = None
            st.rerun()

# ── Map ──
with col_map:
    st.subheader("🗺️ اختر السبوت")
    st.caption("الأنكر ⚓ ثابت في الوسط — حرّك الخريطة حتى يصبح السبوت تحته ثم اضغط Deep Scan")

    m = folium.Map(
        location=st.session_state.map_center,
        zoom_start=8,
        tiles="CartoDB dark_matter",
        control_scale=True
    )

    for s in scout[:10]:
        color = "green" if s["score"] >= 7 else "orange" if s["score"] >= 5 else "red"
        folium.CircleMarker(
            [s["lat"], s["lon"]], radius=5,
            color=color, fill=True, fill_opacity=0.8,
            tooltip=f"{s['name']} — {s['score']}/10"
        ).add_to(m)

    map_data = st_folium(
        m, width=None, height=480,
        returned_objects=["center"],
        key="main_map"
    )

    # أنكر وسط ثابت بصرياً
    st.markdown("""
    <div style="text-align:center;margin-top:-500px;margin-bottom:460px;
                pointer-events:none;z-index:9999;position:relative">
      <span style="font-size:52px;filter:drop-shadow(0 0 8px #ff0000)">⚓</span>
    </div>
    """, unsafe_allow_html=True)

    if map_data and map_data.get("center"):
        c  = map_data["center"]
        st.session_state.map_center = [c["lat"], c["lng"]]
        st.session_state.lat = round(c["lat"], 5)
        st.session_state.lon = round(c["lng"], 5)

    st.markdown(f"""
    <div class="spot-card">
      ⚓ <b>الإحداثيات تحت الأنكر</b><br>
      Lat: <b>{st.session_state.lat}</b> | Lon: <b>{st.session_state.lon}</b>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ── Deep Scan ──
if st.button("🔬 Deep Scan للموقع الحالي", type="primary", use_container_width=True):

    # Coast
    with st.spinner("🧭 تحليل هندسة الساحل..."):
        coast_info, coast_err = analyze_coast(
            st.session_state.lat, st.session_state.lon
        )

    if coast_err == "rate_limit":
        st.error("Open-Meteo rate limit — حاول بعد دقيقة.")
        st.stop()
    if coast_err == "inland":
        st.error("الموقع بري — حرّك الخريطة أكثر نحو الشاطئ.")
        st.stop()
    if coast_err:
        st.error(f"خطأ هندسة الساحل: {coast_err}")
        st.stop()
    if coast_info["coast_type"] == "بحيرة/سبخة":
        st.error("هذا الموقع بحيرة/سبخة — اختر ساحلاً بحرياً.")
        st.stop()

    # Data
    with st.spinner("📡 جلب بيانات البحر والطقس..."):
        marine_data, m_err = fetch_marine(st.session_state.lat, st.session_state.lon)
        weather_data, w_err = fetch_weather(st.session_state.lat, st.session_state.lon)

    if "rate_limit" in (m_err or "", w_err or ""):
        st.error("تجاوز حد الـ API — حاول بعد دقيقة.")
        st.stop()
    if m_err or w_err or not marine_data or not weather_data:
        st.error(f"خطأ جلب الداتا: {m_err or w_err}")
        st.stop()

    # Past 48h
    with st.spinner("📊 تحليل إرث 48 ساعة..."):
        past = past_48h_analysis(marine_data, weather_data, tgt_date)

    # Physics
    with st.spinner("⚙️ الحسابات الفيزيائية..."):
        rows, red_flags = compute_hourly(
            marine_data, weather_data, coast_info, tgt_date, past
        )

    if not rows:
        st.error("لم يتم العثور على بيانات لليوم المختار في هذه المنطقة.")
        st.stop()

    summary  = build_summary(rows, coast_info, past, red_flags, tgt_date)
    loc_name = fetch_location_name(st.session_state.lat, st.session_state.lon)

    current_score = summary["weighted_score"]
    alternatives  = [
        s for s in scout
        if haversine_km(st.session_state.lat, st.session_state.lon,
                         s["lat"], s["lon"]) > 1.0
           and s["score"] > current_score
    ]

    # Deterministic report
    det_report = deterministic_report(loc_name, summary, alternatives, tgt_date)

    # AI payload
    payload = {
        "location"       : loc_name,
        "weighted_score" : summary["weighted_score"],
        "simple_score"   : summary["simple_score"],
        "confidence"     : summary["confidence"],
        "red_flags"      : summary["red_flags"],
        "coast"          : summary["coast"],
        "past_48h"       : summary["past"],
        "best_hour"      : summary["best_hour"],
        "avg_longshore"  : summary["avg_longshore"],
        "avg_wind"       : summary["avg_wind"],
        "ecume_hours"    : summary["ecume_hours"],
        "moon"           : summary["moon"],
        "alternatives"   : alternatives[:3],
    }
    payload_json = json.dumps(payload, ensure_ascii=False, indent=2)

    # Gemini
    with st.spinner("🧠 Gemini يصوغ التقرير من نفس الداتا..."):
        ai_text, ai_err = generate_ai_report(
            payload_json, det_report, str(tgt_date)
        )

    st.session_state.deep_result = {
        "loc_name"       : loc_name,
        "summary"        : summary,
        "det_report"     : det_report,
        "ai_text"        : ai_text,
        "ai_err"         : ai_err,
        "alternatives"   : alternatives,
        "payload_json"   : payload_json,
    }
    st.rerun()

# ══════════════════════════════════════════════════════════════
# 12. RESULTS
# ══════════════════════════════════════════════════════════════
if st.session_state.deep_result:
    R       = st.session_state.deep_result
    summary = R["summary"]
    best    = summary["best_hour"]
    score   = summary["weighted_score"]
    conf    = summary["confidence"]

    # قرار
    st.subheader("⚖️ القرار النهائي")
    if score >= 7.0 and conf >= 70 and not summary["red_flags"]:
        st.markdown(f"""
        <div class="go-box">
          <h2 style="color:#00ff00;text-align:center">✅ GO — ممتاز</h2>
          <p style="text-align:center;font-size:1.15em">
            السكور المرجح: <b>{score}/10</b> | الثقة: <b>{conf}%</b>
          </p>
        </div>""", unsafe_allow_html=True)
    elif score >= 5.0:
        st.markdown(f"""
        <div class="warn-box">
          <h2 style="color:#ffd166;text-align:center">🟡 GO بحذر</h2>
          <p style="text-align:center;font-size:1.15em">
            السكور المرجح: <b>{score}/10</b> | الثقة: <b>{conf}%</b>
          </p>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
        <div class="nogo-box">
          <h2 style="color:#ff4d4d;text-align:center">🔴 NO-GO</h2>
          <p style="text-align:center;font-size:1.15em">
            السكور المرجح: <b>{score}/10</b> | الثقة: <b>{conf}%</b>
          </p>
        </div>""", unsafe_allow_html=True)

    if summary["red_flags"]:
        st.error("🚩 التحذيرات: " + " | ".join(summary["red_flags"]))

    # مؤشرات
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("⭐ أفضل ساعة",      best["time"])
    m2.metric("🌊 تيار جانبي",     f"{summary['avg_longshore']} كم/س")
    m3.metric("💨 Écume",           f"{summary['ecume_hours']} ساعة")
    m4.metric("🌙 القمر",           f"{int(summary['moon']*100)}%")
    m5.metric("⚖️ الرصاص",          best["lead"])

    st.divider()

    # هوية السبوت
    st.subheader("📍 هوية السبوت")
    st.markdown(f"""
    <div class="spot-card">
      <b>{R['loc_name']}</b><br>
      🧭 اتجاه البحر: {summary['coast']['shoreline_normal']}° |
      🏖️ {summary['coast']['coast_type']}<br>
      📊 انكشاف: {int(summary['coast']['coast_exposure']*100)}% |
      🌊 إغلاق الخليج: {int(summary['coast']['bay_factor']*100)}%
    </div>
    """, unsafe_allow_html=True)

    # إرث 48 ساعة
    st.subheader("📊 إرث الـ48 ساعة")
    q1, q2, q3, q4, q5 = st.columns(5)
    q1.metric("موج الرياح",     f"{summary['past']['avg_wwh']} م")
    q2.metric("تردد موج رياح", f"{summary['past']['avg_wwp']} ث")
    q3.metric("Swell",          f"{summary['past']['avg_swh']} م")
    q4.metric("تردد Swell",    f"{summary['past']['avg_swp']} ث")
    q5.metric("الحالة",         "🔴 مدرر" if summary["past"]["is_dirty"] else "🟢 نظيف")

    st.divider()

    # التقرير الحتمي
    st.subheader("🧮 التقرير الحتمي (المحرك الحسابي)")
    st.markdown(R["det_report"])

    st.divider()

    # تقرير Gemini
    st.subheader("🧠 تقرير Gemini (شرح لنفس الداتا)")
    if R["ai_err"]:
        st.warning(f"تعذّر إنشاء التقرير: {R['ai_err']}")
    elif R["ai_text"]:
        st.markdown(R["ai_text"])
    else:
        st.info("لا يوجد تقرير Gemini.")

    st.divider()

    # جدول ساعي
    st.subheader("📊 الجدول الزمني ساعة بساعة")
    df = pd.DataFrame(summary["rows"])[[
        "time","score","wind_type","wind_kmh","gust_kmh","ws_eff",
        "wave_h","wave_p","wave_impact","ww_h","ww_p",
        "sw_h","sw_p","sw_impact",
        "longshore_kmh","lead","rip","debris","ecume",
        "sst_c","rain_mm","vis_km"
    ]].copy()

    df.columns = [
        "الوقت","السكور","نوع الريح","ريح","هبات","ريح فعلية",
        "موج","تردد م","زاوية موج","موج ريح","تردد م.ر",
        "Swell","تردد Sw","زاوية Sw",
        "تيار جانبي","الرصاص","Rip","الأعشاب","Écume",
        "حرارة°","مطر","رؤية كم"
    ]

    def score_style(v):
        if v >= 7:   return "background:#0a3d0a;color:#00ff00"
        if v >= 5:   return "background:#3d3d0a;color:#ffff00"
        if v >= 4:   return "background:#3d2e0a;color:#ffa500"
        return "background:#3d0a0a;color:#ff4d4d"

    def wind_style(v):
        v = str(v)
        if "وش 🟢"       in v: return "color:#00ff00;font-weight:bold"
        if "بر 🔵"       in v: return "color:#66b2ff;font-weight:bold"
        if "جانبي-وش 🟡" in v: return "color:#ffff00"
        return "color:#ffa500"

    styled = (
        df.style
        .applymap(score_style, subset=["السكور"])
        .applymap(wind_style,  subset=["نوع الريح"])
    )
    st.dataframe(styled, use_container_width=True, hide_index=True)

    # بدائل
    if R["alternatives"]:
        st.divider()
        st.subheader("💡 بدائل أقوى من الموقع الحالي")
        for alt in R["alternatives"][:3]:
            dist = haversine_km(
                st.session_state.lat, st.session_state.lon,
                alt["lat"], alt["lon"]
            )
            diff = round(alt["score"] - score, 1)
            st.markdown(f"""
            <div class="spot-card">
              <b>{alt['name']}</b> — {alt['region']}<br>
              🎯 {alt['score']}/10
              <span style="color:#00ff00">(+{diff})</span> |
              📏 {dist} كم
            </div>
            """, unsafe_allow_html=True)

            if st.button(f"⚓ انتقل إلى {alt['name']}",
                         key=f"alt_{alt['name']}", use_container_width=True):
                st.session_state.lat         = alt["lat"]
                st.session_state.lon         = alt["lon"]
                st.session_state.map_center  = [alt["lat"], alt["lon"]]
                st.session_state.deep_result = None
                st.rerun()

    with st.expander("🔧 Payload المرسل إلى Gemini"):
        st.code(R["payload_json"], language="json")

st.caption("© Tunisia Fishing Advisor v10.5 | Physics First — AI Explains")
