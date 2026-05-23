import os
import json
import math
import requests
import streamlit as st
import folium
import pandas as pd
from streamlit_folium import st_folium
from datetime import datetime, timedelta
import google.generativeai as genai

# ==========================================
# STREAMLIT CONFIG
# ==========================================
st.set_page_config(
    page_title="مستشار الصيد الفيزيائي | تونس",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stMetric {background: #0e1117; padding: 12px; border-radius: 8px; border-left: 4px solid #1f77b4;}
    .go-box {background: #0a3d0a; padding: 20px; border-radius: 10px; border: 2px solid #00ff00;}
    .nogo-box {background: #3d0a0a; padding: 20px; border-radius: 10px; border: 2px solid #ff0000;}
    .warning-box {background: #3d2e0a; padding: 20px; border-radius: 10px; border: 2px solid #ffa500;}
</style>
""", unsafe_allow_html=True)

# Session state (Zero-Lag UI)
if 'lat' not in st.session_state:
    st.session_state.lat = 36.4000  # تونس
if 'lon' not in st.session_state:
    st.session_state.lon = 10.6000

st.title("🌊 المستشار الفيزيائي الحاسم لرحلات الصيد")
st.markdown("#### **محرك هيدروديناميكي حتمي | معادلات نيوتن | قرار عسكري**")

# ==========================================
# HAVERSINE HELPER
# ==========================================
def destination_point(lat1, lon1, bearing_deg, distance_km):
    R = 6371.0
    bearing = math.radians(bearing_deg)
    lat1_r = math.radians(lat1)
    lon1_r = math.radians(lon1)
    lat2_r = math.asin(
        math.sin(lat1_r) * math.cos(distance_km / R) +
        math.cos(lat1_r) * math.sin(distance_km / R) * math.cos(bearing)    )
    lon2_r = lon1_r + math.atan2(
        math.sin(bearing) * math.sin(distance_km / R) * math.cos(lat1_r),
        math.cos(distance_km / R) - math.sin(lat1_r) * math.sin(lat2_r)
    )
    return math.degrees(lat2_r), math.degrees(lon2_r)

# ==========================================
# SHORELINE ASPECT CALCULATOR
# ==========================================
@st.cache_data(ttl=86400, show_spinner=False)
def calculate_shoreline_aspect(lat, lon):
    """حساب اتجاه الساحل العمودي (Shoreline Normal)"""
    try:
        radius_km = 2.0
        points = []
        for bearing in range(0, 360, 10):
            lat2, lon2 = destination_point(lat, lon, bearing, radius_km)
            points.append({"lat": round(lat2, 5), "lon": round(lon2, 5), "bearing": bearing})
        
        lats_str = ",".join([str(p["lat"]) for p in points])
        lons_str = ",".join([str(p["lon"]) for p in points])
        
        resp = requests.get(
            "https://api.open-meteo.com/v1/elevation",
            params={"latitude": lats_str, "longitude": lons_str},
            timeout=10
        )
        resp.raise_for_status()
        elevations = resp.json().get("elevation", [])
        
        if len(elevations) != len(points):
            return None, "بيانات الارتفاع غير مكتملة"
        
        sea_bearings = []
        for p, elev in zip(points, elevations):
            if elev is None:
                continue
            if elev <= 0.5:
                sea_bearings.append(p["bearing"])
        
        if not sea_bearings:
            return None, "inland"
        
        # Circular mean
        sea_radians = [math.radians(b) for b in sea_bearings]
        avg_sin = sum(math.sin(r) for r in sea_radians) / len(sea_radians)
        avg_cos = sum(math.cos(r) for r in sea_radians) / len(sea_radians)
        shoreline_normal = math.degrees(math.atan2(avg_sin, avg_cos)) % 360
                return shoreline_normal, None
    except Exception as e:
        return None, str(e)

# ==========================================
# REVERSE GEOCODING
# ==========================================
@st.cache_data(ttl=86400, show_spinner=False)
def get_location_name(lat, lon):
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "accept-language": "ar", "zoom": 10},
            headers={"User-Agent": "TunisianSurfcastingAdvisor/6.1"},
            timeout=8
        )
        data = resp.json()
        address = data.get("address", {})
        name = (
            address.get("hamlet") or address.get("village") or
            address.get("town") or address.get("city") or
            address.get("state") or "ساحل تونسي"
        )
        return name
    except Exception:
        return "منطقة ساحلية"

# ==========================================
# MAP (ZERO-LAG)
# ==========================================
col_map, col_info = st.columns([2, 1])

with col_map:
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=10)
    folium.Marker(
        [st.session_state.lat, st.session_state.lon],
        tooltip="منطقة الصيد",
        icon=folium.Icon(color="red", icon="anchor", prefix="fa")
    ).add_to(m)
    
    map_data = st_folium(m, width=None, height=450, returned_objects=["last_clicked"])
    
    # Zero-lag: rerun فقط إذا تغيرت الإحداثيات
    if map_data and map_data.get("last_clicked"):
        new_lat = round(map_data["last_clicked"]["lat"], 4)
        new_lon = round(map_data["last_clicked"]["lng"], 4)
        if new_lat != st.session_state.lat or new_lon != st.session_state.lon:
            st.session_state.lat = new_lat
            st.session_state.lon = new_lon
            st.rerun()
with col_info:
    st.subheader("📍 الإحداثيات الحالية")
    st.metric("Latitude", f"{st.session_state.lat}°")
    st.metric("Longitude", f"{st.session_state.lon}°")
    
    # حساب اتجاه الساحل
    with st.spinner("حساب هندسة الساحل..."):
        shoreline_normal, geo_error = calculate_shoreline_aspect(
            st.session_state.lat, st.session_state.lon
        )
    
    if geo_error == "inland":
        st.warning("⚠️ إحداثيات برية")
        shoreline_normal = None
    elif geo_error:
        st.error(geo_error)
        shoreline_normal = None
    else:
        st.success(f"🧭 اتجاه الساحل: {round(shoreline_normal, 1)}°")
    
    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        st.success("✅ Gemini جاهز")
    else:
        st.error("❌ GEMINI_API_KEY مفقود")

st.divider()

# ==========================================
# DATA FETCHING (SAFE PARAMS + FALLBACK)
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_data(lat, lon):
    """جلب بيانات البحر والطقس مع الفولباك الذكي"""
    
    # Marine API
    marine_url = "https://marine-api.open-meteo.com/v1/marine"
    marine_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wave_height,wave_direction,wave_period",
        "past_days": 2,
        "forecast_days": 3,
        "timezone": "auto"
    }
    
    # Weather API (Fallback)
    weather_url = "https://api.open-meteo.com/v1/forecast"
    weather_params = {        "latitude": lat,
        "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "past_days": 2,
        "forecast_days": 3,
        "timezone": "auto"
    }
    
    is_inland = False
    marine_data = None
    
    # محاولة جلب بيانات البحر
    try:
        resp = requests.get(marine_url, params=marine_params, timeout=12)
        resp.raise_for_status()
        marine_data = resp.json()
        if "error" in marine_data:
            raise ValueError(marine_data.get("reason", "Marine error"))
    except Exception:
        is_inland = True
        marine_data = None
    
    # جلب بيانات الطقس (إلزامي)
    try:
        resp = requests.get(weather_url, params=weather_params, timeout=12)
        resp.raise_for_status()
        weather_data = resp.json()
    except Exception as e:
        return None, None, True, f"فشل جلب الطقس: {e}"
    
    return marine_data, weather_data, is_inland, None

# ==========================================
# PHYSICS ENGINE (PROMPT-COMPLIANT + CORRECTED)
# ==========================================
def compute_scores(marine_data, weather_data, is_inland, shoreline_normal):
    """حساب السكور الفيزيائي ساعة بساعة"""
    
    time_array = weather_data['hourly']['time']
    wind_speed = weather_data['hourly']['wind_speed_10m']
    wind_dir_raw = weather_data['hourly']['wind_direction_10m']
    
    # Parse times
    time_dt = []
    for t in time_array:
        try:
            time_dt.append(datetime.fromisoformat(t))
        except Exception:
            time_dt.append(None)
        # Wave data
    if not is_inland and marine_data:
        wave_height = marine_data['hourly']['wave_height']
        wave_dir = marine_data['hourly']['wave_direction']
        wave_period = marine_data['hourly']['wave_period']
    else:
        n = len(wind_speed)
        wave_height = [0.0] * n
        wave_dir = [0.0] * n
        wave_period = [0.0] * n
    
    # Find tomorrow indices dynamically
    valid_times = [(i, t) for i, t in enumerate(time_dt) if t is not None]
    if not valid_times:
        return None, None, "فشل تحليل الزمن"
    
    first_date = valid_times[0][1].date()
    tomorrow_date = first_date + timedelta(days=1)
    
    tomorrow_indices = [i for i, t in valid_times if t.date() == tomorrow_date]
    if not tomorrow_indices:
        return None, None, "لم يتم العثور على بيانات الغد"
    
    start_idx = tomorrow_indices[0]
    end_idx = tomorrow_indices[-1] + 1
    
    # Past 48 hours historical backdrop
    past_end = start_idx
    past_start = max(0, past_end - 48)
    
    past_wh = [x for x in wave_height[past_start:past_end] if x is not None]
    past_wp = [x for x in wave_period[past_start:past_end] if x is not None]
    
    avg_past_wh = sum(past_wh) / max(1, len(past_wh)) if past_wh else 0
    avg_past_wp = sum(past_wp) / max(1, len(past_wp)) if past_wp else 0
    
    # البحر متسخ إذا: موج > 1.2م و تردد > 8ث
    is_historically_dirty = (avg_past_wh > 1.2) and (avg_past_wp > 8.0)
    
    hourly = []
    
    for i in range(start_idx, end_idx):
        score = 10.0  # يبدأ من 10 نقاط كاملة
        
        wh = wave_height[i] if i < len(wave_height) and wave_height[i] is not None else 0.0
        wd = wave_dir[i] if i < len(wave_dir) and wave_dir[i] is not None else 0.0
        wp = wave_period[i] if i < len(wave_period) and wave_period[i] is not None else 0.0
        ws_raw = wind_speed[i] if i < len(wind_speed) and wind_speed[i] is not None else 0.0
        wdir_raw = wind_dir_raw[i] if i < len(wind_dir_raw) and wind_dir_raw[i] is not None else 0.0
        time_str = time_array[i]        
        # عكس متجه الرياح (Meteorological → Oceanographic)
        wdir_going_to = (wdir_raw + 180) % 360
        
        # ========== زاوية اصطدام الموج بالساحل (للمعادلات الفيزيائية) ==========
        if shoreline_normal is not None:
            wave_impact = abs(wd - shoreline_normal)
            if wave_impact > 180:
                wave_impact = 360 - wave_impact
        else:
            wave_impact = 0
        
        wave_impact_rad = math.radians(wave_impact)
        
        # ========== (أ) تصحيح الزوايا الدائرية (رياح-موج) ==========
        angle_diff = abs(wdir_going_to - wd)
        if angle_diff > 180:
            angle_diff = 360 - angle_diff
        angle_diff_rad = math.radians(angle_diff)
        
        # ========== (ب) نموذج التيار الجانبي (Longshore Current) ==========
        # V_longshore = 1.17 * sqrt(9.81 * h_wave) * sin(alpha) * cos(alpha)
        # تُفعّل إذا كان الموج > 0.1م وزاوية الموج بالساحل > 15 درجة
        if wh > 0.1 and wave_impact > 15:
            v_longshore = 1.17 * math.sqrt(9.81 * wh) * math.sin(wave_impact_rad) * math.cos(wave_impact_rad)
        else:
            v_longshore = 0.0
        
        v_longshore_kmh = v_longshore * 3.6
        
        # ========== (ج) قوة جر الرصاص (Lead Drag Force) ==========
        # F_drag = 0.5 * 1025 * 1.5 * 0.0025 * (V_longshore ** 2)
        f_drag = 0.5 * 1025 * 1.5 * 0.0025 * (v_longshore ** 2)
        
        # التوصية التكتيكية بالرصاص
        if f_drag > 2.5:
            lead_recommendation = "شواكيش سبايك"
            lead_weight_g = 140
            lead_type = "spike"
        elif f_drag > 1.0:
            lead_recommendation = "هرمي"
            lead_weight_g = 120
            lead_type = "pyramid"
        else:
            lead_recommendation = "زيتوني"
            lead_weight_g = 100
            lead_type = "olive"
        
        # ========== (د) تيار السحب للعمق (Rip Current Risk) ==========
        # إذا كان الموج > 1.2م والتردد > 8ث وزاوية الموج بالساحل < 30°        if wh > 1.2 and wp > 8.0 and wave_impact < 30:
            rip_risk = "عالي جداً"
        else:
            rip_risk = "منخفض"
        
        # ========== (هـ) مؤشر الأعشاب الطافية (Surface Debris Index) ==========
        # التنظيف الميكانيكي: البحر يستقر + تردد 4-7ث + زاوية الموج < 30°
        is_cleansing = (4.0 <= wp <= 7.0 and wave_impact < 30 and wh <= 1.0)
        
        if is_cleansing and is_historically_dirty:
            debris_status = "تنظيف ميكانيكي ومصفاة طبيعية"
        elif is_historically_dirty:
            debris_status = "بحر مدرر بكثافة والأعشاب تخنق الخيوط"
        else:
            debris_status = "نظيف"
        
        # ========== حساب السكور ==========
        # خصم 3.0 نقاط للبحر الميت
        if wh < 0.3:
            score -= 3.0
        
        # خصم 4.5 نقاط للبحر المدرر
        if debris_status == "بحر مدرر بكثافة والأعشاب تخنق الخيوط":
            score -= 4.5
        
        # خصم 4.0 نقاط للتيار الجانبي العنيف
        if v_longshore_kmh > 1.5:
            score -= 4.0
        elif v_longshore_kmh > 0.8:
            score -= 2.0
        
        # مكافأة 1.5 نقطة لحزام الرغوة البيضاء (Écume)
        # عند تزامن الموج المعتدل (0.5-1.2م) والريح العمودية المستقيمة
        if 0.5 <= wh <= 1.2 and angle_diff < 30 and ws_raw > 12.0:
            score += 1.5
        
        # مكافأة التنظيف الميكانيكي
        if debris_status == "تنظيف ميكانيكي ومصفاة طبيعية":
            score += 2.0
        
        score = max(0.0, min(10.0, score))
        
        hourly.append({
            "time": time_str,
            "score": round(score, 1),
            "wave_height_m": round(wh, 2),
            "wave_period_s": round(wp, 1),
            "wind_speed_kmh": round(ws_raw, 1),
            "wave_impact_deg": round(wave_impact, 1),
            "angle_diff_deg": round(angle_diff, 1),            "longshore_ms": round(v_longshore, 2),
            "longshore_kmh": round(v_longshore_kmh, 1),
            "drag_force_n": round(f_drag, 3),
            "lead_recommendation": lead_recommendation,
            "lead_weight_g": lead_weight_g,
            "rip_risk": rip_risk,
            "debris_status": debris_status
        })
    
    historical_ctx = {
        "avg_past_wh": round(avg_past_wh, 2),
        "avg_past_wp": round(avg_past_wp, 1),
        "is_historically_dirty": is_historically_dirty,
        "tomorrow_date": tomorrow_date.isoformat()
    }
    
    return hourly, historical_ctx, None

# ==========================================
# GEMINI REPORT (PROMPT TEMPLATE EXACT)
# ==========================================
@st.cache_data(ttl=1800, show_spinner=False)
def generate_report(hourly_data, historical_ctx, location_name, shoreline_normal):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, "GEMINI_API_KEY مفقود"
    
    try:
        genai.configure(api_key=api_key)
        config = genai.GenerationConfig(temperature=0.1, top_p=0.1, max_output_tokens=2500)
        model = genai.GenerativeModel('gemini-1.5-flash', generation_config=config)
        
        historical_status = "بحر مدرر (متسخ)" if historical_ctx["is_historically_dirty"] else "بحر نظيف (مستقر)"
        shoreline_str = f"{round(shoreline_normal, 1)}°" if shoreline_normal else "غير محسوب"
        
        json_payload = json.dumps(hourly_data, ensure_ascii=False)
        
        prompt = f"""
أنت خبير محيطات ساحلية وصياد محترف تونسي متخصص في هيدروديناميكا Surfcasting.

📍 الموقع: {location_name}
🧭 اتجاه الساحل العمودي: {shoreline_str}
📅 التاريخ: {historical_ctx['tomorrow_date']}
📜 الحالة التاريخية (48 ساعة): {historical_status}
📊 متوسط الموج الماضي: {historical_ctx['avg_past_wh']}م
📊 متوسط التردد الماضي: {historical_ctx['avg_past_wp']}ث

البيانات الحركية ليوم غد (JSON):
{json_payload}
حقول البيانات (استخدمها بدقة):
- score: السكور الرياضي (0-10)
- wave_height_m: ارتفاع الموج (م)
- wave_period_s: تردد الموج (ثانية)
- wind_speed_kmh: سرعة الرياح (كم/س)
- wave_impact_deg: زاوية اصطدام الموج بالساحل (0° = عمودي، 90° = جانبي)
- angle_diff_deg: فرق الزاوية بين الرياح والموج (للرغوة البيضاء)
- longshore_ms: سرعة التيار الجانبي (م/ث)
- longshore_kmh: نفس السرعة بـ كم/س
- drag_force_n: قوة جر الرصاص (نيوتن)
- lead_recommendation: نوع الرصاص الموصى به
- lead_weight_g: وزن الرصاص بالجرام
- rip_risk: خطر التيارات الساحبة
- debris_status: حالة الأعشاب

⚠️ قواعد صارمة:
1. ابدأ مباشرة بالنص (لا مقدمات مثل "بالتأكيد" أو "إليك التقرير")
2. لا تخترع أرقاماً - استخدم البيانات المرفقة فقط
3. احترم التوصيات الحرفية للرصاص من lead_recommendation و lead_weight_g
4. استخدم المصطلحات التونسية/المغاربية: بحر مدرر، تيار الحمل، ريح وش مستقيمة، مصفاة الموج، الرصاص يرجع للشط، البحر ينظف نفسه، Écume، plomb، bas de ligne، daurade، loup، marbré

التزم حرفياً بهذا القالب دون أي تعديل:

بناءً على الحسابات الرياضية الصارمة لسكور الصيد ساعة بساعة ومقارنتها بالـ 48 ساعة الماضية، التقييم التقني يمنح القرار لـ {location_name}.

## 1. تحليل التغير الحركي وسكور الصيد ساعة بساعة (هل البحر ينظف نفسه؟)

(حلل تطور السكور والظروف ساعة بساعة. حدد الساعة الذهبية. هل يحدث "البحر ينظف نفسه"؟ استخدم debris_status. اذكر ساعات الذروة بدقة)

## 2. ميكانيكا حركة الرصاص ومعادلة النيوتن وتيار الحمل الجانبي

(حلل:
- سرعة التيار الجانبي (longshore_kmh) وتأثيرها على المونتاج
- قوة الجر بالنيوتن (drag_force_n) 
- التوصية بالرصاص (lead_recommendation) ووزنه (lead_weight_g) - الزم هذه التوصية
- خطر التيارات الساحبة (rip_risk)
- هل سيرجع الرصاص للشط أم سيثبت في القاع؟)

## 3. النوافذ البيولوجية ونشاط السمك وتطور حزام الرغوة (Écume)

(متى تتشكل Écume؟ متى تدخل الدنيس (Daurade) والقاروص (Loup) والورطة (Marbré)؟ ما هي أفضل نافذة بيولوجية للصيد الليلي؟)

------------------------------

## 🎯 القرار النهائي والحاسم لرحلتك (تأكيد أو إلغاء قطعي تفصيلي بناءً على الأرقام الحتمية):

(احسب المتوسط الحسابي الصارم للـ scores. إذا كان >= 5.0 = GO مؤكد مع ذكر الأسباب بالأرقام. إذا < 5.0 = NO-GO قاطع مع ذكر الأسباب بالأرقام)

* تكتيك الصيد المصيري لليوم: [نوع الرصاص: (lead_recommendation)، الوزن: (lead_weight_g) جرام، المسافة المثالية: (50-70م للرغوة/70-100م للعمق)، الطعوم: (دود البحر/الجمبري/بلح البحر)، وقت البدء والإنهاء]
"""        
        response = model.generate_content(prompt)
        return response.text, None
    
    except Exception as e:
        return None, f"خطأ Gemini: {str(e)}"

# ==========================================
# MAIN FLOW
# ==========================================

# جلب البيانات
with st.spinner("جلب البيانات الهيدروديناميكية..."):
    marine_data, weather_data, is_inland, fetch_error = fetch_data(
        st.session_state.lat, st.session_state.lon
    )

if fetch_error:
    st.error(fetch_error)
    st.stop()

# Fallback warning
if is_inland:
    st.warning("⚠️ **إحداثيات برية!** تم تفعيل الحسابات بناءً على رياح الشاطئ القريبة (لا توجد بيانات أمواج حقيقية).")

location_name = get_location_name(st.session_state.lat, st.session_state.lon)
st.info(f"📍 **الموقع:** {location_name}")

# حساب النقاط الفيزيائية
with st.spinner("حساب المعادلات الفيزيائية الحتمية..."):
    hourly_data, historical_ctx, score_error = compute_scores(
        marine_data, weather_data, is_inland, shoreline_normal
    )

if score_error:
    st.error(score_error)
    st.stop()

# عرض الجدول
st.subheader("📊 المصفوفة الزمنية ليوم غد")
df = pd.DataFrame(hourly_data)
df_display = df[[
    "time", "score", "wave_height_m", "wave_period_s", "wind_speed_kmh",
    "wave_impact_deg", "angle_diff_deg", "longshore_kmh", "drag_force_n",
    "lead_weight_g", "rip_risk", "debris_status"
]].copy()
df_display.columns = [
    "الوقت", "السكر", "الموج (م)", "التردد (ث)", "الرياح (كم/س)",
    "زاوية الموج-الساحل", "زاوية الرياح-الموج", "التيار الجانبي (كم/س)",
    "قوة الجر (N)", "وزن الرصاص (غ)", "التيارات الساحبة", "الأعشاب"]
st.dataframe(df_display, use_container_width=True, hide_index=True)

# ملخصات
avg_score = sum(h["score"] for h in hourly_data) / len(hourly_data)
max_hour = max(hourly_data, key=lambda x: x["score"])
avg_longshore = sum(h["longshore_kmh"] for h in hourly_data) / len(hourly_data)
avg_drag = sum(h["drag_force_n"] for h in hourly_data) / len(hourly_data)

col1, col2, col3, col4 = st.columns(4)
col1.metric("متوسط السكر", f"{avg_score:.1f}/10")
col2.metric("الساعة الذهبية", max_hour["time"][-5:])
col3.metric("التيار الجانبي (متوسط)", f"{avg_longshore:.1f} كم/س")
col4.metric("قوة الجر (متوسط)", f"{avg_drag:.2f} N")

# صندوق القرار السريع
st.subheader("⚡ القرار العسكري السريع")
if avg_score >= 7.5:
    st.markdown(f"""
    <div class='go-box'>
    <h2 style='color:#00ff00; text-align:center;'>✅ GO - انطلاق ممتاز</h2>
    <p style='text-align:center; font-size:1.2em;'>المتوسط: {avg_score:.1f}/10 - ظروف مثالية للصيد</p>
    </div>
    """, unsafe_allow_html=True)
elif avg_score >= 5.0:
    st.markdown(f"""
    <div class='go-box'>
    <h2 style='color:#ffff00; text-align:center;'>🟡 GO - انطلاق ممكن</h2>
    <p style='text-align:center; font-size:1.2em;'>المتوسط: {avg_score:.1f}/10 - ظروف مقبولة مع تحضيرات</p>
    </div>
    """, unsafe_allow_html=True)
elif avg_score >= 4.0:
    st.markdown(f"""
    <div class='warning-box'>
    <h2 style='color:#ffa500; text-align:center;'>🟠 تحذير - للخبراء فقط</h2>
    <p style='text-align:center; font-size:1.2em;'>المتوسط: {avg_score:.1f}/10 - ظروف صعبة</p>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown(f"""
    <div class='nogo-box'>
    <h2 style='color:#ff4b4b; text-align:center;'>🔴 NO-GO - إلغاء قطعي</h2>
    <p style='text-align:center; font-size:1.2em;'>المتوسط: {avg_score:.1f}/10 - ظروف خطيرة للصيد</p>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# تقرير Gemini
st.subheader("🧠 التقرير التكتيكي النهائي")
with st.spinner("جاري إعداد التقرير العسكري الشامل..."):
    report, gen_error = generate_report(
        hourly_data, historical_ctx, location_name, shoreline_normal
    )

if gen_error:
    st.error(gen_error)
else:
    st.markdown(report)

st.divider()
st.caption("© المستشار الفيزيائي الحاسم v6.1 | Shoreline-Aware + Longshore + Drag Force + Rip Current + Debris Index")
