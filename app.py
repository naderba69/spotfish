import os
import json
import math
import requests
import streamlit as st
import folium
from folium.plugins import LocateControl
import pandas as pd
from streamlit_folium import st_folium
from datetime import datetime, timedelta, date
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed
import time

# ══════════════════════════════════════════════════════════════
# 1. CONFIG
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="مستشار الصيد AI | v10.0",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    body {
        direction: rtl;
        font-family: 'Noto Sans Arabic', 'Segoe UI', sans-serif;
    }
    .block-container {
        padding-top: 0.5rem;
        padding-bottom: 2rem;
    }
    .go-box {
        background: linear-gradient(135deg, #0a3d0a 0%, #0d520d 100%);
        padding: 24px;
        border-radius: 12px;
        border: 3px solid #00ff00;
        box-shadow: 0 4px 15px rgba(0,255,0,0.3);
        margin: 16px 0;
    }
    .nogo-box {
        background: linear-gradient(135deg, #3d0a0a 0%, #520d0d 100%);
        padding: 24px;
        border-radius: 12px;
        border: 3px solid #ff0000;
        box-shadow: 0 4px 15px rgba(255,0,0,0.3);
        margin: 16px 0;
    }
    .warn-box {
        background: linear-gradient(135deg, #3d2e0a 0%, #52400d 100%);
        padding: 24px;
        border-radius: 12px;
        border: 3px solid #ffa500;
        box-shadow: 0 4px 15px rgba(255,165,0,0.3);
        margin: 16px 0;
    }
    .top-spot {
        background: #0a3d0a;
        padding: 16px;
        border-radius: 10px;
        border: 2px solid #00ff00;
        margin: 10px 0;
        transition: all 0.3s ease;
    }
    .top-spot:hover {
        transform: translateX(-5px);
        box-shadow: 0 4px 12px rgba(0,255,0,0.4);
    }
    .spot-card {
        background: #0a1a2e;
        padding: 14px;
        border-radius: 8px;
        border: 1px solid #1f77b4;
        margin-bottom: 10px;
    }
    .factor-card {
        background: #1a1a2e;
        padding: 12px;
        border-radius: 8px;
        border-left: 4px solid #1f77b4;
        margin: 8px 0;
    }
    .crosshair {
        position: absolute;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        width: 60px;
        height: 60px;
        z-index: 1000;
        pointer-events: none;
    }
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        font-weight: bold;
        font-size: 16px;
    }
</style>
""", unsafe_allow_html=True)

st.title("🎣 مستشار الصيد AI | v10.0 ULTIMATE")
st.markdown("**الأنكر الثابت + Deep Scan + الكلمة الأولى والأخيرة**")

# ══════════════════════════════════════════════════════════════
# 2. SESSION STATE
# ══════════════════════════════════════════════════════════════
if "lat" not in st.session_state:
    st.session_state.lat = 36.80
if "lon" not in st.session_state:
    st.session_state.lon = 10.60
if "day_offset" not in st.session_state:
    st.session_state.day_offset = 1
if "scan_results" not in st.session_state:
    st.session_state.scan_results = None
if "deep_result" not in st.session_state:
    st.session_state.deep_result = None
if "favorites" not in st.session_state:
    st.session_state.favorites = []
if "map_center" not in st.session_state:
    st.session_state.map_center = [36.80, 10.60]

# ══════════════════════════════════════════════════════════════
# 3. SPOTS DATABASE
# ══════════════════════════════════════════════════════════════
SPOTS_DATABASE = [
    {"name": "رأس الدرك", "lat": 37.2742, "lon": 9.8739, "region": "بنزرت", "type": "open_coast"},
    {"name": "الهوارية", "lat": 37.0539, "lon": 11.0581, "region": "نابل", "type": "rocky_open"},
    {"name": "قليبية", "lat": 36.8333, "lon": 11.1000, "region": "نابل", "type": "open_coast"},
    {"name": "غار الملح", "lat": 37.1728, "lon": 10.0872, "region": "بنزرت", "type": "bay"},
    {"name": "رفراف الشاطئ", "lat": 37.1889, "lon": 10.1833, "region": "بنزرت", "type": "open_coast"},
    {"name": "الحمامات", "lat": 36.4000, "lon": 10.6167, "region": "نابل", "type": "urban_beach"},
    {"name": "سوسة بوجعفر", "lat": 35.8256, "lon": 10.6369, "region": "سوسة", "type": "urban_beach"},
    {"name": "المنستير الشاطئ", "lat": 35.7672, "lon": 10.8111, "region": "المنستير", "type": "urban"},
    {"name": "المهدية الكورنيش", "lat": 35.5047, "lon": 11.0622, "region": "المهدية", "type": "open_coast"},
    {"name": "صفاقس رأس الطابية", "lat": 34.7333, "lon": 10.7633, "region": "صفاقس", "type": "mixed"},
    {"name": "قرقنة", "lat": 34.7333, "lon": 11.1167, "region": "صفاقس", "type": "island"},
    {"name": "قابس الشاطئ", "lat": 33.8815, "lon": 10.0982, "region": "قابس", "type": "mixed"},
    {"name": "جرجيس", "lat": 33.5042, "lon": 10.8681, "region": "مدنين", "type": "open_coast"},
    {"name": "جربة أجيم", "lat": 33.7167, "lon": 10.7667, "region": "جربة", "type": "bay"},
    {"name": "بنزرت المرسى", "lat": 37.2744, "lon": 9.8628, "region": "بنزرت", "type": "harbor"},
    {"name": "طبرقة", "lat": 36.9544, "lon": 8.7578, "region": "جندوبة", "type": "rocky_open"},
    {"name": "المكنين", "lat": 35.6333, "lon": 10.6000, "region": "المنستير", "type": "beach"},
    {"name": "قصر هلال", "lat": 35.6500, "lon": 10.7000, "region": "المنستير", "type": "beach"},
]

# ══════════════════════════════════════════════════════════════
# 4. MATH HELPERS
# ══════════════════════════════════════════════════════════════
def haversine_km(lat1, lon1, lat2, lon2):
    """حساب المسافة بين نقطتين بالكيلومترات"""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 + 
         math.cos(math.radians(lat1)) * 
         math.cos(math.radians(lat2)) * 
         math.sin(dlon/2)**2)
    c = 2 * math.asin(math.sqrt(a))
    return round(R * c, 1)

def destination_point(lat1, lon1, bearing_deg, distance_km):
    """حساب نقطة على مسافة واتجاه معينين"""
    R = 6371.0
    bearing = math.radians(bearing_deg)
    φ1 = math.radians(lat1)
    λ1 = math.radians(lon1)
    
    φ2 = math.asin(
        math.sin(φ1) * math.cos(distance_km/R) + 
        math.cos(φ1) * math.sin(distance_km/R) * math.cos(bearing)
    )
    
    λ2 = λ1 + math.atan2(
        math.sin(bearing) * math.sin(distance_km/R) * math.cos(φ1),
        math.cos(distance_km/R) - math.sin(φ1) * math.sin(φ2)
    )
    
    return math.degrees(φ2), math.degrees(λ2)

def circular_mean(angles_deg):
    """المتوسط الدائري للزوايا"""
    if not angles_deg:
        return 0.0
    sin_sum = sum(math.sin(math.radians(a)) for a in angles_deg)
    cos_sum = sum(math.cos(math.radians(a)) for a in angles_deg)
    mean_angle = math.degrees(math.atan2(sin_sum, cos_sum))
    return mean_angle % 360

def angle_diff_180(a, b):
    """الفرق بين زاويتين (0-180)"""
    diff = abs(a - b) % 360
    return diff if diff <= 180 else 360 - diff

def safe_avg(lst):
    """متوسط آمن"""
    return sum(lst) / len(lst) if lst else 0.0

def moon_phase_factor(d: date) -> float:
    """عامل القمر (0.0 = محاق، 1.0 = بدر)"""
    known_new_moon = date(2024, 1, 11)
    delta_days = (d - known_new_moon).days
    phase_in_cycle = delta_days % 29.53
    factor = 0.5 + 0.5 * abs(math.cos(2 * math.pi * phase_in_cycle / 29.53))
    return round(factor, 3)

# ══════════════════════════════════════════════════════════════
# 5. API CALLS WITH FULL CACHING
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def analyze_coast_geometry(lat: float, lon: float):
    """تحليل هندسة الساحل الكامل مع bay_factor"""
    radius_km = 3.0
    bearings = list(range(0, 360, 30))  # 12 نقطة
    points = []
    
    for bearing in bearings:
        lat2, lon2 = destination_point(lat, lon, bearing, radius_km)
        points.append({
            "lat": round(lat2, 4),
            "lon": round(lon2, 4),
            "bearing": bearing
        })
    
    lats_str = ",".join(str(p["lat"]) for p in points)
    lons_str = ",".join(str(p["lon"]) for p in points)
    
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/elevation",
            params={"latitude": lats_str, "longitude": lons_str},
            timeout=15
        )
        response.raise_for_status()
        elevations = response.json().get("elevation", [])
    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 429:
            return None, "rate_limit"
        return None, f"HTTP error: {e}"
    except Exception as e:
        return None, f"خطأ: {e}"
    
    if len(elevations) != len(points):
        return None, "بيانات ارتفاع غير مكتملة"
    
    sea_bearings = [
        p["bearing"] for p, elev in zip(points, elevations)
        if elev is not None and elev <= 0.5
    ]
    
    if not sea_bearings:
        return None, "inland"
    
    if len(sea_bearings) < 2:
        return None, "موقع غير واضح"
    
    shoreline_normal = circular_mean(sea_bearings)
    coast_exposure = round(len(sea_bearings) / len(points), 3)
    
    # حساب bay_factor (معامل انغلاق الخليج)
    if len(sea_bearings) >= 2:
        avg_sin = sum(math.sin(math.radians(b)) for b in sea_bearings) / len(sea_bearings)
        avg_cos = sum(math.cos(math.radians(b)) for b in sea_bearings) / len(sea_bearings)
        R_bar = min(math.sqrt(avg_sin**2 + avg_cos**2), 0.9999)
        circular_variance = -2.0 * math.log(R_bar)
        bay_factor = round(max(0.0, 1.0 - math.degrees(math.sqrt(circular_variance)) / 90.0), 3)
    else:
        bay_factor = 0.5
    
    # تصنيف نوع الساحل
    if coast_exposure < 0.05:
        coast_type = "🔴 بحيرة / سبخة"
    elif coast_exposure > 0.65:
        coast_type = "🌊 رأس بحري / ساحل مفتوح"
    elif coast_exposure > 0.35:
        if bay_factor > 0.55:
            coast_type = "🏖️ خليج شبه مغلق"
        else:
            coast_type = "🏖️ ساحل عادي"
    else:
        coast_type = "⚓ خليج مغلق / مرسى"
    
    return {
        "shoreline_normal": round(shoreline_normal, 1),
        "coast_exposure": coast_exposure,
        "bay_factor": bay_factor,
        "coast_type": coast_type,
    }, None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_marine_data(lat: float, lon: float):
    """جلب بيانات البحر"""
    try:
        response = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
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
            headers={"User-Agent": "TunisiaFishingAI/10.0"},
            timeout=25
        )
        response.raise_for_status()
        data = response.json()
        if "error" in data:
            return None, data.get("reason", "Marine API error")
        return data, None
    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 429:
            return None, "rate_limit"
        return None, f"Marine HTTP {e.response.status_code if e.response else 'error'}"
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_weather_data(lat: float, lon: float):
    """جلب بيانات الطقس"""
    try:
        response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "hourly": (
                    "wind_speed_10m,wind_direction_10m,"
                    "wind_gusts_10m,precipitation,visibility"
                ),
                "past_days": 2,
                "forecast_days": 3,
                "timezone": "auto"
            },
            headers={"User-Agent": "TunisiaFishingAI/10.0"},
            timeout=25
        )
        response.raise_for_status()
        return response.json(), None
    except requests.exceptions.HTTPError as e:
        if e.response and e.response.status_code == 429:
            return None, "rate_limit"
        return None, f"Weather HTTP {e.response.status_code if e.response else 'error'}"
    except Exception as e:
        return None, str(e)

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_location_name(lat: float, lon: float) -> str:
    """جلب اسم المكان"""
    try:
        response = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat,
                "lon": lon,
                "format": "json",
                "accept-language": "ar",
                "zoom": 14
            },
            headers={"User-Agent": "TunisiaFishingAI/10.0"},
            timeout=8
        )
        data = response.json()
        address = data.get("address", {})
        return (
            address.get("hamlet") or
            address.get("village") or
            address.get("suburb") or
            address.get("town") or
            address.get("city") or
            address.get("state") or
            "ساحل تونسي"
        )
    except:
        return "منطقة ساحلية"

# ══════════════════════════════════════════════════════════════
# 6. DATA EXTRACTION HELPERS
# ══════════════════════════════════════════════════════════════
def build_time_lookup(data):
    """بناء فهرس للوصول السريع للبيانات"""
    if not data or "hourly" not in data:
        return {}
    times = data["hourly"].get("time", [])
    return {t: i for i, t in enumerate(times)}

def get_value(data, lookup, key, timestamp, default=0.0):
    """استخراج قيمة من البيانات بشكل آمن"""
    if not data or not lookup:
        return default
    idx = lookup.get(timestamp)
    if idx is None:
        return default
    arr = data["hourly"].get(key, [])
    if idx >= len(arr):
        return default
    val = arr[idx]
    if val is None:
        return default
    try:
        return float(val)
    except:
        return default

# ══════════════════════════════════════════════════════════════
# 7. WIND CLASSIFICATION
# ══════════════════════════════════════════════════════════════
def classify_wind(wind_dir_going, shoreline_normal, wind_speed_eff):
    """تصنيف الريح حسب الاتجاه والتأثير"""
    if shoreline_normal is None:
        return "غير محدد", 90.0, 0.0
    
    diff = angle_diff_180(wind_dir_going, shoreline_normal)
    
    if diff <= 45:
        label = "ريح وش 🟢"
        if 8 <= wind_speed_eff <= 25:
            bonus = +1.5
        elif wind_speed_eff < 8:
            bonus = +0.5
        else:
            bonus = -0.5
    elif diff >= 135:
        label = "ريح بر 🔵"
        if wind_speed_eff <= 15:
            bonus = +1.0
        elif wind_speed_eff <= 25:
            bonus = +0.3
        else:
            bonus = -1.5
    elif diff <= 90:
        label = "ريح جانبي-وش 🟡"
        if wind_speed_eff <= 20:
            bonus = -0.5
        else:
            bonus = -1.5
    else:
        label = "ريح جانبي-بر 🟠"
        if wind_speed_eff <= 20:
            bonus = -0.8
        else:
            bonus = -2.5
    
    return label, round(diff, 1), round(bonus, 2)

# ══════════════════════════════════════════════════════════════
# 8. PAST 48H ANALYSIS
# ══════════════════════════════════════════════════════════════
def analyze_past_48h(marine_data, weather_data, target_date):
    """تحليل الـ48 ساعة السابقة"""
    if not marine_data or not weather_data:
        return {
            "avg_wwh": 0.0, "avg_wwp": 0.0,
            "avg_swh": 0.0, "avg_swp": 0.0,
            "is_dirty": False
        }
    
    time_array = weather_data["hourly"].get("time", [])
    if not time_array:
        return {
            "avg_wwh": 0.0, "avg_wwp": 0.0,
            "avg_swh": 0.0, "avg_swp": 0.0,
            "is_dirty": False
        }
    
    target_start = datetime.combine(target_date, datetime.min.time())
    past_start = target_start - timedelta(hours=48)
    
    lookup = build_time_lookup(marine_data)
    
    past_wwh, past_wwp = [], []
    past_swh, past_swp = [], []
    
    for i, ts in enumerate(time_array):
        try:
            dt = datetime.fromisoformat(ts)
        except:
            continue
        
        if not (past_start <= dt < target_start):
            continue
        
        wwh = get_value(marine_data, lookup, "wind_wave_height", ts)
        wwp = get_value(marine_data, lookup, "wind_wave_period", ts)
        swh = get_value(marine_data, lookup, "swell_wave_height", ts)
        swp = get_value(marine_data, lookup, "swell_wave_period", ts)
        
        if wwh > 0:
            past_wwh.append(wwh)
        if wwp > 0:
            past_wwp.append(wwp)
        if swh > 0:
            past_swh.append(swh)
        if swp > 0:
            past_swp.append(swp)
    
    avg_wwh = safe_avg(past_wwh)
    avg_wwp = safe_avg(past_wwp)
    avg_swh = safe_avg(past_swh)
    avg_swp = safe_avg(past_swp)
    
    is_dirty = (avg_wwh > 1.2) and (avg_wwp < 6.0)
    
    return {
        "avg_wwh": round(avg_wwh, 2),
        "avg_wwp": round(avg_wwp, 1),
        "avg_swh": round(avg_swh, 2),
        "avg_swp": round(avg_swp, 1),
        "is_dirty": is_dirty
    }

# ══════════════════════════════════════════════════════════════
# 9. DEEP SCORING ENGINE (FULL PHYSICS)
# ══════════════════════════════════════════════════════════════
def compute_deep_scores(marine_data, weather_data, coast_info, target_date, past_48h):
    """المحرك الفيزيائي الكامل للتقييم"""
    
    if not weather_data or "hourly" not in weather_data:
        return None, None, "بيانات الطقس مفقودة"
    
    time_array = weather_data["hourly"]["time"]
    wind_speed = weather_data["hourly"].get("wind_speed_10m", [])
    wind_dir = weather_data["hourly"].get("wind_direction_10m", [])
    wind_gust = weather_data["hourly"].get("wind_gusts_10m", [])
    precip = weather_data["hourly"].get("precipitation", [])
    visibility = weather_data["hourly"].get("visibility", [])
    
    time_dt = []
    for t in time_array:
        try:
            time_dt.append(datetime.fromisoformat(t))
        except:
            time_dt.append(None)
    
    valid_indices = [(i, t) for i, t in enumerate(time_dt) if t]
    if not valid_indices:
        return None, None, "لا توجد أوقات صالحة"
    
    target_indices = [i for i, t in valid_indices if t.date() == target_date]
    if not target_indices:
        return None, None, f"لا توجد بيانات لـ {target_date}"
    
    sn = coast_info.get("shoreline_normal")
    bay_factor = coast_info.get("bay_factor", 0.0)
    coast_exposure = coast_info.get("coast_exposure", 1.0)
    coast_type = coast_info.get("coast_type", "ساحل عادي")
    
    moon_f = moon_phase_factor(target_date)
    is_dirty = past_48h.get("is_dirty", False)
    avg_wwh = past_48h.get("avg_wwh", 0.0)
    avg_wwp = past_48h.get("avg_wwp", 0.0)
    avg_swh = past_48h.get("avg_swh", 0.0)
    avg_swp = past_48h.get("avg_swp", 0.0)
    
    lookup = build_time_lookup(marine_data)
    
    hourly_scores = []
    
    for i in target_indices:
        score = 10.0
        ts = time_array[i]
        t_obj = time_dt[i]
        
        # Marine data
        wd = get_value(marine_data, lookup, "wave_direction", ts)
        wp = get_value(marine_data, lookup, "wave_period", ts)
        
        wwh = get_value(marine_data, lookup, "wind_wave_height", ts)
        wwd = get_value(marine_data, lookup, "wind_wave_direction", ts)
        wwp = get_value(marine_data, lookup, "wind_wave_period", ts)
        
        swh = get_value(marine_data, lookup, "swell_wave_height", ts)
        swd = get_value(marine_data, lookup, "swell_wave_direction", ts)
        swp = get_value(marine_data, lookup, "swell_wave_period", ts)
        
        sst = get_value(marine_data, lookup, "sea_surface_temperature", ts, 18.0)
        
        # Weather data
        def safe_w(arr, idx):
            if idx < len(arr) and arr[idx] is not None:
                try:
                    return float(arr[idx])
                except:
                    return 0.0
            return 0.0
        
        ws = safe_w(wind_speed, i)
        wd_raw = safe_w(wind_dir, i)
        gust = safe_w(wind_gust, i)
        rain = safe_w(precip, i)
        vis = safe_w(visibility, i) if visibility else 24140.0
        if vis <= 0:
            vis = 24140.0
        
        # Effective wind
        ws_eff = max(ws, gust * 0.7)
        wind_dir_going = (wd_raw + 180) % 360
        
        wind_label, wind_shore_angle, wind_bonus = classify_wind(
            wind_dir_going, sn, ws_eff
        )
        
        # Wave processing with bay factor
        wwh_eff = wwh * (1.0 - bay_factor * 0.50)
        swh_eff = swh * (1.0 - bay_factor * 0.30)
        wh_total = wwh_eff + swh_eff
        
        # Wave impact angles
        _sn = sn if sn is not None else 0.0
        wave_impact = angle_diff_180(wd, _sn)
        ww_impact = angle_diff_180(wwd, _sn)
        sw_impact = angle_diff_180(swd, _sn)
        
        # Longshore current (full physics)
        def longshore_velocity(H_b, impact_angle):
            if H_b <= 0.05 or impact_angle <= 10:
                return 0.0
            theta = math.radians(impact_angle)
            g = 9.81
            V_ls = 1.17 * math.sqrt(g * H_b) * math.sin(theta) * math.cos(theta)
            return V_ls
        
        v_ww = longshore_velocity(wwh_eff * 1.4, ww_impact)
        v_sw = longshore_velocity(swh_eff * 1.2, sw_impact)
        v_total = v_ww + v_sw + (ws_eff * 0.015)
        v_kmh = v_total * 3.6
        
        # Drag force and lead recommendation
        rho_water = 1025
        A_lead = 0.0025
        Cd = 1.5
        F_drag = 0.5 * rho_water * Cd * A_lead * (v_total ** 2)
        
        if F_drag > 2.5:
            lead_type = "شواكيش سبايك"
            lead_weight = 140
        elif F_drag > 1.0:
            lead_type = "هرمي"
            lead_weight = 120
        else:
            lead_type = "زيتوني"
            lead_weight = 100
        
        # Rip current risk
        if wh_total > 1.2 and wp > 8 and 20 <= wave_impact <= 60:
            rip_risk = "عالي جداً ⚠️"
        elif wh_total > 1.0 and wp > 6 and wave_impact < 30:
            rip_risk = "متوسط"
        else:
            rip_risk = "منخفض"
        
        # Swell cleaning detection
        is_clean = (swp >= 8.0 and sw_impact < 45 and swh_eff <= 1.2)
        
        if is_clean and is_dirty:
            debris_status = "Swell ينظف 🟢"
        elif is_dirty and wwp < 6.0:
            debris_status = "مدرر — موج ريح قصير 🔴"
        else:
            debris_status = "نظيف 🟢"
        
        # Écume detection
        if "وش" in wind_label and 0.4 <= wh_total <= 1.4 and wave_impact < 50 and ws >= 8:
            ecume = "نعم ✅"
        else:
            ecume = "لا"
        
        # SCORING LOGIC
        # Wave height
        if wh_total < 0.3:
            score -= 3.0
        elif wh_total > 2.5:
            score -= 2.0
        
        # Debris penalty
        if "مدرر" in debris_status:
            score -= 4.5
        
        # Longshore current penalty
        if v_kmh > 1.5:
            score -= 4.0
        elif v_kmh > 0.8:
            score -= 2.0
        
        # Wind strength
        if ws_eff > 65:
            score -= 7.0
        elif ws_eff > 55:
            score -= 5.0
        elif ws_eff > 42:
            score -= 3.0
        elif ws_eff > 32:
            score -= 1.5
        elif ws_eff > 26:
            score -= 0.5
        
        # Rain
        if rain > 5.0:
            score -= 2.0
        elif rain > 1.0:
            score -= 0.5
        
        # Visibility
        if vis < 1000:
            score -= 3.0
        elif vis < 3000:
            score -= 1.0
        
        # Wind bonus
        score += wind_bonus
        
        # Écume bonus
        if ecume == "نعم ✅":
            score += 1.5
        
        # Swell bonus
        if swh_eff > 0.3 and wwh_eff < 0.3 and swp > 9.0:
            score += 1.5
        
        # Cleaning bonus
        if is_clean and is_dirty:
            score += 2.0
        
        # Moon bonus
        score += max(0.0, (moon_f - 0.55) * 1.5)
        
        # Coast type adjustments
        if coast_exposure > 0.7 and wh_total > 1.5:
            score -= 1.5
        if bay_factor > 0.8 and wh_total < 0.5:
            score -= 1.0
        
        # SST
        if sst < 15.0:
            score -= 2.0
        elif sst < 17.0:
            score -= 1.0
        elif 19 <= sst <= 24:
            score += 0.5
        
        score = max(0.0, min(10.0, score))
        
        hourly_scores.append({
            "time": ts,
            "hour": t_obj.hour,
            "score": round(score, 1),
            "wh_total": round(wh_total, 2),
            "wp": round(wp, 1),
            "ww_h": round(wwh_eff, 2),
            "ww_p": round(wwp, 1),
            "ww_impact": round(ww_impact, 1),
            "sw_h": round(swh_eff, 2),
            "sw_p": round(swp, 1),
            "sw_impact": round(sw_impact, 1),
            "wind_kmh": round(ws, 1),
            "gust_kmh": round(gust, 1),
            "ws_eff": round(ws_eff, 1),
            "wind_dir": round(wd_raw, 0),
            "wind_type": wind_label,
            "wind_shore_angle": wind_shore_angle,
            "longshore_kmh": round(v_kmh, 2),
            "drag_n": round(F_drag, 4),
            "lead_type": lead_type,
            "lead_weight": lead_weight,
            "rip_risk": rip_risk,
            "debris": debris_status,
            "ecume": ecume,
            "sst_c": round(sst, 1),
            "rain_mm": round(rain, 1),
            "vis_km": round(vis / 1000, 1),
        })
    
    # Context
    context = {
        "avg_wwh": avg_wwh,
        "avg_wwp": avg_wwp,
        "avg_swh": avg_swh,
        "avg_swp": avg_swp,
        "is_dirty": is_dirty,
        "tomorrow": str(target_date),
        "moon_f": moon_f,
        "bay_factor": bay_factor,
        "coast_exposure": coast_exposure,
        "coast_type": coast_type,
        "sn": sn,
    }
    
    return hourly_scores, context, None

def weighted_average_score(hourly_data):
    """حساب السكور المُرجَّح (الساعات الذهبية لها وزن أعلى)"""
    prime_hours = set(range(17, 24)) | set(range(4, 9))
    total_weighted = 0.0
    total_weight = 0.0
    
    for h in hourly_data:
        weight = 2.5 if h["hour"] in prime_hours else 1.0
        total_weighted += h["score"] * weight
        total_weight += weight
    
    return total_weighted / total_weight if total_weight else 0.0

# ══════════════════════════════════════════════════════════════
# 10. QUICK SCAN FOR MULTIPLE SPOTS
# ══════════════════════════════════════════════════════════════
def quick_score_spot(lat, lon, target_date):
    """فحص سريع لسبوت واحد (للترتيب الأولي)"""
    coast, err = analyze_coast_geometry(lat, lon)
    if err or not coast:
        return None
    
    if "بحيرة" in coast.get("coast_type", ""):
        return None
    
    marine, err1 = fetch_marine_data(lat, lon)
    weather, err2 = fetch_weather_data(lat, lon)
    
    if err1 or err2 or not marine or not weather:
        return None
    
    times = weather["hourly"].get("time", [])
    if not times:
        return None
    
    scores = []
    lookup = build_time_lookup(marine)
    sn = coast["shoreline_normal"]
    
    for i, ts in enumerate(times):
        try:
            dt = datetime.fromisoformat(ts)
        except:
            continue
        
        if dt.date() != target_date:
            continue
        
        score = 10.0
        
        ws = weather["hourly"]["wind_speed_10m"][i] if i < len(weather["hourly"]["wind_speed_10m"]) else 0
        wdir = weather["hourly"]["wind_direction_10m"][i] if i < len(weather["hourly"]["wind_direction_10m"]) else 0
        gust = weather["hourly"]["wind_gusts_10m"][i] if i < len(weather["hourly"]["wind_gusts_10m"]) else 0
        
        wh = get_value(marine, lookup, "wave_height", ts)
        sst = get_value(marine, lookup, "sea_surface_temperature", ts, 18.0)
        
        ws_eff = max(ws or 0, (gust or 0) * 0.7)
        wdir_going = (wdir + 180) % 360 if wdir else 0
        diff = angle_diff_180(wdir_going, sn)
        
        # Simple wind scoring
        if diff <= 45:
            score += 1.2
        elif diff >= 135:
            score += 0.6
        else:
            score -= 1.0
        
        # Wave
        if wh < 0.25:
            score -= 3.0
        elif wh > 1.8:
            score -= 1.5
        
        # Wind strength
        if ws_eff > 50:
            score -= 5.0
        elif ws_eff > 35:
            score -= 2.0
        
        # SST
        if sst < 15:
            score -= 2.0
        elif 19 <= sst <= 24:
            score += 0.5
        
        score = max(0, min(10, score))
        
        weight = 2.5 if dt.hour in set(range(17, 24)) | set(range(4, 9)) else 1.0
        scores.append((score, weight))
    
    if not scores:
        return None
    
    total = sum(s * w for s, w in scores)
    weights = sum(w for _, w in scores)
    return round(total / weights, 2) if weights else 0.0

def scan_all_spots_parallel(spots, target_date, max_workers=3):
    """فحص جميع السبوتات بشكل متوازي"""
    results = []
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_spot = {
            executor.submit(quick_score_spot, spot["lat"], spot["lon"], target_date): spot
            for spot in spots
        }
        
        for future in as_completed(future_to_spot):
            spot = future_to_spot[future]
            try:
                score = future.result()
                if score is not None:
                    results.append({
                        "name": spot["name"],
                        "region": spot["region"],
                        "lat": spot["lat"],
                        "lon": spot["lon"],
                        "score": score,
                    })
            except:
                pass
    
    results.sort(key=lambda x: x["score"], reverse=True)
    return results

# ══════════════════════════════════════════════════════════════
# 11. GEMINI REPORT
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=1800, show_spinner=False)
def generate_detailed_report(hourly_data, context, location_name, weighted_score):
    """تقرير مفصل بواسطة Gemini"""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, "GEMINI_API_KEY مفقود من متغيرات البيئة"
    
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            generation_config=genai.GenerationConfig(
                temperature=0.05,
                top_p=0.1,
                max_output_tokens=3500
            )
        )
        
        prompt = f"""أنت خبير صيد تونسي محترف جداً، تتحدث بالدارجة التونسية الواضحة.

📍 الموقع: {location_name}
🧭 اتجاه البحر: {context['sn']}°
🏖️ نوع الساحل: {context['coast_type']}
📊 انكشاف البحر: {int(context['coast_exposure']*100)}%
🌊 إغلاق الخليج: {int(context['bay_factor']*100)}%

📅 التاريخ: {context['tomorrow']}
🌙 القمر: {int(context['moon_f']*100)}%

📊 الـ48 ساعة السابقة:
- موج الرياح: {context['avg_wwh']}م / {context['avg_wwp']}ث
- Swell: {context['avg_swh']}م / {context['avg_swp']}ث
- الحالة: {'🔴 مدرر (بحر متعكر)' if context['is_dirty'] else '🟢 نظيف'}

🎯 السكور النهائي: {round(weighted_score, 2)}/10

البيانات ساعة بساعة:
{json.dumps(hourly_data, ensure_ascii=False, indent=1)}

اكتب تقريراً تكتيكياً مفصلاً بالدارجة التونسية، يحتوي على:

## 1️⃣ هوية السبوت (جملة واحدة)

## 2️⃣ حالة البحر (إرث الـ48 ساعة)
- هل البحر مدرر ولا نظيف؟
- شنوة تأثير موج الرياح والـ Swell؟

## 3️⃣ تحليل الريح
- أنواع الريح ساعة بساعة (وش/بر/جانبي)
- أحسن ساعات للريح

## 4️⃣ الفيزياء والتكتيك
- التيار الجانبي (Longshore) وخطورتو
- الرصاص الموصى به والوزن
- Écume (رغوة البحر) - متى ستظهر؟
- تيار الساحب (Rip Current)

## 5️⃣ النوافذ البيولوجية
- القمر وتأثيره
- حرارة البحر
- أحسن ساعات للصيد

## 6️⃣ القرار النهائي ({round(weighted_score, 2)}/10)

إذا السكور ≥ 6.0:
**✅ GO**
▸ الرصاص: [النوع] | الوزن: [غرام]
▸ الطعم المُوصى: [ساردين/دود/...]
▸ المسافة: [قريب/متوسط/بعيد]
▸ وقت البدء: [الساعة]
▸ وقت الإنهاء: [الساعة]

إذا السكور < 6.0:
**🔴 NO-GO**
▸ السبب الرئيسي: [...]
▸ التوصية: غيّر السبوت أو استنى يوم آخر

استخدم مصطلحات تونسية واضحة. كن مباشراً وحاسماً."""
        
        response = model.generate_content(prompt)
        return response.text, None
    except Exception as e:
        return None, f"خطأ Gemini: {e}"

# ══════════════════════════════════════════════════════════════
# 12. UI — MAIN INTERFACE
# ══════════════════════════════════════════════════════════════

# Day selector
st.markdown("### 📅 1) اختر اليوم")
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🔵 اليوم", use_container_width=True):
        st.session_state.day_offset = 0
        st.rerun()
with col2:
    if st.button("🟢 غداً", use_container_width=True):
        st.session_state.day_offset = 1
        st.rerun()
with col3:
    if st.button("🟡 بعد غد", use_container_width=True):
        st.session_state.day_offset = 2
        st.rerun()

target_date = date.today() + timedelta(days=st.session_state.day_offset)
day_names = {0: "اليوم", 1: "غداً", 2: "بعد غد"}
st.info(f"📆 **{day_names[st.session_state.day_offset]}** — {target_date.strftime('%Y-%m-%d')}")

st.divider()

# Map + Scout section
col_map, col_scout = st.columns([2, 1])

with col_map:
    st.markdown("### 🗺️ 2) حرّك الخريطة لتثبيت السبوت تحت الأنكر الأحمر")
    
    # Create map with draggable behavior
    m = folium.Map(
        location=st.session_state.map_center,
        zoom_start=9,
        tiles="CartoDB dark_matter"
    )
    
    # Add famous spots as markers
    for spot in SPOTS_DATABASE:
        folium.CircleMarker(
            location=[spot["lat"], spot["lon"]],
            radius=5,
            popup=f"{spot['name']} — {spot['region']}",
            tooltip=spot['name'],
            color='cyan',
            fill=True,
            fillColor='cyan',
            fillOpacity=0.6
        ).add_to(m)
    
    map_output = st_folium(
        m,
        width=None,
        height=500,
        returned_objects=["center"],
        key="map_with_crosshair"
    )
    
    # Update coordinates from map center
    if map_output and map_output.get("center"):
        st.session_state.map_center = [
            map_output["center"]["lat"],
            map_output["center"]["lng"]
        ]
        st.session_state.lat = round(map_output["center"]["lat"], 5)
        st.session_state.lon = round(map_output["center"]["lng"], 5)
    
    # Display crosshair overlay (CSS-based)
    st.markdown("""
    <div style='text-align:center; margin-top:-520px; margin-bottom:480px; pointer-events:none;'>
        <div style='font-size:60px; color:#ff0000; text-shadow: 0 0 10px #ff0000;'>⚓</div>
    </div>
    """, unsafe_allow_html=True)
    
    st.markdown(f"""
    <div style='background:#0a1a2e; padding:12px; border-radius:8px; border:1px solid #1f77b4; text-align:center;'>
    <b>📍 الإحداثيات الحالية تحت الأنكر</b><br>
    Latitude: {st.session_state.lat} | Longitude: {st.session_state.lon}
    </div>
    """, unsafe_allow_html=True)

with col_scout:
    st.markdown("### 🤖 AI Scout — الكلمة الأولى")
    
    if st.button("🚀 فحص تلقائي لأفضل السبوتات", type="primary", use_container_width=True):
        with st.spinner(f"🔍 يفحص {len(SPOTS_DATABASE)} سبوت مشهور..."):
            scan_results = scan_all_spots_parallel(SPOTS_DATABASE, target_date, max_workers=3)
            st.session_state.scan_results = scan_results
            st.success(f"✅ تم فحص {len(scan_results)} سبوت")
    
    if st.session_state.scan_results:
        st.markdown("#### 🏆 أفضل 5 سبوتات")
        for i, spot in enumerate(st.session_state.scan_results[:5], 1):
            emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "⭐"
            color = "#00ff00" if spot['score'] >= 7 else "#ffff00" if spot['score'] >= 5 else "#ffa500"
            
            st.markdown(f"""
            <div class='top-spot'>
            {emoji} <b>{spot['name']}</b><br>
            📍 {spot['region']}<br>
            🎯 <b style='color:{color};font-size:1.2em'>{spot['score']}/10</b>
            </div>
            """, unsafe_allow_html=True)
            
            if st.button(f"⚓ انتقل إلى {spot['name']}", key=f"goto_{i}", use_container_width=True):
                st.session_state.lat = spot['lat']
                st.session_state.lon = spot['lon']
                st.session_state.map_center = [spot['lat'], spot['lon']]
                st.rerun()

st.divider()

# Deep Scan Button
st.markdown("### 🔬 3) Deep Scan — التحليل العميق")

if st.button("🚀 ابدأ Deep Scan للموقع الحالي", type="primary", use_container_width=True):
    with st.spinner("⚡ جاري التحليل العميق الكامل..."):
        
        # Step 1: Coast analysis
        with st.spinner("🧭 تحليل هندسة الساحل..."):
            coast_info, coast_err = analyze_coast_geometry(st.session_state.lat, st.session_state.lon)
        
        if coast_err == "rate_limit":
            st.error("⏳ تجاوزت الحد المسموح للـ API — انتظر دقيقة وحاول مرة أخرى")
            st.stop()
        elif coast_err == "inland":
            st.error("📍 هذا موقع بري — اختر نقطة على الشاطئ أو البحر")
            st.stop()
        elif coast_err:
            st.error(f"❌ خطأ في تحليل الساحل: {coast_err}")
            st.stop()
        
        if "بحيرة" in coast_info.get("coast_type", ""):
            st.error("⛔ هذا موقع بحيرة أو سبخة — اختر ساحلاً بحرياً")
            st.stop()
        
        # Step 2: Fetch data
        with st.spinner("📡 جلب بيانات البحر والطقس..."):
            marine_data, marine_err = fetch_marine_data(st.session_state.lat, st.session_state.lon)
            weather_data, weather_err = fetch_weather_data(st.session_state.lat, st.session_state.lon)
        
        if marine_err == "rate_limit" or weather_err == "rate_limit":
            st.error("⏳ تجاوزت الحد المسموح — انتظر 60 ثانية")
            st.stop()
        elif marine_err or weather_err or not marine_data or not weather_data:
            st.error(f"❌ خطأ في جلب البيانات: {marine_err or weather_err}")
            st.stop()
        
        # Step 3: Past 48h analysis
        with st.spinner("📊 تحليل الـ48 ساعة السابقة..."):
            past_48h = analyze_past_48h(marine_data, weather_data, target_date)
        
        # Step 4: Deep scoring
        with st.spinner("⚙️ حساب الفيزياء الكاملة..."):
            hourly_data, context, score_err = compute_deep_scores(
                marine_data, weather_data, coast_info, target_date, past_48h
            )
        
        if score_err or not hourly_data:
            st.error(f"❌ خطأ في الحساب: {score_err}")
            st.stop()
        
        # Step 5: Get location name
        location_name = fetch_location_name(st.session_state.lat, st.session_state.lon)
        
        # Step 6: Calculate scores
        weighted_score = weighted_average_score(hourly_data)
        simple_score = sum(h["score"] for h in hourly_data) / len(hourly_data)
        best_hour = max(hourly_data, key=lambda x: x["score"])
        
        # Step 7: Red flags
        red_flags = []
        avg_ws = sum(h["ws_eff"] for h in hourly_data) / len(hourly_data)
        avg_longshore = sum(h["longshore_kmh"] for h in hourly_data) / len(hourly_data)
        
        if avg_ws > 50:
            red_flags.append("ريح قوية جداً")
        if avg_longshore > 2.0:
            red_flags.append("تيار جانبي خطير")
        if past_48h["is_dirty"] and past_48h["avg_swp"] < 8:
            red_flags.append("بحر مدرر + Swell ضعيف")
        
        confidence = 85 if not red_flags else (65 if len(red_flags) == 1 else 40)
        
        # Step 8: Generate Gemini report
        with st.spinner("🧠 إعداد التقرير التكتيكي بواسطة Gemini..."):
            report, report_err = generate_detailed_report(
                hourly_data, context, location_name, weighted_score
            )
        
        # Save to session
        st.session_state.deep_result = {
            "location_name": location_name,
            "coast_info": coast_info,
            "past_48h": past_48h,
            "hourly_data": hourly_data,
            "context": context,
            "weighted_score": weighted_score,
            "simple_score": simple_score,
            "best_hour": best_hour,
            "red_flags": red_flags,
            "confidence": confidence,
            "report": report,
            "report_err": report_err,
        }
        
        st.success("✅ اكتمل التحليل العميق!")
        st.rerun()

# Display deep scan results
if st.session_state.deep_result:
    result = st.session_state.deep_result
    
    st.divider()
    st.markdown("## 📊 نتائج Deep Scan")
    
    # Location info
    st.markdown(f"""
    <div class='spot-card'>
    <h3>📍 {result['location_name']}</h3>
    🧭 اتجاه البحر: <b>{result['coast_info']['shoreline_normal']}°</b><br>
    🏖️ نوع الساحل: <b>{result['coast_info']['coast_type']}</b><br>
    📊 انكشاف البحر: <b>{int(result['coast_info']['coast_exposure']*100)}%</b><br>
    🌊 إغلاق الخليج: <b>{int(result['coast_info']['bay_factor']*100)}%</b>
    </div>
    """, unsafe_allow_html=True)
    
    # Past 48h
    st.markdown("### 📊 إرث الـ48 ساعة السابقة")
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("موج رياح", f"{result['past_48h']['avg_wwh']} م")
    c2.metric("تردده", f"{result['past_48h']['avg_wwp']} ث")
    c3.metric("Swell", f"{result['past_48h']['avg_swh']} م")
    c4.metric("تردده", f"{result['past_48h']['avg_swp']} ث")
    c5.metric("الحالة", "🔴 مدرر" if result['past_48h']['is_dirty'] else "🟢 نظيف")
    
    # Hourly table
    st.markdown("### ⏰ المصفوفة الزمنية — ساعة بساعة")
    df = pd.DataFrame(result['hourly_data'])
    df_show = df[[
        "time", "score", "wind_type", "wind_kmh", "gust_kmh", "ws_eff",
        "wh_total", "ww_h", "sw_h", "sw_p",
        "longshore_kmh", "drag_n", "lead_weight", "lead_type",
        "rip_risk", "debris", "ecume", "sst_c", "rain_mm", "vis_km"
    ]].copy()
    
    df_show.columns = [
        "الوقت", "السكور", "نوع الريح", "ريح", "هبات", "ريح فعلية",
        "موج كلي", "موج ريح", "Swell", "تردد Swell",
        "تيار جانبي", "جر", "وزن رصاص", "نوع رصاص",
        "تيار ساحب", "أعشاب", "Écume", "حرارة", "مطر", "رؤية"
    ]
    
    def color_score(v):
        if v >= 7: return 'background:#0a3d0a;color:#00ff00'
        elif v >= 5: return 'background:#3d3d0a;color:#ffff00'
        elif v >= 4: return 'background:#3d2e0a;color:#ffa500'
        else: return 'background:#3d0a0a;color:#ff4b4b'
    
    def color_wind(v):
        s = str(v)
        if "وش 🟢" in s: return 'color:#00ff00;font-weight:bold'
        if "بر 🔵" in s: return 'color:#4da6ff;font-weight:bold'
        return 'color:#ffa500'
    
    styled = df_show.style.applymap(color_score, subset=["السكور"]) \
                          .applymap(color_wind, subset=["نوع الريح"])
    
    st.dataframe(styled, use_container_width=True, hide_index=True)
    
    # Metrics
    st.markdown("### 📈 المؤشرات الرئيسية")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("🎯 السكور المُرجَّح", f"{result['weighted_score']:.1f}/10")
    m2.metric("⭐ أفضل ساعة", result['best_hour']['time'][-5:], 
              delta=f"سكور: {result['best_hour']['score']}")
    m3.metric("💪 الثقة", f"{result['confidence']}%")
    m4.metric("🚩 Red Flags", len(result['red_flags']))
    m5.metric("🌙 القمر", f"{int(result['context']['moon_f']*100)}%")
    
    # Final verdict
    st.markdown("### ⚖️ القرار النهائي")
    
    if result['weighted_score'] >= 7.0 and result['confidence'] >= 75 and not result['red_flags']:
        st.markdown(f"""<div class='go-box'>
        <h2 style='color:#00ff00;text-align:center'>✅ GO — ممتاز</h2>
        <p style='text-align:center;font-size:1.2em'>
        السكور: <b>{result['weighted_score']:.1f}/10</b> | الثقة: <b>{result['confidence']}%</b><br>
        هذا السبوت من الأقوى اليوم — اذهب بدون تردد!
        </p>
        </div>""", unsafe_allow_html=True)
    
    elif result['weighted_score'] >= 5.0:
        st.markdown(f"""<div class='warn-box'>
        <h2 style='color:#ffff00;text-align:center'>🟡 GO — مقبول بشروط</h2>
        <p style='text-align:center;font-size:1.2em'>
        السكور: <b>{result['weighted_score']:.1f}/10</b> | الثقة: <b>{result['confidence']}%</b>
        </p>
        </div>""", unsafe_allow_html=True)
        
        if result['red_flags']:
            st.warning("⚠️ **تحذيرات:**")
            for flag in result['red_flags']:
                st.markdown(f"- {flag}")
    
    else:
        st.markdown(f"""<div class='nogo-box'>
        <h2 style='color:#ff0000;text-align:center'>🔴 NO-GO — غيّر السبوت</h2>
        <p style='text-align:center;font-size:1.2em'>
        السكور: <b>{result['weighted_score']:.1f}/10</b> | الثقة: <b>{result['confidence']}%</b>
        </p>
        </div>""", unsafe_allow_html=True)
        
        if result['red_flags']:
            st.error("🚨 **الأسباب:**")
            for flag in result['red_flags']:
                st.markdown(f"- {flag}")
    
    # Gemini report
    st.divider()
    st.markdown("### 🧠 التقرير التكتيكي المفصّل")
    
    if result['report_err']:
        st.error(f"❌ {result['report_err']}")
    elif result['report']:
        st.markdown(result['report'])
    else:
        st.info("لا يوجد تقرير")
    
    # Alternatives from Scout
    if st.session_state.scan_results:
        st.divider()
        st.markdown("### 💡 البدائل المقترحة من AI Scout")
        
        better_spots = [s for s in st.session_state.scan_results if s['score'] > result['weighted_score']][:3]
        
        if better_spots:
            st.warning(f"⚠️ **AI وجد {len(better_spots)} سبوت أفضل من موقعك:**")
            for spot in better_spots:
                diff = round(spot['score'] - result['weighted_score'], 1)
                distance = haversine_km(st.session_state.lat, st.session_state.lon, 
                                       spot['lat'], spot['lon'])
                
                st.markdown(f"""
                <div class='spot-card'>
                ✨ <b>{spot['name']}</b> — {spot['region']}<br>
                🎯 {spot['score']}/10 (<span style='color:#00ff00'>+{diff} نقطة</span>)<br>
                📏 المسافة: <b>{distance} كم</b><br>
                📍 {spot['lat']:.4f}, {spot['lon']:.4f}
                </div>
                """, unsafe_allow_html=True)
                
                if st.button(f"⚓ انتقل إلى {spot['name']}", key=f"alt_{spot['name']}", use_container_width=True):
                    st.session_state.lat = spot['lat']
                    st.session_state.lon = spot['lon']
                    st.session_state.map_center = [spot['lat'], spot['lon']]
                    st.session_state.deep_result = None
                    st.rerun()
        else:
            st.success("✅ **موقعك من الأفضل في تونس اليوم!**")
    
    # Add to favorites
    st.divider()
    if st.button("⭐ أضف هذا السبوت للمفضلة", use_container_width=True):
        fav = {
            "name": result['location_name'],
            "lat": st.session_state.lat,
            "lon": st.session_state.lon,
            "score": result['weighted_score'],
            "date": str(target_date)
        }
        if not any(f['lat'] == fav['lat'] and f['lon'] == fav['lon'] for f in st.session_state.favorites):
            st.session_state.favorites.append(fav)
            st.success("✅ تمت الإضافة للمفضلة")
        else:
            st.info("هذا السبوت موجود بالفعل في المفضلة")

# Favorites section
if st.session_state.favorites:
    st.divider()
    st.markdown("### ⭐ المفضلة")
    fav_df = pd.DataFrame(st.session_state.favorites)
    st.dataframe(fav_df, use_container_width=True, hide_index=True)

st.divider()
st.caption("© مستشار الصيد AI v10.0 ULTIMATE | الأنكر الثابت + Deep Scan + الكلمة الأولى والأخيرة")
