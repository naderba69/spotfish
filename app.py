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
st.set_page_config(page_title="مستشار الصيد AI | تونس", page_icon="🎣",
                   layout="wide", initial_sidebar_state="collapsed")

st.markdown("""
<style>
  body{direction:rtl}
  .block-container{padding-top:1rem}
  .go-box{background:#0a3d0a;padding:18px;border-radius:10px;border:2px solid #00ff00}
  .nogo-box{background:#3d0a0a;padding:18px;border-radius:10px;border:2px solid #ff0000}
  .warn-box{background:#3d2e0a;padding:18px;border-radius:10px;border:2px solid #ffa500}
  .spot-card{background:#0a1a2e;padding:14px;border-radius:8px;border:1px solid #1f77b4;margin-bottom:10px}
  .top-spot{background:#0a3d0a;padding:16px;border-radius:10px;border:2px solid #0f0;margin:8px 0}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# 2. FAMOUS SPOTS DATABASE (قاعدة بيانات السبوتات)
# ══════════════════════════════════════════════════════════════
SPOTS_DATABASE = [
    {"name": "رأس الدرك", "lat": 37.2742, "lon": 9.8739, "region": "بنزرت"},
    {"name": "الهوارية", "lat": 37.0539, "lon": 11.0581, "region": "نابل"},
    {"name": "قليبية", "lat": 36.8333, "lon": 11.1, "region": "نابل"},
    {"name": "المنستير الشاطئ", "lat": 35.7672, "lon": 10.8111, "region": "المنستير"},
    {"name": "المهدية الكورنيش", "lat": 35.5047, "lon": 11.0622, "region": "المهدية"},
    {"name": "صفاقس رأس الطابية", "lat": 34.7333, "lon": 10.7633, "region": "صفاقس"},
    {"name": "قابس الشاطئ", "lat": 33.8815, "lon": 10.0982, "region": "قابس"},
    {"name": "جرجيس", "lat": 33.5042, "lon": 10.8681, "region": "مدنين"},
    {"name": "جربة أجيم", "lat": 33.7167, "lon": 10.7667, "region": "جربة"},
    {"name": "قرقنة", "lat": 34.7333, "lon": 11.1167, "region": "صفاقس"},
    {"name": "بنزرت المرسى", "lat": 37.2744, "lon": 9.8628, "region": "بنزرت"},
    {"name": "غار الملح", "lat": 37.1728, "lon": 10.0872, "region": "بنزرت"},
    {"name": "رفراف الشاطئ", "lat": 37.1889, "lon": 10.1833, "region": "بنزرت"},
    {"name": "الحمامات", "lat": 36.4, "lon": 10.6167, "region": "نابل"},
    {"name": "سوسة بوجعفر", "lat": 35.8256, "lon": 10.6369, "region": "سوسة"},
]

# ══════════════════════════════════════════════════════════════
# 3. HELPERS (نفس الدوال السابقة)
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

# ══════════════════════════════════════════════════════════════
# 4. API CALLS (مع cache)
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def analyze_coast(lat, lon):
    points = [destination_point(lat, lon, b, 3.0) for b in range(0, 360, 30)]
    lats = ",".join(str(round(p[0], 4)) for p in points)
    lons = ",".join(str(round(p[1], 4)) for p in points)
    try:
        r = requests.get("https://api.open-meteo.com/v1/elevation",
                         params={"latitude": lats, "longitude": lons}, timeout=15)
        r.raise_for_status()
        elevs = r.json().get("elevation", [])
    except:
        return None, "error"

    sea_bearings = [b for (_, _), b, e in
                    zip(points, range(0, 360, 30), elevs)
                    if e is not None and e <= 0.5]
    if not sea_bearings:
        return None, "inland"

    exposure = len(sea_bearings) / len(points)
    sn = circular_mean(sea_bearings)
    return {"sn": round(sn, 1), "exposure": round(exposure, 2)}, None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_data(lat, lon):
    try:
        marine = requests.get("https://marine-api.open-meteo.com/v1/marine", params={
            "latitude": lat, "longitude": lon,
            "hourly": "wave_height,wave_direction,wave_period,wind_wave_height,wind_wave_period,swell_wave_height,swell_wave_period,sea_surface_temperature",
            "past_days": 2, "forecast_days": 3, "timezone": "auto"
        }, timeout=20).json()

        weather = requests.get("https://api.open-meteo.com/v1/forecast", params={
            "latitude": lat, "longitude": lon,
            "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation",
            "past_days": 2, "forecast_days": 3, "timezone": "auto"
        }, timeout=20).json()
        return marine, weather, None
    except Exception as e:
        return None, None, str(e)

def get_hourly_value(data, key, idx, default=0.0):
    arr = data['hourly'].get(key, [])
    if idx < len(arr) and arr[idx] is not None:
        try: return float(arr[idx])
        except: return default
    return default

# ══════════════════════════════════════════════════════════════
# 5. SCORING ENGINE (مختصر لسرعة الفحص)
# ══════════════════════════════════════════════════════════════
def quick_score_spot(lat, lon, target_date):
    """حساب سريع لسكور سبوت واحد"""
    coast, err = analyze_coast(lat, lon)
    if err: return 0.0
    
    marine, weather, err = fetch_data(lat, lon)
    if err: return 0.0
    
    times = weather['hourly']['time']
    scores = []
    
    for i, t in enumerate(times):
        try: t_obj = datetime.fromisoformat(t)
        except: continue
        if t_obj.date() != target_date: continue
        
        score = 10.0
        ws = get_hourly_value(weather, 'wind_speed_10m', i)
        wdir = get_hourly_value(weather, 'wind_direction_10m', i)
        gust = get_hourly_value(weather, 'wind_gusts_10m', i)
        wh = get_hourly_value(marine, 'wave_height', i)
        wd = get_hourly_value(marine, 'wave_direction', i)
        sst = get_hourly_value(marine, 'sea_surface_temperature', i, 18)
        
        ws_eff = max(ws, gust * 0.7)
        wdir_going = (wdir + 180) % 360
        diff = angle_diff(wdir_going, coast['sn'])
        
        # Wind bonus/penalty
        if diff <= 45: score += 1.5 if 8 <= ws_eff <= 25 else -0.5
        elif diff >= 135: score += 1.0 if ws_eff <= 15 else -1.5
        else: score -= 1.0
        
        # Wave
        if wh < 0.3: score -= 3.0
        
        # Wind strength
        if ws_eff > 55: score -= 5.0
        elif ws_eff > 42: score -= 3.0
        elif ws_eff > 32: score -= 1.5
        
        # SST
        if sst < 15: score -= 2.0
        elif 19 <= sst <= 24: score += 0.5
        
        score = max(0, min(10, score))
        scores.append(score)
    
    if not scores: return 0.0
    
    # Weighted (prime hours)
    prime = set(range(17, 24)) | set(range(4, 9))
    tw, ts = 0.0, 0.0
    for i, s in enumerate(scores):
        hour = (i + 4) % 24  # تقريبي
        w = 2.5 if hour in prime else 1.0
        ts += s * w
        tw += w
    
    return round(ts / tw if tw else 0, 1)

# ══════════════════════════════════════════════════════════════
# 6. AI SCOUT — الكلمة الأولى
# ══════════════════════════════════════════════════════════════
def scan_all_spots(target_date):
    """فحص جميع السبوتات بشكل متوازي"""
    results = []
    
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = {
            executor.submit(quick_score_spot, spot['lat'], spot['lon'], target_date): spot
            for spot in SPOTS_DATABASE
        }
        
        for future in as_completed(futures):
            spot = futures[future]
            try:
                score = future.result()
                results.append({
                    "name": spot['name'],
                    "region": spot['region'],
                    "lat": spot['lat'],
                    "lon": spot['lon'],
                    "score": score,
                })
            except:
                pass
    
    # ترتيب تنازلي
    results.sort(key=lambda x: x['score'], reverse=True)
    return results

# ══════════════════════════════════════════════════════════════
# 7. UI — الواجهة الجديدة
# ══════════════════════════════════════════════════════════════
st.title("🤖 مستشار الصيد AI | الكلمة الأولى والأخيرة")
st.markdown("**v9.0 — AI Scout: النظام يختار أفضل السبوتات تلقائياً**")

# اختيار اليوم
st.markdown("### 📅 1) اختر اليوم")
col1, col2, col3 = st.columns(3)
with col1:
    if st.button("🔵 اليوم", use_container_width=True):
        st.session_state.day_offset = 0
with col2:
    if st.button("🟢 غداً", use_container_width=True):
        st.session_state.day_offset = 1
with col3:
    if st.button("🟡 بعد غد", use_container_width=True):
        st.session_state.day_offset = 2

if 'day_offset' not in st.session_state:
    st.session_state.day_offset = 1

target_date = date.today() + timedelta(days=st.session_state.day_offset)
day_names = {0: "اليوم", 1: "غداً", 2: "بعد غد"}
st.info(f"📆 **{day_names[st.session_state.day_offset]}** — {target_date.strftime('%Y-%m-%d')}")

st.divider()

# ══════════════════════════════════════════════════════════════
# 8. AI SCOUT — الفحص التلقائي
# ══════════════════════════════════════════════════════════════
st.markdown("### 🤖 الكلمة الأولى: AI يفحص تونس كلها...")

if st.button("🚀 ابدأ الفحص الذكي", type="primary", use_container_width=True):
    with st.spinner(f"🔍 فحص {len(SPOTS_DATABASE)} سبوت..."):
        results = scan_all_spots(target_date)
        st.session_state.scan_results = results
        st.session_state.scanned = True
        st.success("✅ انتهى الفحص!")

if 'scanned' in st.session_state and st.session_state.scanned:
    results = st.session_state.scan_results
    
    st.markdown("### 🏆 أفضل 5 سبوتات (حسب AI)")
    
    top5 = results[:5]
    for i, spot in enumerate(top5, 1):
        emoji = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "⭐"
        color = "#0f0" if spot['score'] >= 7 else "#ff0" if spot['score'] >= 5 else "#fa0"
        
        st.markdown(f"""
        <div class='top-spot'>
        {emoji} <b style='font-size:1.2em'>{spot['name']}</b> — {spot['region']}<br>
        🎯 السكور: <b style='color:{color};font-size:1.3em'>{spot['score']}/10</b><br>
        📍 {spot['lat']:.4f}, {spot['lon']:.4f}
        </div>
        """, unsafe_allow_html=True)
    
    st.divider()
    
    # الخريطة التفاعلية
    st.markdown("### 🗺️ خريطة السبوتات (اللون = الجودة)")
    m = folium.Map(location=[36.0, 9.5], zoom_start=7, tiles="CartoDB dark_matter")
    
    for spot in results:
        if spot['score'] >= 7: color = 'green'
        elif spot['score'] >= 5: color = 'orange'
        else: color = 'red'
        
        folium.Marker(
            [spot['lat'], spot['lon']],
            popup=f"{spot['name']}<br>🎯 {spot['score']}/10",
            tooltip=f"{spot['name']} — {spot['score']}/10",
            icon=folium.Icon(color=color, icon='anchor', prefix='fa')
        ).add_to(m)
    
    st_folium(m, width=None, height=500, key="scout_map")
    
    st.divider()
    
    # الجدول الكامل
    st.markdown("### 📊 كل السبوتات مرتبة")
    df = pd.DataFrame(results)
    df_show = df[['name', 'region', 'score', 'lat', 'lon']].copy()
    df_show.columns = ['الاسم', 'المنطقة', 'السكور', 'Lat', 'Lon']
    
    def color_score(v):
        if v >= 7: return 'background:#0a3d0a;color:#0f0'
        elif v >= 5: return 'background:#3d3d0a;color:#ff0'
        elif v >= 4: return 'background:#3d2e0a;color:#fa0'
        else: return 'background:#3d0a0a;color:#f44'
    
    styled = df_show.style.applymap(color_score, subset=['السكور'])
    st.dataframe(styled, use_container_width=True, hide_index=True)
    
    st.divider()
    
    # ══════════════════════════════════════════════════════════════
    # 9. الكلمة الأخيرة
    # ══════════════════════════════════════════════════════════════
    st.markdown("### ⚖️ الكلمة الأخيرة: مقارنة اختيارك")
    
    user_lat = st.number_input("📍 Latitude (اختيارك)", value=36.4561, format="%.5f")
    user_lon = st.number_input("📍 Longitude (اختيارك)", value=10.7376, format="%.5f")
    
    if st.button("🔍 قيّم اختياري", use_container_width=True):
        with st.spinner("⚡ تقييم موقعك..."):
            user_score = quick_score_spot(user_lat, user_lon, target_date)
            
            st.markdown(f"### 🎯 سكور موقعك: **{user_score}/10**")
            
            if user_score >= 7:
                st.markdown(f"""<div class='go-box'>
                <h2 style='color:#0f0;text-align:center'>✅ اختيار ممتاز!</h2>
                <p style='text-align:center'>موقعك من أفضل الخيارات اليوم</p>
                </div>""", unsafe_allow_html=True)
            
            elif user_score >= 5:
                st.markdown(f"""<div class='warn-box'>
                <h2 style='color:#ff0;text-align:center'>🟡 مقبول لكن...</h2>
                </div>""", unsafe_allow_html=True)
                
                # اقتراح بدائل
                better = [s for s in results if s['score'] > user_score][:3]
                if better:
                    st.markdown("#### 💡 AI يقترح بدائل أفضل:")
                    for b in better:
                        diff = round(b['score'] - user_score, 1)
                        st.markdown(f"""
                        <div class='spot-card'>
                        ✨ <b>{b['name']}</b> — {b['region']}<br>
                        🎯 {b['score']}/10 (<span style='color:#0f0'>+{diff} نقطة</span>)<br>
                        📍 {b['lat']:.4f}, {b['lon']:.4f}
                        </div>
                        """, unsafe_allow_html=True)
            
            else:
                st.markdown(f"""<div class='nogo-box'>
                <h2 style='color:#f44;text-align:center'>🔴 اختيار سيء!</h2>
                </div>""", unsafe_allow_html=True)
                
                st.markdown("#### ⚠️ AI يرفض هذا السبوت ويقترح:")
                for b in results[:3]:
                    diff = round(b['score'] - user_score, 1)
                    st.markdown(f"""
                    <div class='top-spot'>
                    ⭐ <b>{b['name']}</b> — {b['region']}<br>
                    🎯 {b['score']}/10 (<span style='color:#0f0'>+{diff} نقاط</span>)<br>
                    📍 {b['lat']:.4f}, {b['lon']:.4f}
                    </div>
                    """, unsafe_allow_html=True)

else:
    st.info("👆 انقر على زر 'ابدأ الفحص الذكي' لكي يفحص AI كل السبوتات التونسية")

st.caption("© مستشار الصيد AI v9.0 | الكلمة الأولى والأخيرة للذكاء الاصطناعي")
