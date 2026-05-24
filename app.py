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
TUNIS_TZ     = ZoneInfo("Africa/Tunis")
USER_AGENT   = "TunisiaFishingAdvisor/10.8"
GEMINI_MODEL = "gemini-2.5-flash"

st.set_page_config(
    page_title="🎣 مستشار الصيد الفيزيائي | تونس",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
body{direction:rtl; text-align:right;}
.block-container{padding-top:.5rem}
.go-box{background:linear-gradient(135deg,#0a3d0a,#0d520d); padding:18px;border-radius:10px;border:2px solid #00ff00;margin:10px 0; color:white; text-align:center;}
.warn-box{background:linear-gradient(135deg,#3d2e0a,#52400d); padding:18px;border-radius:10px;border:2px solid #ffa500;margin:10px 0; color:white; text-align:center;}
.nogo-box{background:linear-gradient(135deg,#3d0a0a,#520d0d); padding:18px;border-radius:10px;border:2px solid #ff0000;margin:10px 0; color:white; text-align:center;}
.spot-card{background:#0a1a2e;padding:12px;border-radius:8px; border:1px solid #1f77b4;margin-bottom:6px; color:white;}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# 2. SESSION STATE
# ══════════════════════════════════════════════════════════════
if "lat" not in st.session_state: st.session_state.lat = 36.8333
if "lon" not in st.session_state: st.session_state.lon = 11.1000
if "day_offset" not in st.session_state: st.session_state.day_offset = 1
if "deep_result" not in st.session_state: st.session_state.deep_result = None

# ══════════════════════════════════════════════════════════════
# 3. SPOTS & MATH
# ══════════════════════════════════════════════════════════════
SPOTS = [
    {"name": "طبرقة", "lat": 36.9544, "lon": 8.7578, "region": "جندوبة"},
    {"name": "رأس أنجلة", "lat": 37.3470, "lon": 9.7440, "region": "بنزرت"},
    {"name": "قليبية", "lat": 36.8333, "lon": 11.1000, "region": "نابل"},
    {"name": "الهوارية", "lat": 37.0539, "lon": 11.0581, "region": "نابل"},
    {"name": "المهدية", "lat": 35.5047, "lon": 11.0622, "region": "المهدية"},
    {"name": "جرجيس", "lat": 33.5042, "lon": 10.8681, "region": "مدنين"},
]

def safe_avg(lst): return sum(lst)/len(lst) if lst else 0.0
def angle_diff_180(a, b):
    d = abs(a-b) % 360
    return d if d <= 180 else 360-d

def circular_mean(angles):
    if not angles: return 0.0
    s = sum(math.sin(math.radians(a)) for a in angles)/len(angles)
    c = sum(math.cos(math.radians(a)) for a in angles)/len(angles)
    return math.degrees(math.atan2(s,c)) % 360

def moon_phase_factor(d):
    delta = (d - date(2024,1,11)).days % 29.53
    return round(0.5+0.5*abs(math.cos(2*math.pi*delta/29.53)), 3)

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat, dlon = math.radians(lat2-lat1), math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return round(2*R*math.asin(math.sqrt(a)), 1)

def destination_point(lat1, lon1, bearing, dist):
    R = 6371.0; b = math.radians(bearing)
    p1, l1 = math.radians(lat1), math.radians(lon1)
    p2 = math.asin(math.sin(p1)*math.cos(dist/R)+math.cos(p1)*math.sin(dist/R)*math.cos(b))
    l2 = l1+math.atan2(math.sin(b)*math.sin(dist/R)*math.cos(p1),math.cos(dist/R)-math.sin(p1)*math.sin(p2))
    return math.degrees(p2), math.degrees(l2)

def fmt_date_ar(d):
    days = ["الاثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت","الأحد"]
    months = {1:"جانفي",2:"فيفري",3:"مارس",4:"أفريل",5:"ماي",6:"جوان",7:"جويلية",8:"أوت",9:"سبتمبر",10:"أكتوبر",11:"نوفمبر",12:"ديسمبر"}
    return f"{days[d.weekday()]} {d.day} {months[d.month]} {d.year}"

# ══════════════════════════════════════════════════════════════
# 4. DATA FETCHING
# ══════════════════════════════════════════════════════════════
def get_json(url, params):
    r = requests.get(url, params=params, timeout=15, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.json()

@st.cache_data(ttl=86400)
def analyze_coast(lat, lon):
    pts = [destination_point(lat, lon, b, 2.5) for b in range(0,360,30)]
    lats = ",".join(str(round(p[0],4)) for p in pts)
    lons = ",".join(str(round(p[1],4)) for p in pts)
    try:
        data = get_json("https://api.open-meteo.com/v1/elevation", {"latitude":lats,"longitude":lons})
        elevs = data.get("elevation",[])
        sea_b = [b for b,e in zip(range(0,360,30), elevs) if e is not None and e <= 0.8]
        if not sea_b: return None, "inland"
        sn = circular_mean(sea_b) # الاتجاه نحو البحر
        exp = len(sea_b)/12
        return {"shoreline_normal":round(sn,1), "exposure":round(exp,2)}, None
    except: return None, "elev_error"

@st.cache_data(ttl=3600)
def fetch_all_data(lat, lon):
    try:
        marine = get_json("https://marine-api.open-meteo.com/v1/marine", {
            "latitude":lat,"longitude":lon,
            "hourly":"wave_height,wave_direction,wave_period,wind_wave_height,swell_wave_height,swell_wave_period,swell_wave_direction,sea_surface_temperature",
            "past_days":2,"forecast_days":3,"timezone":"Africa/Tunis"
        })
        weather = get_json("https://api.open-meteo.com/v1/forecast", {
            "latitude":lat,"longitude":lon,
            "hourly":"wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,visibility",
            "past_days":2,"forecast_days":3,"timezone":"Africa/Tunis"
        })
        return marine, weather, None
    except Exception as e: return None, None, str(e)

# ══════════════════════════════════════════════════════════════
# 5. CORE PHYSICS ENGINE (تصحيح الوش والبر)
# ══════════════════════════════════════════════════════════════
def classify_wind(wd_from, sn_to_sea):
    # sn_to_sea هو الاتجاه من الشاطئ نحو البحر
    diff = angle_diff_180(wd_from, sn_to_sea)
    if diff <= 45:    return "وش (البحر في وجهك) 🟢", diff, 1.5
    if diff >= 135:   return "بر (الريح في ظهرك) 🔵", diff, 0.8
    if wd_from > sn_to_sea: return "جانبي-يمين 🟠", diff, -1.0
    return "جانبي-يسار 🟡", diff, -1.0

def process_data(marine, weather, coast, tgt):
    sn = coast["shoreline_normal"]
    m_h = marine["hourly"]; w_h = weather["hourly"]
    rows = []
    
    # تحضير الـ Lookup
    m_lk = {t: i for i,t in enumerate(m_h["time"])}
    
    for i, ts in enumerate(w_h["time"]):
        dt = datetime.fromisoformat(ts)
        if dt.date() != tgt: continue
        
        idx = m_lk.get(ts)
        if idx is None: continue

        ws = w_h["wind_speed_10m"][i]; wd = w_h["wind_direction_10m"][i]; gu = w_h["wind_gusts_10m"][i]
        ws_eff = ws + 0.3*(gu-ws)
        
        wh = m_h["wave_height"][idx]; wp = m_h["wave_period"][idx]; wd_wave = m_h["wave_direction"][idx]
        sw_h = m_h["swell_wave_height"][idx]; sw_p = m_h["swell_wave_period"][idx]; sw_d = m_h["swell_wave_direction"][idx]
        sst = m_h["sea_surface_temperature"][idx]
        
        w_lbl, w_diff, w_bon = classify_wind(wd, sn)
        wave_impact = angle_diff_180(wd_wave, sn)
        
        # تيار جانبي فيزيائي
        vls = 0.0
        if 10 < wave_impact < 90:
            vls = 1.1 * math.sqrt(9.8*wh) * math.sin(math.radians(wave_impact)) * math.cos(math.radians(wave_impact))
        vk = round(max(0, (vls + ws_eff*0.01)*3.6), 2)
        
        # الحساب الدقيق للسكور
        sc = 6.0 + w_bon
        if 0.5 <= wh <= 1.5 and "وش" in w_lbl: sc += 2.0
        if wh > 2.0 or ws_eff > 35: sc -= 3.0
        if vk > 1.5: sc -= 2.0
        if 19 <= sst <= 24: sc += 0.5
        
        rows.append({
            "hour": dt.hour, "time": ts[-5:], "score": round(max(0,min(10,sc)),1),
            "wind_type": w_lbl, "ws_eff": round(ws_eff,1), "wave_h": round(wh,2),
            "wave_p": wp, "wave_impact": round(wave_impact,1), "vk": vk,
            "sst": sst, "sw_p": sw_p, "debris": "نظيف 🟢" if wh < 1.2 else "مدرر 🔴"
        })
    
    # حساب 48 ساعة سابقة (أعشاب)
    past_w = safe_avg(m_h["wave_height"][:48])
    is_dirty = past_w > 1.3
    
    return rows, is_dirty

# ══════════════════════════════════════════════════════════════
# 6. DETERMINISTIC REPORT (التقرير الحسابي)
# ══════════════════════════════════════════════════════════════
def generate_det_report(loc, rows, is_dirty, coast, tgt):
    best = max(rows, key=lambda x:x["score"])
    avg_sc = safe_avg([r["score"] for r in rows])
    
    verdict = "✅ GO" if avg_sc >= 6.5 else "🟡 حذر" if avg_sc >= 4.5 else "❌ NO-GO"
    
    report = f"""
### 📊 تقرير المحرك الفيزيائي لـ {loc} ({fmt_date_ar(tgt)})
**القرار النهائي: {verdict} ({round(avg_sc,1)}/10)**

1. **الرياح والزاوية:** الرياح السائدة هي **{best['wind_type']}** بسرعة **{best['ws_eff']} كم/س**. زاوية دخول الموج **{best['wave_impact']}°**.
2. **التيار والأوزان:** تيار جانبي شدته **{best['vk']} كم/س**. ننصح برصاص **{'سبايك 140غ' if best['vk']>1.2 else 'هرمي 120غ'}**.
3. **حالة القاع:** البحر في الـ48 ساعة الماضية كان **{'هائجاً (توقع أعشاب)' if is_dirty else 'هادئاً (القاع نظيف)'}**.
4. **أفضل فترة:** الساعة **{best['time']}** بسكور **{best['score']}/10**.
"""
    return report, best, avg_sc

# ══════════════════════════════════════════════════════════════
# 7. GEMINI AI (ضبط الهلوسة)
# ══════════════════════════════════════════════════════════════
def get_ai_explanation(det_text, rows_json):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key: return "API Key missing."
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"""أنت خبير صيد تونسي. التزم بالأرقام الواردة في التقرير الحسابي أدناه ولا تخترع أرقاماً جديدة.
التقرير الحسابي: {det_text}
البيانات الكاملة: {rows_json}
اشرح للصياد التونسي باللهجة التقنية (وش، بر، تيار، أعشاب) لماذا تم اتخاذ هذا القرار. 
إذا كان السكور منخفضاً، كن صريحاً وقل له 'البحر لا يصلح'."""
        
        resp = client.models.generate_content(model=GEMINI_MODEL, contents=prompt)
        return resp.text
    except: return "AI Error"

# ══════════════════════════════════════════════════════════════
# 8. UI & MAIN EXECUTION
# ══════════════════════════════════════════════════════════════
st.title("🎣 Tunisia Fishing Advisor v10.8")
st.caption("Physics Engine + Deterministic Reports")

c1, c2, c3 = st.columns(3)
with c1: 
    if st.button("اليوم"): st.session_state.day_offset=0; st.rerun()
with c2: 
    if st.button("غداً"): st.session_state.day_offset=1; st.rerun()
with c3: 
    if st.button("بعد غد"): st.session_state.day_offset=2; st.rerun()

tgt_date = date.today() + timedelta(days=st.session_state.day_offset)
st.subheader(f"📅 {fmt_date_ar(tgt_date)}")

# الخريطة
m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=7, tiles="CartoDB dark_matter")
folium.Marker([st.session_state.lat, st.session_state.lon], draggable=True).add_to(m)
map_res = st_folium(m, height=300, width=None, key="map")

if map_res.get("last_clicked"):
    st.session_state.lat = map_res["last_clicked"]["lat"]
    st.session_state.lon = map_res["last_clicked"]["lng"]

if st.button("🔬 تحليل معمق للموقع الحالي", type="primary", use_container_width=True):
    with st.spinner("جاري حساب المتغيرات الفيزيائية..."):
        coast, err1 = analyze_coast(st.session_state.lat, st.session_state.lon)
        if err1: st.error("الموقع داخل البر!"); st.stop()
        
        marine, weather, err2 = fetch_all_data(st.session_state.lat, st.session_state.lon)
        if err2: st.error(err2); st.stop()
        
        rows, is_dirty = process_data(marine, weather, coast, tgt_date)
        loc_name = "هذا الموقع"
        
        det_text, best_row, final_sc = generate_det_report(loc_name, rows, is_dirty, coast, tgt_date)
        ai_text = get_ai_explanation(det_text, json.dumps(rows[:5]))
        
        st.session_state.deep_result = {
            "det": det_text, "ai": ai_text, "rows": rows, 
            "best": best_row, "final_sc": final_sc, "dirty": is_dirty
        }

# عرض النتائج
if st.session_state.deep_result:
    res = st.session_state.deep_result
    
    # المربعات العلوية الموثوقة
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("⭐ السكور النهائي", f"{res['final_sc']}/10")
    m2.metric("⏱️ أفضل ساعة", res['best']['time'])
    m3.metric("🌊 ارتفاع الموج", f"{res['best']['wave_h']}م")
    m4.metric("⚖️ الرصاص", "سبايك" if res['best']['vk'] > 1.2 else "هرمي")
    
    st.divider()
    
    col_det, col_ai = st.columns(2)
    with col_det:
        st.info("📌 تقرير المحرك (حسابات صارمة)")
        st.markdown(res["det"])
    with col_ai:
        st.success("🧠 شرح الذكاء الاصطناعي")
        st.write(res["ai"])
    
    st.divider()
    st.subheader("📊 تفاصيل الساعة بساعة")
    df = pd.DataFrame(res["rows"])[["time", "score", "wind_type", "ws_eff", "wave_h", "vk", "debris"]]
    df.columns = ["الوقت", "السكور", "نوع الريح", "السرعة", "الموج", "التيار", "الأعشاب"]
    
    st.dataframe(df.style.applymap(lambda x: "background:#0a3d0a" if isinstance(x,float) and x>7 else "", subset=["السكور"]), use_container_width=True)

st.caption("© Physics-First Engine | لا تعتمد على AI وحده، المحرك الحسابي هو المرجع.")
