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
# 1. CONFIG & SETUP
# ══════════════════════════════════════════════════════════════
st.set_page_config(page_title="مستشار الصيد AI | v10.0", page_icon="🎣", layout="wide")

st.markdown("""
<style>
    body{direction:rtl; font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;}
    .go-box{background:#0a3d0a;padding:22px;border-radius:12px;border:3px solid #00ff00;box-shadow: 0 4px 15px rgba(0,255,0,0.2);}
    .warn-box{background:#3d2e0a;padding:22px;border-radius:12px;border:3px solid #ffa500;}
    .nogo-box{background:#3d0a0a;padding:22px;border-radius:12px;border:3px solid #ff0000;box-shadow: 0 4px 15px rgba(255,0,0,0.2);}
    .top-spot{background:#0a1a2e;padding:16px;border-radius:10px;border:2px solid #1f77b4;margin:8px 0;transition: transform 0.2s;}
    .top-spot:hover{transform: scale(1.02);}
    .metric-card{background:#111;padding:15px;border-radius:8px;border-right:4px solid #1f77b4;text-align:center;}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# 2. STATE & DATABASE
# ══════════════════════════════════════════════════════════════
if "lat" not in st.session_state: st.session_state.lat = 36.8333
if "lon" not in st.session_state: st.session_state.lon = 11.1000
if "day_offset" not in st.session_state: st.session_state.day_offset = 1

SPOTS = [
    {"name": "رأس الدرك", "lat": 37.2742, "lon": 9.8739, "region": "بنزرت"},
    {"name": "الهوارية", "lat": 37.0539, "lon": 11.0581, "region": "نابل"},
    {"name": "قليبية", "lat": 36.8333, "lon": 11.1000, "region": "نابل"},
    {"name": "غار الملح", "lat": 37.1728, "lon": 10.0872, "region": "بنزرت"},
    {"name": "رفراف", "lat": 37.1889, "lon": 10.1833, "region": "بنزرت"},
    {"name": "الحمامات", "lat": 36.4000, "lon": 10.6167, "region": "نابل"},
    {"name": "سوسة بوجعفر", "lat": 35.8256, "lon": 10.6369, "region": "سوسة"},
    {"name": "المنستير", "lat": 35.7672, "lon": 10.8111, "region": "المنستير"},
    {"name": "المهدية", "lat": 35.5047, "lon": 11.0622, "region": "المهدية"},
    {"name": "صفاقس رأس الطابية", "lat": 34.7333, "lon": 10.7633, "region": "صفاقس"},
    {"name": "قابس", "lat": 33.8815, "lon": 10.0982, "region": "قابس"},
    {"name": "جرجيس", "lat": 33.5042, "lon": 10.8681, "region": "مدنين"},
    {"name": "جربة أجيم", "lat": 33.7167, "lon": 10.7667, "region": "جربة"},
]

# ══════════════════════════════════════════════════════════════
# 3. MATH & PHYSICS ENGINE
# ══════════════════════════════════════════════════════════════
def destination_point(lat, lon, bearing, dist_km):
    R = 6371.0; b = math.radians(bearing)
    φ1, λ1 = math.radians(lat), math.radians(lon)
    φ2 = math.asin(math.sin(φ1)*math.cos(dist_km/R) + math.cos(φ1)*math.sin(dist_km/R)*math.cos(b))
    λ2 = λ1 + math.atan2(math.sin(b)*math.sin(dist_km/R)*math.cos(φ1), math.cos(dist_km/R) - math.sin(φ1)*math.sin(φ2))
    return math.degrees(φ2), math.degrees(λ2)

def circular_mean(angles):
    if not angles: return 0.0
    s = sum(math.sin(math.radians(a)) for a in angles)/len(angles)
    c = sum(math.cos(math.radians(a)) for a in angles)/len(angles)
    return math.degrees(math.atan2(s,c)) % 360

def angle_diff(a, b):
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d

def moon_factor(d: date):
    delta = (d - date(2024, 1, 11)).days % 29.53
    return round(0.5 + 0.5 * abs(math.cos(2 * math.pi * delta / 29.53)), 3)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1); dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return 2 * R * math.asin(math.sqrt(a))

# ══════════════════════════════════════════════════════════════
# 4. API FETCHERS (Cached)
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def analyze_coast(lat, lon):
    points = [destination_point(lat, lon, b, 3.0) for b in range(0, 360, 30)]
    lats = ",".join(str(round(p[0],4)) for p in points)
    lons = ",".join(str(round(p[1],4)) for p in points)
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation", params={"latitude":lats, "longitude":lons}, timeout=10).json()
        elevs = r.get("elevation", [])
        sea_b = [b for b, e in zip(range(0,360,30), elevs) if e is not None and e <= 0.5]
        if not sea_b: return None, "موقع بري (Inland)"
        sn = circular_mean(sea_b)
        exp = len(sea_b)/12.0
        bay = max(0.0, 1.0 - exp)
        coast_type = "ساحل مفتوح" if exp > 0.65 else ("خليج" if exp <= 0.4 else "ساحل عادي")
        return {"sn": round(sn,1), "exposure": exp, "bay_factor": bay, "type": coast_type}, None
    except Exception as e: return None, f"خطأ الخرائط: {e}"

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_meteo_data(lat, lon):
    try:
        marine = requests.get("https://marine-api.open-meteo.com/v1/marine", params={
            "latitude": lat, "longitude": lon,
            "hourly": "wave_height,wave_direction,wave_period,wind_wave_height,wind_wave_direction,wind_wave_period,swell_wave_height,swell_wave_direction,swell_wave_period,sea_surface_temperature",
            "past_days": 2, "forecast_days": 3, "timezone": "auto"
        }, timeout=15).json()
        weather = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon,
            "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,visibility",
            "past_days": 2, "forecast_days": 3, "timezone": "auto"
        }, timeout=15).json()
        return marine, weather, None
    except Exception as e: return None, None, str(e)

def get_val(data, key, idx, default=0.0):
    arr = data['hourly'].get(key, [])
    if idx < len(arr) and arr[idx] is not None:
        try: return float(arr[idx])
        except: return default
    return default

# ══════════════════════════════════════════════════════════════
# 5. DEEP ANALYSIS ENGINE
# ══════════════════════════════════════════════════════════════
def run_deep_scan(lat, lon, target_date):
    coast, err = analyze_coast(lat, lon)
    if err: return None, err
    marine, weather, err = fetch_meteo_data(lat, lon)
    if err: return None, err

    times = weather['hourly']['time']
    target_start = datetime.combine(target_date, datetime.min.time())
    past_start = target_start - timedelta(hours=48)
    
    # 1. Past 48h Legacy
    p_wwh, p_wwp, p_swh, p_swp = [], [], [], []
    for i, t in enumerate(times):
        dt = datetime.fromisoformat(t)
        if past_start <= dt < target_start:
            p_wwh.append(get_val(marine, 'wind_wave_height', i))
            p_wwp.append(get_val(marine, 'wind_wave_period', i))
            p_swh.append(get_val(marine, 'swell_wave_height', i))
            p_swp.append(get_val(marine, 'swell_wave_period', i))
            
    avg_wwh = sum(p_wwh)/len(p_wwh) if p_wwh else 0.0
    avg_wwp = sum(p_wwp)/len(p_wwp) if p_wwp else 0.0
    is_dirty = (avg_wwh > 1.0) and (avg_wwp < 6.5)

    # 2. Hourly Physics
    hourly = []
    red_flags = set()
    total_score = 0.0; weights = 0.0
    sn = coast['sn']

    for i, t in enumerate(times):
        dt = datetime.fromisoformat(t)
        if dt.date() != target_date: continue
        
        ws = get_val(weather, 'wind_speed_10m', i)
        wg = get_val(weather, 'wind_gusts_10m', i)
        wd = get_val(weather, 'wind_direction_10m', i)
        rn = get_val(weather, 'precipitation', i)
        w_h = get_val(marine, 'wave_height', i)
        w_d = get_val(marine, 'wave_direction', i)
        sw_h = get_val(marine, 'swell_wave_height', i)
        sw_p = get_val(marine, 'swell_wave_period', i)
        sst = get_val(marine, 'sea_surface_temperature', i, 18.0)
        
        ws_eff = max(ws, wg * 0.7)
        wdir_going = (wd + 180) % 360
        wind_diff = angle_diff(wdir_going, sn)
        wave_diff = angle_diff(w_d, sn)
        
        # Longshore Current (v = 1.17 * sqrt(9.81*H) * sin(a)cos(a))
        rad = math.radians(wave_diff)
        v_ls = 1.17 * math.sqrt(9.81 * w_h) * math.sin(rad) * math.cos(rad) if wave_diff > 10 else 0.0
        v_kmh = (v_ls + (ws_eff * 0.015)) * 3.6

        # Score Calculation
        h_score = 10.0
        
        if wind_diff <= 45: 
            wind_type = "وش 🟢"; h_score += 1.5 if 8 <= ws_eff <= 25 else -0.5
        elif wind_diff >= 135: 
            wind_type = "بر 🔵"; h_score += 1.0 if ws_eff <= 15 else -1.5
        else: 
            wind_type = "جانبي 🟠"; h_score -= 1.0 if ws_eff <= 20 else -3.0

        if w_h < 0.3: h_score -= 3.0
        if ws_eff > 50: h_score -= 5.0; red_flags.add("ريح عنيفة (>50 كم/س)")
        if v_kmh > 2.0: h_score -= 3.0; red_flags.add("تيار ساحب/جانبي خطير")
        if rn > 2.0: h_score -= 1.5
        if sst < 15: h_score -= 1.5

        if is_dirty and sw_p < 8.0: h_score -= 2.0; red_flags.add("بحر مدرر من أيام سابقة")
        elif sw_p >= 9.0 and sw_h > 0.4: h_score += 1.5 # Clean Swell cleaning

        # Lead
        if v_kmh > 1.8: lead = "سبايك 140g"
        elif v_kmh > 1.0: lead = "هرمي 120g"
        else: lead = "زيتوني 100g"

        h_score = max(0.0, min(10.0, h_score))
        
        w = 2.5 if dt.hour in [4,5,6,7,8, 17,18,19,20,21,22,23] else 1.0
        total_score += h_score * w
        weights += w

        hourly.append({
            "time": t[-5:], "hour": dt.hour, "score": round(h_score,1),
            "wind": round(ws_eff,1), "wind_type": wind_type, "wave": round(w_h,2),
            "swell_p": round(sw_p,1), "ls_kmh": round(v_kmh,2), "lead": lead, "sst": round(sst,1)
        })

    final_score = round(total_score / weights, 1) if weights else 0.0
    moon = moon_factor(target_date)
    final_score = min(10.0, final_score + max(0, (moon - 0.55)*1.5))
    
    confidence = 95 - (len(red_flags) * 15)
    best_hour = max(hourly, key=lambda x: x["score"])

    return {
        "final_score": final_score,
        "confidence": max(30, confidence),
        "red_flags": list(red_flags),
        "coast": coast,
        "past": {"dirty": is_dirty, "avg_wwh": round(avg_wwh,2)},
        "hourly": hourly,
        "best_hour": best_hour,
        "moon": moon
    }, None

# ══════════════════════════════════════════════════════════════
# 6. AI SCOUT (Fast Parallel Scanner)
# ══════════════════════════════════════════════════════════════
def fast_scan(spot, target_date):
    marine, weather, err = fetch_meteo_data(spot['lat'], spot['lon'])
    if err: return spot, 0.0
    times = weather['hourly']['time']
    scores = []
    for i, t in enumerate(times):
        if datetime.fromisoformat(t).date() == target_date:
            ws = get_val(weather, 'wind_speed_10m', i)
            wh = get_val(marine, 'wave_height', i)
            sc = 10.0
            if wh < 0.2: sc -= 4.0
            if ws > 45: sc -= 5.0
            scores.append(sc)
    avg = sum(scores)/len(scores) if scores else 0.0
    return spot, round(avg, 1)

@st.cache_data(ttl=3600, show_spinner=False)
def scan_tunisia(target_date):
    results = []
    with ThreadPoolExecutor(max_workers=4) as ex:
        futures = [ex.submit(fast_scan, s, target_date) for s in SPOTS]
        for f in as_completed(futures):
            spot, score = f.result()
            results.append({"name": spot['name'], "region": spot['region'], "lat": spot['lat'], "lon": spot['lon'], "score": score})
    return sorted(results, key=lambda x: x['score'], reverse=True)

# ══════════════════════════════════════════════════════════════
# 7. GEMINI AI REPORT (الكلمة الأخيرة)
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=1800, show_spinner=False)
def generate_ai_report(analysis, alt_spots, target_date):
    key = os.environ.get("GEMINI_API_KEY")
    if not key: return "❌ مفتاح API مفقود (GEMINI_API_KEY)"
    try:
        genai.configure(api_key=key)
        model = genai.GenerativeModel('gemini-1.5-flash', generation_config={"temperature":0.1})
        prompt = f"""
أنت خبير صيد تونسي محترف وحاسم.
📅 يوم الصيد: {target_date}
📍 سكور السبوت الحالي: {analysis['final_score']}/10 | ثقة: {analysis['confidence']}%
🚩 مشاكل (Red Flags): {analysis['red_flags']}
🌊 حالة البحر السابقة: {'مدرر' if analysis['past']['dirty'] else 'نظيف'}

💡 بدائل أفضل: {alt_spots}

اكتب تقرير حاسم بالدارجة التونسية:
1. تقييم صارم لاختيار المستخدم.
2. هل يذهب إلى موقعه أم يغير إلى بديل؟ (حاسم: GO أو NO-GO)
3. التكتيك: نوع الرصاص، الوقت الذهبي، وتأثير التيارات.
"""
        return model.generate_content(prompt).text
    except Exception as e: return f"خطأ الذكاء الاصطناعي: {e}"

# ══════════════════════════════════════════════════════════════
# 8. UI & INTERACTION
# ══════════════════════════════════════════════════════════════
st.title("🤖 مستشار الصيد AI | v10.0")
st.markdown("**الكلمة الأولى للـ AI، والقرار الأخير حاسم مبني على الفيزياء.**")

# 8.1 Date Selector
col_d1, col_d2, col_d3 = st.columns(3)
if col_d1.button("🟢 اليوم", use_container_width=True): st.session_state.day_offset = 0
if col_d2.button("🟡 غداً", use_container_width=True): st.session_state.day_offset = 1
if col_d3.button("🔵 بعد غد", use_container_width=True): st.session_state.day_offset = 2

target_date = date.today() + timedelta(days=st.session_state.day_offset)
day_name = ["اليوم", "غداً", "بعد غد"][st.session_state.day_offset]
st.info(f"📅 **يوم التحليل:** {day_name} ({target_date})")

# 8.2 AI Scout (Auto Scan)
st.markdown("---")
col_map, col_scout = st.columns([2, 1])

with col_scout:
    st.markdown("### 🏆 الكلمة الأولى (AI Scout)")
    with st.spinner("🔍 جاري مسح سواحل تونس..."):
        scout_results = scan_tunisia(target_date)
    
    for i, s in enumerate(scout_results[:4], 1):
        color = "#0f0" if s['score']>=7 else "#ff0" if s['score']>=5 else "#f44"
        st.markdown(f"""
        <div class='top-spot'>
        <b>{i}. {s['name']}</b> ({s['region']})<br>
        🎯 <span style='color:{color}; font-size:1.2em; font-weight:bold'>{s['score']}/10</span>
        </div>
        """, unsafe_allow_html=True)

# 8.3 Interactive Map
with col_map:
    st.markdown("### 🗺️ حرّك الخريطة وانقر لتثبيت المرساة")
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=9, tiles="CartoDB dark_matter")
    
    # Adding the anchor
    folium.Marker(
        [st.session_state.lat, st.session_state.lon],
        icon=folium.Icon(color="red", icon="crosshairs", prefix="fa"),
        tooltip="موقع الصيد المختار"
    ).add_to(m)
    
    # Adding Top Spots as small dots
    for s in scout_results[:4]:
        folium.CircleMarker([s['lat'], s['lon']], radius=5, color="lime", fill=True, tooltip=f"{s['name']}: {s['score']}").add_to(m)

    map_data = st_folium(m, width=None, height=400, returned_objects=["last_clicked"])
    
    # Update coordinates if user clicks
    if map_data and map_data.get("last_clicked"):
        new_lat = map_data["last_clicked"]["lat"]
        new_lon = map_data["last_clicked"]["lng"]
        if abs(new_lat - st.session_state.lat) > 0.0001:
            st.session_state.lat, st.session_state.lon = new_lat, new_lon
            st.rerun()

    st.markdown(f"📍 **إحداثيات المرساة:** `{st.session_state.lat:.4f}, {st.session_state.lon:.4f}`")

# 8.4 Deep Scan Action
st.markdown("---")
if st.button("⚡ إجراء مسح فيزيائي عميق للمرساة (Deep Scan)", type="primary", use_container_width=True):
    with st.spinner("⚙️ يقرأ الإحداثيات، يحلل 48 ساعة سابقة، ويحسب الفيزياء..."):
        analysis, err = run_deep_scan(st.session_state.lat, st.session_state.lon, target_date)
        
    if err: st.error(err)
    else:
        # Display Verdict
        score = analysis['final_score']
        conf = analysis['confidence']
        
        st.markdown("## ⚖️ الكلمة الأخيرة للذكاء الاصطناعي")
        
        if score >= 7.0 and conf >= 70:
            st.markdown(f"<div class='go-box'><h2 style='color:#0f0;text-align:center'>✅ GO — موقع ممتاز</h2><h3 style='text-align:center'>السكور: {score}/10 | الثقة: {conf}%</h3></div>", unsafe_allow_html=True)
        elif score >= 5.0:
            st.markdown(f"<div class='warn-box'><h2 style='color:#fa0;text-align:center'>🟡 مقبول (بحذر)</h2><h3 style='text-align:center'>السكور: {score}/10 | الثقة: {conf}%</h3></div>", unsafe_allow_html=True)
        else:
            st.markdown(f"<div class='nogo-box'><h2 style='color:#f44;text-align:center'>🔴 NO-GO — مرفوض تماماً</h2><h3 style='text-align:center'>السكور: {score}/10 | الثقة: {conf}%</h3></div>", unsafe_allow_html=True)
            
        # Display Metrics
        c1, c2, c3, c4 = st.columns(4)
        c1.markdown(f"<div class='metric-card'>⭐ أفضل ساعة<br><b>{analysis['best_hour']['time']}</b></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='metric-card'>🌊 تيار ساحب<br><b>{analysis['best_hour']['ls_kmh']} كم/س</b></div>", unsafe_allow_html=True)
        c3.markdown(f"<div class='metric-card'>⚖️ الرصاص الموصى به<br><b>{analysis['best_hour']['lead']}</b></div>", unsafe_allow_html=True)
        c4.markdown(f"<div class='metric-card'>🌙 عامل القمر<br><b>{int(analysis['moon']*100)}%</b></div>", unsafe_allow_html=True)

        if analysis['red_flags']:
            st.error(f"🚩 **تحذيرات حاسمة:** {', '.join(analysis['red_flags'])}")

        # Gemini Report
        st.markdown("---")
        st.markdown("### 🧠 تقرير الخبير (Gemini AI)")
        alt_spots = [{"اسم": s['name'], "سكور": s['score']} for s in scout_results[:3] if s['score'] > score]
        
        with st.spinner("يكتب التقرير التكتيكي..."):
            report = generate_ai_report(analysis, alt_spots, target_date)
            st.markdown(f"<div style='background:#1a2639; padding:20px; border-radius:10px; border-right:5px solid #00f;'>{report}</div>", unsafe_allow_html=True)

        # Hourly Data Table
        with st.expander("📊 عرض الجدول الزمني المفصل", expanded=False):
            df = pd.DataFrame(analysis['hourly'])
            st.dataframe(df[["time", "score", "wind_type", "wind", "wave", "swell_p", "ls_kmh", "lead", "sst"]], use_container_width=True)

st.caption("© Fishing Advisor AI | v10.0 Extended | تونس 🇹🇳")
