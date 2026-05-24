import os
import json
import math
import requests
import streamlit as st
import folium
import pandas as pd
from streamlit_folium import st_folium
from datetime import datetime, timedelta, date
import google.generativeai as genai
from concurrent.futures import ThreadPoolExecutor, as_completed

# ══════════════════════════════════════════════════════════════
# 1. CONFIG
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="مستشار الصيد AI | تونس",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
  body{direction:rtl}
  .block-container{padding-top:0.5rem}
  .go-box{background:#0a3d0a;padding:20px;border-radius:12px;border:3px solid #00ff00}
  .nogo-box{background:#3d0a0a;padding:20px;border-radius:12px;border:3px solid #ff0000}
  .warn-box{background:#3d2e0a;padding:20px;border-radius:12px;border:3px solid #ffa500}
  .spot-card{background:#0a1a2e;padding:14px;border-radius:8px;border:1px solid #1f77b4;margin-bottom:8px}
  .top-spot{background:#0a3d0a;padding:16px;border-radius:10px;border:2px solid #0f0;margin:6px 0}
  .scroll-cards{display:flex;flex-direction:column;gap:10px;max-height:700px;overflow-y:auto;padding:10px}
</style>
""", unsafe_allow_html=True)

st.title("🎣 مستشار الصيد AI | v10.0")
st.markdown("**☝️ تصفح السبوتات → اضغط على سبوت → احصل على تقرير مفصل**")

# ══════════════════════════════════════════════════════════════
# 2. DATABASE - قاعدة بيانات السبوتات
# ══════════════════════════════════════════════════════════════
SPOTS_DATABASE = [
    # ===== بنزرت =====
    {"id":"ras_eddarck","name":"رأس الدرك","lat":37.2742,"lon":9.8739,"region":"بنزرت","type":"rocky_open"},
    {"id":"hawaria","name":"الهوارية","lat":37.0539,"lon":11.0581,"region":"نابل","type":"rocky_open"},
    {"id":"ghar_el_melh","name":"غار الملح","lat":37.1728,"lon":10.0872,"region":"بنزرت","type":"bay"},
    {"id":"rafraf","name":"رفراف الشاطئ","lat":37.1889,"lon":10.1833,"region":"بنزرت","type":"open_coast"},
    {"id":"rakta","name":"الراكتة","lat":37.1000,"lon":10.9000,"region":"بنزرت","type":"rocky_open"},
    # ===== نابل =====
    {"id":"kelibia","name":"قليبية","lat":36.8333,"lon":11.1000,"region":"نابل","type":"open_coast"},
    {"id":"hammamet","name":"الحمامات","lat":36.4000,"lon":10.6167,"region":"نابل","type":"urban_beach"},
    {"id":"tabarka","name":"طبرقة","lat":36.5700,"lon":8.7700,"region":"نابل","type":"rocky_open"},
    {"id":"aïn_draham","name":"عين دراهم","lat":36.7200,"lon":8.5900,"region":"نابل","type":"bay"},
    # ===== سوسة =====
    {"id":"sousse_boujaafar","name":"سوسة بوجعفر","lat":35.8256,"lon":10.6369,"region":"سوسة","type":"urban_beach"},
    {"id":"monastir","name":"المنستير الشاطئ","lat":35.7672,"lon":10.8111,"region":"المنستير","type":"urban_beach"},
    {"id":"bordj_cedria","name":"برج السدرياء","lat":36.0300,"lon":10.1500,"region":"سوسة","type":"rocky_open"},
    # ===== المهدية =====
    {"id":"mahdia","name":"المهدية الكورنيش","lat":35.5047,"lon":11.0622,"region":"المهدية","type":"open_coast"},
    {"id":"khezamet_el_bihar","name":"خزامة البحار","lat":35.5500,"lon":11.1000,"region":"المهدية","type":"bay"},
    # ===== صفاقس =====
    {"id":"sfax","name":"صفاقس رأس الطابية","lat":34.7333,"lon":10.7633,"region":"صفاقس","type":"mixed"},
    {"id":"kerkennah","name":"قرقنة","lat":34.7333,"lon":11.1167,"region":"صفاقس","type":"island"},
    {"id":"skanes","name":"سكنة","lat":34.7400,"lon":10.6900,"region":"صفاقس","type":"urban_beach"},
    # ===== قابس =====
    {"id":"gabes","name":"قابس الشاطئ","lat":33.8815,"lon":10.0982,"region":"قابس","type":"mixed"},
    {"id":"matmata","name":"متمة","lat":33.7500,"lon":10.3500,"region":"قابس","type":"bay"},
    # ===== جرجيس =====
    {"id":"zarzis","name":"جرجيس","lat":33.5042,"lon":10.8681,"region":"جرجيس","type":"open_coast"},
    {"id":"djerba_mersa_gueir","name":"مرسى الجراج","lat":33.1500,"lon":10.4300,"region":"دجربة","type":"bay"},
    {"id":"houmt_souk","name":"حمامات","lat":33.2000,"lon":10.4800,"region":"دجربة","type":"urban_beach"},
    {"id":"ain_khaled","name":"عين الخالدة","lat":33.2800,"lon":10.5200,"region":"دجربة","type":"open_coast"},
    # ===== مدنين =====
    {"id":"sidi_youssef","name":"سيدي يوسف","lat":36.8000,"lon":10.0500,"region":"مدنين","type":"rocky_open"},
    {"id":"zouaraa","name":"زواراء","lat":36.7600,"lon":9.9800,"region":"مدنين","type":"bay"},
    # ===== ساببة =====
    {"id":"zouaraa","name":"زواراء","lat":36.7600,"lon":9.9800,"region":"مدنين","type":"bay"},
    {"id":"nabeul","name":"نابلس الشاطئ","lat":36.2300,"lon":10.6600,"region":"نابلس","type":"urban_beach"},
    {"id":"korbous","name":"قربوس","lat":36.3300,"lon":10.2700,"region":"بنزرت","type":"open_coast"},
    {"id":"cap_bon_el_kef","name":"رأس البون الكيف","lat":36.0500,"lon":10.3500,"region":"سوسة","type":"rocky_open"},
    {"id":"sejnane","name":"سجنان","lat":36.6800,"lon":9.5800,"region":"بنزرت","type":"bay"},
    {"id":"tunis_port","name":"ميناء تونس","lat":36.6100,"lon":10.2100,"region":"تونس","type":"urban_beach"},
    {"id":"la_mouriscan","name":"المرسكان","lat":36.5800,"lon":10.2400,"region":"تونس","type":"urban_beach"},
    {"id":"radès","name":"الرادس","lat":36.4700,"lon":10.2200,"region":"تونس","type":"urban_beach"},
    {"id":"bir_bouregreg","name":"بربريغ سباحة","lat":36.4800,"lon":10.2300,"region":"تونس","type":"urban_beach"},
    {"id":"mejetna","name":"مجذانة","lat":36.5300,"lon":10.4600,"region":"بنزرت","type":"bay"},
    {"id":"sidi_ali_mekki","name":"سيدي علي المكي","lat":36.3500,"lon":10.5000,"region":"بنزرت","type":"rocky_open"},
    {"id":"dellal","name":"دللال","lat":36.3200,"lon":10.5600,"region":"بنزرت","type":"open_coast"},
    {"id":"berber","name":"بربر","lat":36.3800,"lon":10.6400,"region":"بنزرت","type":"urban_beach"},
    {"id":"carthage","name":"قرطاج","lat":36.5900,"lon":10.3100,"region":"تونس","type":"urban_beach"},
    {"id":"stintino","name":"السفانة","lat":37.3900,"lon":8.9500,"region":"بنزرت","type":"rocky_open"},
    {"id":"foum_tatouine","name":"فم تاتوين","lat":33.9200,"lon":10.1700,"region":"تاتوين","type":"bay"},
    {"id":"kesr_souk","name":"كسر سوق","lat":34.5500,"lon":10.4300,"region":"صفاقس","type":"open_coast"},
    {"id":"meharia","name":"مهدية","lat":34.4800,"lon":10.5100,"region":"صفاقس","type":"urban_beach"},
    {"id":"saouaf","name":"ساوف","lat":35.3500,"lon":10.1900,"region":"سوسة","type":"bay"},
    {"id":"soliman","name":"سليمان","lat":35.9000,"lon":10.4300,"region":"المنستير","type":"open_coast"},
]

# ══════════════════════════════════════════════════════════════
# 3. HELPERS
# ══════════════════════════════════════════════════════════════
def destination_point(lat1, lon1, bearing, dist_km):
    R = 6371.0
    b = math.radians(bearing)
    φ1, λ1 = math.radians(lat1), math.radians(lon1)
    φ2 = math.asin(math.sin(φ1)*math.cos(dist_km/R) +
                   math.cos(φ1)*math.sin(dist_km/R)*math.cos(b))
    λ2 = λ1 + math.atan2(math.sin(b)*math.sin(dist_km/R)*math.cos(φ1),
                         math.cos(dist_km/R) - math.sin(φ1)*math.sin(φ2))
    return math.degrees(φ2), math.degrees(λ2)

def circular_mean(angles):
    if not angles: return 0.0
    s = sum(math.sin(math.radians(a)) for a in angles) / len(angles)
    c = sum(math.cos(math.radians(a)) for a in angles) / len(angles)
    return math.degrees(math.atan2(s, c)) % 360

def angle_diff(a, b):
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d

def moon_factor(d):
    delta = (d - date(2024, 1, 11)).days % 29.53
    return round(0.5 + 0.5*abs(math.cos(2*math.pi*delta/29.53)), 3)

def get_hourly_value(data, key, idx, default=0.0):
    arr = data['hourly'].get(key, [])
    if idx < len(arr) and arr[idx] is not None:
        try: return float(arr[idx])
        except: return default
    return default

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat/2)**2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon/2)**2)
    return 2 * R * math.asin(math.sqrt(a))

# ══════════════════════════════════════════════════════════════
# 4. API CALLS (مع cache)
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def analyze_coast(lat, lon):
    points = [destination_point(lat, lon, b, 3.0) for b in range(0, 360, 30)]
    lats = ",".join(str(round(p[0], 4)) for p in points)
    lons = ",".join(str(round(p[1], 4)) for p in points)

    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/elevation",
            params={"latitude": lats, "longitude": lons},
            headers={"User-Agent": "TunisiaFishingAI/10.0"},
            timeout=15
        )
        r.raise_for_status()
        elevs = r.json().get("elevation", [])
    except Exception:
        return None, "خطأ في تحليل الساحل"

    sea_bearings = [b for (_, _), b, e in
                    zip(points, range(0, 360, 30), elevs)
                    if e is not None and e <= 0.5]

    if not sea_bearings:
        return None, "inland"

    exposure = len(sea_bearings) / len(points)
    sn = circular_mean(sea_bearings)

    if exposure < 0.05:
        coast_type = "🔴 بحيرة / سبخة"
    elif exposure > 0.65:
        coast_type = "🌊 ساحل مفتوح / رأس بحري"
    elif exposure > 0.35:
        coast_type = "🏖️ ساحل عادي"
    else:
        coast_type = "⚓ خليج مغلق"

    bay_factor = 1.0 - exposure
    if bay_factor > 0.85:
        bay_factor = 0.9

    return {
        "sn": round(sn, 1),
        "exposure": round(exposure, 2),
        "bay_factor": round(bay_factor, 2),
        "coast_type": coast_type,
    }, None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_data(lat, lon):
    headers = {"User-Agent": "TunisiaFishingAI/10.0"}

    try:
        marine_r = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params={
                "latitude": lat, "longitude": lon,
                "hourly": "wave_height,wave_direction,wave_period,"
                          "wind_wave_height,wind_wave_direction,wind_wave_period,"
                          "swell_wave_height,swell_wave_direction,swell_wave_period,"
                          "sea_surface_temperature",
                "past_days": 2, "forecast_days": 3, "timezone": "auto"
            },
            headers=headers, timeout=20
        )
        marine_r.raise_for_status()
        marine = marine_r.json()

        weather_r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat, "longitude": lon,
                "hourly": "wind_speed_10m,wind_direction_10m,"
                          "wind_gusts_10m,precipitation,visibility",
                "past_days": 2, "forecast_days": 3, "timezone": "auto"
            },
            headers=headers, timeout=20
        )
        weather_r.raise_for_status()
        weather = weather_r.json()

        if "hourly" not in marine or "hourly" not in weather:
            return None, None, "بيانات ناقصة"

        return marine, weather, None
    except requests.exceptions.HTTPError as e:
        return None, None, f"HTTP {e.response.status_code if e.response else 0}"
    except Exception as e:
        return None, None, str(e)

# ══════════════════════════════════════════════════════════════
# 5. SCORING ENGINE - المرحلة 1: Quick Scan
# ══════════════════════════════════════════════════════════════
def quick_score_spot(lat, lon, target_date):
    coast, err = analyze_coast(lat, lon)
    if err or not coast:
        return 0.0

    marine, weather, err = fetch_data(lat, lon)
    if err or not marine or not weather:
        return 0.0

    times = weather['hourly'].get('time', [])
    if not times:
        return 0.0

    scores = []
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t)
        except:
            continue

        if dt.date() != target_date:
            continue

        ws = get_hourly_value(weather, 'wind_speed_10m', i)
        gust = get_hourly_value(weather, 'wind_gusts_10m', i)
        wdir = get_hourly_value(weather, 'wind_direction_10m', i)
        wh = get_hourly_value(marine, 'wave_height', i)
        sst = get_hourly_value(marine, 'sea_surface_temperature', i, 18.0)

        ws_eff = max(ws, gust * 0.7)
        wdir_going = (wdir + 180) % 360
        diff = angle_diff(wdir_going, coast['sn'])

        score = 10.0

        if diff <= 45:
            score += 1.2 if 8 <= ws_eff <= 25 else (-0.5 if ws_eff < 8 else 0.0)
        elif diff >= 135:
            score += 1.0 if ws_eff <= 15 else (-1.5 if ws_eff <= 25 else -3.0)
        else:
            score -= 1.0

        if wh < 0.25:
            score -= 3.0
        elif wh > 1.8:
            score -= 1.5

        if ws_eff > 50:
            score -= 5.0
        elif ws_eff > 35:
            score -= 2.0
        elif ws_eff > 28:
            score -= 1.0

        if sst < 15:
            score -= 2.0
        elif 19 <= sst <= 24:
            score += 0.5

        score = max(0, min(10, score))
        weight = 2.5 if dt.hour in set(range(17, 24)) | set(range(4, 9)) else 1.0
        scores.append((score, weight))

    if not scores:
        return 0.0

    total = sum(s * w for s, w in scores)
    weights = sum(w for _, w in scores)
    return round(total / weights if weights else 0, 1)

# ══════════════════════════════════════════════════════════════
# 6. SCORING ENGINE - المرحلة 2: Deep Analysis
# ══════════════════════════════════════════════════════════════
def analyze_past_48h(marine, weather, target_date):
    times = weather['hourly']['time']
    past_wwh, past_wwp, past_swh, past_swp = [], [], [], []

    target_start = datetime.combine(target_date, datetime.min.time())
    past_start = target_start - timedelta(hours=48)

    for i, t in enumerate(times):
        try:
            t_obj = datetime.fromisoformat(t)
        except:
            continue
        if past_start <= t_obj < target_start:
            wwh = get_hourly_value(marine, 'wind_wave_height', i)
            wwp = get_hourly_value(marine, 'wind_wave_period', i)
            swh = get_hourly_value(marine, 'swell_wave_height', i)
            swp = get_hourly_value(marine, 'swell_wave_period', i)
            if wwh > 0: past_wwh.append(wwh)
            if wwp > 0: past_wwp.append(wwp)
            if swh > 0: past_swh.append(swh)
            if swp > 0: past_swp.append(swp)

    def avg(lst): return sum(lst) / len(lst) if lst else 0.0

    return {
        "avg_wwh": round(avg(past_wwh), 2),
        "avg_wwp": round(avg(past_wwp), 1),
        "avg_swh": round(avg(past_swh), 2),
        "avg_swp": round(avg(past_swp), 1),
        "is_dirty": (avg(past_wwh) > 1.2) and (avg(past_wwp) < 6.0),
    }

def score_hour(marine, weather, idx, sn, exposure, bay_factor, coast_type):
    score = 10.0
    ts = weather['hourly']['time'][idx]
    t_obj = datetime.fromisoformat(ts)

    wd  = get_hourly_value(marine, 'wave_direction', idx)
    wp  = get_hourly_value(marine, 'wave_period', idx)
    wwh = get_hourly_value(marine, 'wind_wave_height', idx)
    wwd = get_hourly_value(marine, 'wind_wave_direction', idx)
    wwp = get_hourly_value(marine, 'wind_wave_period', idx)
    swh = get_hourly_value(marine, 'swell_wave_height', idx)
    swd = get_hourly_value(marine, 'swell_wave_direction', idx)
    swp = get_hourly_value(marine, 'swell_wave_period', idx)
    sst = get_hourly_value(marine, 'sea_surface_temperature', idx, 18.0)

    ws   = get_hourly_value(weather, 'wind_speed_10m', idx)
    wdir = get_hourly_value(weather, 'wind_direction_10m', idx)
    gust = get_hourly_value(weather, 'wind_gusts_10m', idx)
    rain = get_hourly_value(weather, 'precipitation', idx)
    vis  = get_hourly_value(weather, 'visibility', idx, 24140) / 1000

    ws_eff = max(ws, gust * 0.7)
    wdir_going = (wdir + 180) % 360
    diff = angle_diff(wdir_going, sn)

    wind_label = ""
    if diff <= 45:
        wind_label = "وش 🟢"
        score += 1.5 if 8 <= ws_eff <= 25 else (-0.5 if ws_eff < 8 else 0.0)
    elif diff >= 135:
        wind_label = "بر 🔵"
        score += 1.0 if ws_eff <= 15 else (-1.5 if ws_eff <= 25 else -3.0)
    elif diff <= 90:
        wind_label = "جانبي-وش 🟡"
        score -= 0.5 if ws_eff <= 20 else -1.5
    else:
        wind_label = "جانبي-بر 🟠"
        score -= 0.8 if ws_eff <= 20 else -2.5

    wave_impact = angle_diff(wd, sn)
    sw_impact = angle_diff(swd, sn)

    wwh_eff = wwh * (1.0 - bay_factor * 0.50)
    swh_eff = swh * (1.0 - bay_factor * 0.30)
    wh_eff = wwh_eff + swh_eff

    def longshore_velocity(hb, imp):
        if hb > 0.05 and imp > 10:
            ir = math.radians(imp)
            v = 1.17 * math.sqrt(9.81 * hb) * math.sin(ir) * math.cos(ir)
            return v * 3.6
        return 0.0

    v_kmh = (longshore_velocity(wwh_eff * 1.4, wave_impact) +
             longshore_velocity(swh_eff * 1.2, sw_impact))

    if wh_eff < 0.3:
        score -= 3.0
    if "مدرر" in str(bay_factor) or (wwh_eff > 1.2 and wwp < 6.0):
        score -= 4.0

    if v_kmh > 1.5:
        score -= 4.0
    elif v_kmh > 0.8:
        score -= 2.0

    if ws_eff > 55:
        score -= 5.0
    elif ws_eff > 42:
        score -= 3.0
    elif ws_eff > 32:
        score -= 1.5

    if rain > 5.0:
        score -= 2.0
    elif rain > 1.0:
        score -= 0.5

    if vis < 1000:
        score -= 3.0
    elif vis < 3000:
        score -= 1.0

    is_clean = (swp >= 8.0 and sw_impact < 45 and swh_eff <= 1.2)
    if is_clean:
        score += 1.5

    moon = moon_factor(t_obj.date())
    score += max(0.0, (moon - 0.55) * 1.5)

    if sst < 15.0:
        score -= 2.0
    elif sst < 17.0:
        score -= 1.0
    elif 19 <= sst <= 24:
        score += 0.5

    score = max(0.0, min(10.0, score))
    ecume = "نعم ✅" if ("وش" in wind_label and 0.4 <= wh_eff <= 1.4
                          and wave_impact < 50 and ws_eff >= 8) else "لا"

    return {
        "time": ts[-5:],
        "hour": t_obj.hour,
        "score": round(score, 1),
        "wh_eff": round(wh_eff, 2),
        "wp": round(wp, 1),
        "ww_h": round(wwh_eff, 2),
        "ww_p": round(wwp, 1),
        "ww_impact": round(wave_impact, 1),
        "sw_h": round(swh_eff, 2),
        "sw_p": round(swp, 1),
        "sw_impact": round(sw_impact, 1),
        "wind_kmh": round(ws, 1),
        "gust_kmh": round(gust, 1),
        "ws_eff": round(ws_eff, 1),
        "wind_dir": round(wdir, 0),
        "wind_type": wind_label,
        "longshore_kmh": round(v_kmh, 2),
        "lead_rec": "سبايك 140g" if v_kmh > 1.5 else ("هرمي 120g" if v_kmh > 0.8 else "زيتوني 100g"),
        "rip": ("عالي" if wh_eff > 1.2 and wp > 8 and 20 <= wave_impact <= 60 else
                "متوسط" if wh_eff > 1.0 and wp > 6 and wave_impact < 30 else
                "منخفض"),
        "debris": ("Swell ينظف 🟢" if is_clean and (wwh_eff > 1.2 and wwp < 6.0) else
                   "مدرر 🔴" if (wwh_eff > 1.2 and wwp < 6.0) and swp < 8.0 else
                   "نظيف 🟢"),
        "ecume": ecume,
        "sst_c": round(sst, 1),
        "rain_mm": round(rain, 1),
        "vis_km": round(vis, 1),
    }

def deep_analyze_spot(lat, lon, target_date):
    coast, err = analyze_coast(lat, lon)
    if err:
        return None, err

    marine, weather, err = fetch_data(lat, lon)
    if err:
        return None, err

    if "hourly" not in marine or "hourly" not in weather:
        return None, "بيانات ناقصة"

    past_48h = analyze_past_48h(marine, weather, target_date)

    times = weather['hourly']['time']
    hourly = []
    for i, t in enumerate(times):
        try:
            t_obj = datetime.fromisoformat(t)
        except:
            continue
        if t_obj.date() == target_date:
            hourly.append(score_hour(
                marine, weather, i,
                coast['sn'], coast['exposure'], coast['bay_factor'], coast['coast_type']
            ))

    if not hourly:
        return None, "لا توجد بيانات لهذا اليوم"

    prime = set(range(17, 24)) | set(range(4, 9))
    tw, ts = 0.0, 0.0
    for h in hourly:
        w = 2.5 if h["hour"] in prime else 1.0
        ts += h["score"] * w
        tw += w

    best = max(hourly, key=lambda x: x["score"])
    avg_sst = sum(h["sst_c"] for h in hourly) / len(hourly)
    ecume_cnt = sum(1 for h in hourly if "نعم" in h["ecume"])

    return {
        "hourly": hourly,
        "weighted_score": round(ts / tw if tw else 0, 1),
        "simple_score": round(sum(h["score"] for h in hourly) / len(hourly), 1),
        "best_hour": best["time"],
        "best_score": best["score"],
        "moon": moon_factor(target_date),
        "past_48h": past_48h,
        "avg_sst": round(avg_sst, 1),
        "ecume_hours": f"{ecume_cnt}/{len(hourly)}",
    }, None

# ══════════════════════════════════════════════════════════════
# 7. SCAN ALL SPOTS (المرحلة 1)
# ══════════════════════════════════════════════════════════════
def scan_all_spots(spots, target_date):
    results = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {
            executor.submit(quick_score_spot, s['lat'], s['lon'], target_date): s
            for s in spots
        }

        for future in as_completed(futures):
            spot = futures[future]
            try:
                score = future.result()
                if score > 0:
                    results.append({
                        "name": spot['name'],
                        "region": spot['region'],
                        "lat": spot['lat'],
                        "lon": spot['lon'],
                        "type": spot['type'],
                        "quick_score": score,
                    })
            except Exception:
                pass

    results.sort(key=lambda x: x['quick_score'], reverse=True)
    return results

# ══════════════════════════════════════════════════════════════
# 8. GEMINI REPORT
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=1800, show_spinner=False)
def generate_report(hourly_data, past_48h, coast, target_date, location_name):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, "GEMINI_API_KEY مفقود في المتغيرات البيئية"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            generation_config=genai.GenerationConfig(
                temperature=0.1,
                top_p=0.1,
                max_output_tokens=3500
            )
        )

        avg_wwh = past_48h.get('avg_wwh', 0)
        avg_swh = past_48h.get('avg_swh', 0)
        is_dirty = past_48h.get('is_dirty', False)

        best_hour_data = max(hourly_data, key=lambda x: x['score'])

        prompt = f"""أنت خبير صيد تونسي محترف جداً في هيدروديناميكا السواحل.
كن حاسماً ومباشراً باللهجة التونسية.

📍 موقع: {location_name}
🧭 اتجاه البحر: {coast['sn']}°
🏖️ نوع الساحل: {coast['coast_type']}
📅 يوم التحليل: {target_date}
🌙 عامل القمر: {int(coast['moon']*100)}%
🎯 سكور: {coast['weighted_score']}/10

📊 إرث البحر (48 ساعة سابقة):
• موج ريح: {avg_wwh}م / {past_48h.get('avg_wwp',0)}ث
• Swell: {avg_swh}م / {past_48h.get('avg_swp',0)}ث
• الحالة: {'🔴 مدرر ومتعرق' if is_dirty else '🟢 نظيف ومرتب'}

⏰ أفضل ساعة: {best_hour_data['time']} (سكور {best_hour_data['score']}/10)
   • نوع الريح: {best_hour_data['wind_type']}
   • موج فعلي: {best_hour_data['wh_eff']}م
   • تيار جانبي: {best_hour_data['longshore_kmh']} كم/س
   • حرارة البحر: {best_hour_data['sst_c']}°C
   • رؤية: {best_hour_data['vis_km']} كم
   • سكورة: {best_hour_data['debris']}

📋 بيانات ساعة بساعة:
{json.dumps(hourly_data, ensure_ascii=False, indent=1)}

اكتب تقريراً مفصلاً ومباشراً بالتسلسل التالي:

## 1️⃣ هوية الموقع وخصائصه
## 2️⃣ حالة البحر (إرث 48 ساعة)
## 3️⃣ الريح ساعة بساعة
## 4️⃣ الفيزياء: تيار - رصاص - Écume
## 5️⃣ النوافذ البيولوجية (أفضل الأوقات)
## 6️⃣ القرار النهائي والحاسم ({coast['weighted_score']}/10)

القرار النهائي:
- ≥ 7.5 → ✅ GO: اذهب بدون تردد
- 5-7.5 → 🟡 GO مشروط: اذهب بشروط
- 4-5 → 🟠 مخاطر: للخبراء فقط
- < 4 → 🔴 NO-GO: غيّر السبوت فوراً

استخدم المصطلحات التونسية. كن صريحاً. لا تتكلم بالزهد.
لا تخترع أرقاماً. التقرير يبقى مختصر ومفيد.
"""
        return model.generate_content(prompt).text, None
    except Exception as e:
        return None, f"خطأ Gemini: {str(e)}"

# ══════════════════════════════════════════════════════════════
# 9. UI — تصفح السبوتات + الضغط = Deep Scan
# ══════════════════════════════════════════════════════════════

# ─── اختيار اليوم ───
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🔵 اليوم", use_container_width=True, type="primary"):
        st.session_state.day_offset = 0
with col2:
    if st.button("🟢 غداً", use_container_width=True):
        st.session_state.day_offset = 1
with col3:
    if st.button("🟡 بعد غد", use_container_width=True):
        st.session_state.day_offset = 2

if 'day_offset' not in st.session_state:
    st.session_state.day_offset = 1

day_names = {0: "اليوم", 1: "غداً", 2: "بعد غد"}
target_date = date.today() + timedelta(days=st.session_state.day_offset)
st.info(f"📆 **{day_names[st.session_state.day_offset]}** — {target_date.strftime('%Y-%m-%d')}")

st.divider()

# ─── فلتر حسب المنطقة ───
regions = sorted(list(set(s['region'] for s in SPOTS_DATABASE)))
selected_region = st.selectbox("🏷️ اختر المنطقة:", ["كل التونس"] + regions)

if selected_region != "كل التونس":
    filtered_spots = [s for s in SPOTS_DATABASE if s['region'] == selected_region]
else:
    filtered_spots = SPOTS_DATABASE

# ─── Auto Scan عند الفتح ───
if "scan_results" not in st.session_state or \
   st.session_state.get("scan_date") != str(target_date) or \
   selected_region != st.session_state.get("scan_region", ""):

    with st.spinner(f"🔍 AI يفحص {len(filtered_spots)} سبوت في {selected_region or 'تونس'}..."):
        results = scan_all_spots(filtered_spots, target_date)
        st.session_state.scan_results = results
        st.session_state.scan_date = str(target_date)
        st.session_state.scan_region = selected_region

# ─── عرض السبوتات كبطاقات ───
st.markdown(f"### 📋 السبوتات مرتبة ({len(st.session_state.scan_results)} سبوت)")

if st.session_state.scan_results:
    scroll_container = st.container()
    with scroll_container:

        for i, spot in enumerate(st.session_state.scan_results[:20], 1):

            score = spot['quick_score']
            emoji_rank = "🥇" if i == 1 else ("🥈" if i == 2 else ("🥉" if i == 3 else "⭐"))

            score_color = "#00ff00" if score >= 7 else ("#ffff00" if score >= 5 else "#ffa500" if score >= 4 else "#ff4444")

            st.markdown(f"""
            <div class='spot-card'>
            {emoji_rank} <b style='font-size:1.2em;color:{score_color}'>{spot['name']}</b><br>
            📍 {spot['region']} | 🏷️ {spot['type']}<br>
            🎯 <b style='font-size:1.3em;color:{score_color}'>{score}/10</b><br>
            🧭 {st.session_state.get('coast_data',{}).get(spot['name'],{}).get('sn', '?')}°
            </div>
            """, unsafe_allow_html=True)

            # زر Deep Scan لكل سبوت
            if st.button(f"🔬 Deep Scan + تقرير مفصل",
                         key=f"deep_{spot['name']}_{spot['lat']}_{spot['lon']}"):
                st.session_state.selected_spot = spot
                st.session_state.deep_day = str(target_date)
                st.rerun()

# ─── Deep Scan عند الضغط ───
if 'selected_spot' in st.session_state:
    spot = st.session_state.selected_spot

    st.divider()
    st.markdown(f"### 🔬 Deep Scan: {spot['name']} | {spot['region']}")
    st.markdown(f"📍 {spot['lat']:.4f}, {spot['lon']:.4f}")
    st.markdown(f"📅 {target_date.strftime('%Y-%m-%d')}")

    with st.spinner("⚡ تحليل عميق..."):
        coast, coast_err = analyze_coast(spot['lat'], spot['lon'])

    if coast_err:
        st.error(f"⛔ {coast_err}")
        del st.session_state.selected_spot
        st.stop()

    coast['moon'] = moon_factor(target_date)

    deep, deep_err = deep_analyze_spot(spot['lat'], spot['lon'], target_date)

    if deep_err:
        st.error(f"⛔ {deep_err}")
        del st.session_state.selected_spot
        st.stop()

    # ─── بيانات الساحل ───
    st.markdown(f"""
    <div class='top-spot'>
    🧭 اتجاه البحر: {coast['sn']}°<br>
    🏖️ {coast['coast_type']}<br>
    📊 انكشاف: {int(coast['exposure']*100)}% | خليج: {int(coast['bay_factor']*100)}%
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("### 📊 مصفوفة الساعات")

    df = pd.DataFrame(deep['hourly'])
    show_cols = ["score", "wind_type", "wh_eff", "ww_h", "sw_h", "wind_kmh", "ws_eff", "sst_c", "rain_mm", "vis_km", "lead_rec", "debris", "ecume", "longshore_kmh"]
    col_names = ["السكور", "نوع الريح", "موج فعلي م", "موج ريح م", "Swell م", "ريح كم/س", "ريح فعلية", "حرارة°C", "مطر mm", "رؤية كم", "الرصاص", "الأعشاب", "Écume", "تيار كم/س"]

    df_show = df[show_cols].copy()
    df_show.columns = col_names

    def c_score(v):
        if v >= 7: return 'background:#0a3d0a;color:#0f0'
        elif v >= 5: return 'background:#3d3d0a;color:#ff0'
        elif v >= 4: return 'background:#3d2e0a;color:#fa0'
        else: return 'background:#3d0a0a;color:#f44'

    def c_wind(v):
        s = str(v)
        if "وش 🟢" in s: return 'color:#0f0;font-weight:bold'
        if "بر 🔵" in s: return 'color:#4af;font-weight:bold'
        if "جانبي" in s: return 'color:#fa0;font-weight:bold'

    styled = df_show.style.applymap(c_score, subset=["السكور"]) \
                       .applymap(c_wind, subset=["نوع الريح"])

    st.dataframe(styled, use_container_width=True, hide_index=True)

    # ─── معايير ───
    col_a, col_b, col_c, col_d, col_e = st.columns(5)
    col_a.metric("🎯 السكور المُرجَّح", f"{deep['weighted_score']}/10",
                 delta=f"بسيط: {deep['simple_score']}")
    col_b.metric("⭐ أفضل ساعة", deep['best_hour'],
                 delta=f"سكور: {deep['best_score']}")
    col_c.metric("🌙 القمر", f"{int(coast['moon']*100)}%")
    col_d.metric("🌡️ حرارة البحر", f"{deep['avg_sst']}°C")
    col_e.metric("Écume", deep['ecume_hours'])

    # ─── القرار النهائي ───
    score = deep['weighted_score']

    st.markdown("---")
    st.markdown("### ⚡ القرار النهائي")

    if score >= 7.5:
        st.markdown(f"""<div class='go-box'>
        <h2 style='color:#0f0;text-align:center;font-size:1.8em'>
        ✅ GO — ممتاز، اذهب فوراً!
        </h2>
        <p style='text-align:center;font-size:1.2em'>{score}/10</p>
        <p style='text-align:center'>
        أفضل وقت: {deep['best_hour']} | رصاص: {deep['hourly'][0]['lead_rec']}
        </p>
        </div>""", unsafe_allow_html=True)

    elif score >= 5.0:
        st.markdown(f"""<div class='go-box'>
        <h2 style='color:#ff0;text-align:center;font-size:1.8em'>
        🟡 GO مشروط
        </h2>
        <p style='text-align:center;font-size:1.2em'>{score}/10</p>
        <p style='text-align:center'>
        أفضل وقت: {deep['best_hour']} | لكن راقب الريح
        </p>
        </div>""", unsafe_allow_html=True)

    elif score >= 4.0:
        st.markdown(f"""<div class='warn-box'>
        <h2 style='color:#fa0;text-align:center;font-size:1.8em'>
        🟠 للخبراء فقط
        </h2>
        <p style='text-align:center;font-size:1.2em'>{score}/10</p>
        <p style='text-align:center'>
        خطر: تيار قوي أو مدرر
        </p>
        </div>""", unsafe_allow_html=True)

    else:
        st.markdown(f"""<div class='nogo-box'>
        <h2 style='color:#f44;text-align:center;font-size:1.8em'>
        🔴 NO-GO — غيّر السبوت!
        </h2>
        <p style='text-align:center;font-size:1.2em'>{score}/10</p>
        <p style='text-align:center'>
        لا تذهب اليوم. ابحث عن بديل.
        </p>
        </div>""", unsafe_allow_html=True)

    # ─── التقرير التفصيلي من Gemini ───
    st.markdown("---")
    st.markdown("### 🧠 التقرير التكتيكي من الخبير")

    with st.spinner("🤖 جيل Gemini يكتب التقرير..."):
        report, gen_err = generate_report(
            deep['hourly'], deep['past_48h'], coast,
            target_date.strftime('%Y-%m-%d'), spot['name']
        )

    if gen_err:
        st.error(f"⛔ {gen_err}")
    else:
        st.markdown(report)

    # ─── خريطة ───
    st.markdown("---")
    st.markdown("### 🗺️ الموقع على الخريطة")

    m = folium.Map(location=[spot['lat'], spot['lon']],
                   zoom_start=12, tiles="CartoDB dark_matter")

    # shoreline normal
    lat_e, lon_e = destination_point(spot['lat'], spot['lon'], coast['sn'], 3.0)
    folium.PolyLine(
        [[spot['lat'], spot['lon']], [lat_e, lon_e]],
        color="cyan", weight=3,
        popup=f"اتجاه البحر: {coast['sn']}°"
    ).add_to(m)

    folium.Marker(
        [spot['lat'], spot['lon']],
        popup=f"<b>{spot['name']}</b><br>🎯 {score}/10",
        tooltip=f"{spot['name']} — {score}/10",
        icon=folium.Icon(color="red" if score < 5 else ("green" if score >= 7 else "orange"),
                         icon="anchor", prefix="fa")
    ).add_to(m)

    st_folium(m, width=None, height=400)

    # ─── زر العودة ───
    if st.button("🔙 عودة لقائمة السبوتات", use_container_width=True):
        del st.session_state.selected_spot
        st.rerun()

# ─── إذا لم يكن عندو scan results ───
if 'selected_spot' not in st.session_state and not st.session_state.scan_results:
    st.info("👆 انقر على سبوت لأحصل على تقرير مفصل")

st.caption("© مستشار الصيد AI v10.0 | الكلمة الأولى والأخيرة")
