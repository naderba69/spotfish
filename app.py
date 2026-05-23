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
    .info-box {background: #0a1a3d; padding: 20px; border-radius: 10px; border: 2px solid #1f77b4;}
</style>
""", unsafe_allow_html=True)

# ==========================================
# SESSION STATE — ZERO-LAG UI
# ==========================================
if 'lat' not in st.session_state:
    st.session_state.lat = 36.4000
if 'lon' not in st.session_state:
    st.session_state.lon = 10.6000

# FIX #9 — تهيئة shoreline_normal قبل أي استخدام
if 'shoreline_normal' not in st.session_state:
    st.session_state.shoreline_normal = None

st.title("🌊 المستشار الفيزيائي الحاسم لرحلات الصيد")
st.markdown("#### **محرك هيدروديناميكي حتمي | معادلات نيوتن | قرار عسكري — v6.2 Fixed**")

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
        math.cos(lat1_r) * math.sin(distance_km / R) * math.cos(bearing)
    )
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
            headers={"User-Agent": "TunisianSurfcastingAdvisor/6.2"},
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
# MAP — ZERO-LAG
# ==========================================
col_map, col_info = st.columns([2, 1])

# FIX #9 — shoreline_normal مُهيَّأ قبل الـ with block
shoreline_normal = st.session_state.shoreline_normal

with col_map:
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=10)
    folium.Marker(
        [st.session_state.lat, st.session_state.lon],
        tooltip="منطقة الصيد",
        icon=folium.Icon(color="red", icon="anchor", prefix="fa")
    ).add_to(m)

    map_data = st_folium(m, width=None, height=450, returned_objects=["last_clicked"])

    if map_data and map_data.get("last_clicked"):
        new_lat = round(map_data["last_clicked"]["lat"], 4)
        new_lon = round(map_data["last_clicked"]["lng"], 4)
        if new_lat != st.session_state.lat or new_lon != st.session_state.lon:
            st.session_state.lat = new_lat
            st.session_state.lon = new_lon
            st.session_state.shoreline_normal = None  # إعادة حساب عند تغيير الموقع
            st.rerun()

with col_info:
    st.subheader("📍 الإحداثيات الحالية")
    st.metric("Latitude", f"{st.session_state.lat}°")
    st.metric("Longitude", f"{st.session_state.lon}°")

    with st.spinner("حساب هندسة الساحل..."):
        computed_normal, geo_error = calculate_shoreline_aspect(
            st.session_state.lat, st.session_state.lon
        )

    if geo_error == "inland":
        st.warning("⚠️ إحداثيات برية — سيتم استخدام بيانات الرياح فقط")
        shoreline_normal = None
    elif geo_error:
        st.error(f"خطأ في حساب الساحل: {geo_error}")
        shoreline_normal = None
    else:
        shoreline_normal = computed_normal
        st.success(f"🧭 اتجاه الساحل: {round(shoreline_normal, 1)}°")

    # تخزين في session_state للاستخدام لاحقاً
    st.session_state.shoreline_normal = shoreline_normal

    api_key = os.environ.get("GEMINI_API_KEY")
    if api_key:
        st.success("✅ Gemini جاهز")
    else:
        st.error("❌ GEMINI_API_KEY مفقود")

st.divider()

# ==========================================
# DATA FETCHING — SAFE PARAMS + SMART FALLBACK
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_data(lat, lon):
    """جلب بيانات البحر والطقس مع الفولباك الذكي"""

    marine_url = "https://marine-api.open-meteo.com/v1/marine"
    marine_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wave_height,wave_direction,wave_period",
        "past_days": 2,
        "forecast_days": 3,
        "timezone": "auto"
    }

    weather_url = "https://api.open-meteo.com/v1/forecast"
    weather_params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "past_days": 2,
        "forecast_days": 3,
        "timezone": "auto"
    }

    is_inland = False
    marine_data = None

    try:
        resp = requests.get(marine_url, params=marine_params, timeout=12)
        resp.raise_for_status()
        marine_data = resp.json()
        if "error" in marine_data:
            raise ValueError(marine_data.get("reason", "Marine error"))
    except Exception:
        is_inland = True
        marine_data = None

    try:
        resp = requests.get(weather_url, params=weather_params, timeout=12)
        resp.raise_for_status()
        weather_data = resp.json()
    except Exception as e:
        return None, None, True, f"فشل جلب الطقس: {e}"

    return marine_data, weather_data, is_inland, None


# ==========================================
# FIX #1 — دمج آمن بالوقت كمفتاح
# ==========================================
def build_marine_lookup(marine_data):
    """
    بناء dict: {time_str: index} من بيانات Marine API
    يضمن تطابقاً دقيقاً بين الوقت من Weather وبيانات Marine
    """
    if not marine_data:
        return {}
    times = marine_data['hourly'].get('time', [])
    return {t: i for i, t in enumerate(times)}


# ==========================================
# PHYSICS ENGINE — FULLY CORRECTED v6.2
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)  # FIX #12 — cache للأداء والاتساق
def compute_scores(marine_data, weather_data, is_inland, shoreline_normal):
    """حساب السكور الفيزيائي ساعة بساعة — جميع الأخطاء مُصحَّحة"""

    time_array   = weather_data['hourly']['time']
    wind_speed   = weather_data['hourly']['wind_speed_10m']
    wind_dir_raw = weather_data['hourly']['wind_direction_10m']

    # Parse times
    time_dt = []
    for t in time_array:
        try:
            time_dt.append(datetime.fromisoformat(t))
        except Exception:
            time_dt.append(None)

    # FIX #1 — lookup بالوقت بدل الفهرس المُشترك
    marine_lookup = build_marine_lookup(marine_data) if not is_inland else {}

    def get_marine_val(key, time_str, default=0.0):
        if is_inland or not marine_data:
            return default
        idx = marine_lookup.get(time_str)
        if idx is None:
            return default
        arr = marine_data['hourly'].get(key, [])
        if idx < len(arr) and arr[idx] is not None:
            return float(arr[idx])
        return default

    # Find tomorrow
    valid_times = [(i, t) for i, t in enumerate(time_dt) if t is not None]
    if not valid_times:
        return None, None, "فشل تحليل الزمن"

    first_date    = valid_times[0][1].date()
    tomorrow_date = first_date + timedelta(days=1)

    tomorrow_indices = [i for i, t in valid_times if t.date() == tomorrow_date]
    if not tomorrow_indices:
        return None, None, "لم يتم العثور على بيانات الغد"

    start_idx = tomorrow_indices[0]
    end_idx   = tomorrow_indices[-1] + 1

    # ==========================================
    # FIX #2 — Historical dirty check مُصحَّح
    # تردد قصير < 6s = موج ريح عشوائي = بحر مدرر
    # تردد طويل > 8s = Swell منتظم = بحر نظيف
    # ==========================================
    past_end   = start_idx
    past_start = max(0, past_end - 48)

    past_wh_vals, past_wp_vals = [], []
    for i in range(past_start, past_end):
        t_str = time_array[i]
        wh_p  = get_marine_val('wave_height', t_str, 0.0)
        wp_p  = get_marine_val('wave_period', t_str, 0.0)
        if wh_p > 0:
            past_wh_vals.append(wh_p)
        if wp_p > 0:
            past_wp_vals.append(wp_p)

    avg_past_wh = sum(past_wh_vals) / max(1, len(past_wh_vals)) if past_wh_vals else 0.0
    avg_past_wp = sum(past_wp_vals) / max(1, len(past_wp_vals)) if past_wp_vals else 0.0

    # CORRECTED: تردد قصير = بحر مدرر، تردد طويل = Swell نظيف
    is_historically_dirty = (avg_past_wh > 1.2) and (avg_past_wp < 6.0)

    hourly = []

    for i in range(start_idx, end_idx):
        score  = 10.0
        t_str  = time_array[i]
        t_obj  = time_dt[i]

        # FIX #1 — جلب بيانات Marine بالوقت
        wh  = get_marine_val('wave_height',  t_str, 0.0)
        wd  = get_marine_val('wave_direction', t_str, 0.0)
        wp  = get_marine_val('wave_period',  t_str, 0.0)

        ws_raw   = float(wind_speed[i])   if i < len(wind_speed)   and wind_speed[i]   is not None else 0.0
        wdir_raw = float(wind_dir_raw[i]) if i < len(wind_dir_raw) and wind_dir_raw[i] is not None else 0.0

        # Meteorological → Oceanographic (اتجاه ذهاب الرياح)
        wdir_going_to = (wdir_raw + 180) % 360

        # ========== زاوية اصطدام الموج بالساحل ==========
        if shoreline_normal is not None:
            wave_impact = abs(wd - shoreline_normal)
            if wave_impact > 180:
                wave_impact = 360 - wave_impact
        else:
            wave_impact = 45.0  # افتراضي محايد (ليس 0 الذي يُشوّه الحسابات)

        wave_impact_rad = math.radians(wave_impact)

        # ========== زاوية رياح-موج ==========
        angle_diff = abs(wdir_going_to - wd)
        if angle_diff > 180:
            angle_diff = 360 - angle_diff

        # ========== FIX #5 — Hb (Breaking Wave Height) ==========
        # H_offshore → H_breaking بمعامل Kshoaling تقريبي 1.4
        hb = wh * 1.4

        # ========== (ب) التيار الجانبي — بـ Hb الصحيح ==========
        if wh > 0.1 and wave_impact > 15:
            v_longshore = 1.17 * math.sqrt(9.81 * hb) * \
                          math.sin(wave_impact_rad) * math.cos(wave_impact_rad)
        else:
            v_longshore = 0.0

        v_longshore_kmh = v_longshore * 3.6

        # ========== (ج) قوة جر الرصاص ==========
        f_drag = 0.5 * 1025 * 1.5 * 0.0025 * (v_longshore ** 2)

        if f_drag > 2.5:
            lead_recommendation = "شواكيش سبايك"
            lead_weight_g       = 140
        elif f_drag > 1.0:
            lead_recommendation = "هرمي"
            lead_weight_g       = 120
        else:
            lead_recommendation = "زيتوني"
            lead_weight_g       = 100

        # ========== FIX #6 — Rip Current مُصحَّح ==========
        # Rip Currents تتشكل عند: موج عالٍ + تردد طويل + زاوية 20-60°
        if wh > 1.2 and wp > 8.0 and 20 <= wave_impact <= 60:
            rip_risk = "عالي جداً"
        elif wh > 1.0 and wp > 6.0 and wave_impact < 30:
            rip_risk = "متوسط"
        else:
            rip_risk = "منخفض"

        # ========== FIX #8 — is_cleansing مُصحَّح ==========
        # Swell منتظم (wp >= 8s) = تنظيف حقيقي
        # تردد قصير (4-7s) = موج ريح = يُثير الرواسب
        is_cleansing = (wp >= 8.0 and wave_impact < 45 and wh <= 1.2)

        # FIX #7 — Inland fallback: لا نُصدر توصية كاذبة بالأعشاب
        if is_inland:
            debris_status = "لا توجد بيانات أمواج — إحداثيات برية"
        elif is_cleansing and is_historically_dirty:
            debris_status = "تنظيف ميكانيكي — البحر ينظف نفسه (Swell نظيف)"
        elif is_historically_dirty:
            debris_status = "بحر مدرر بكثافة — الأعشاب تخنق الخيوط"
        else:
            debris_status = "نظيف"

        # ==========================================
        # حساب السكور — جميع الخصومات والمكافآت
        # ==========================================

        # خصم البحر الميت (inland: wh=0 → لا خصم لأنه غير موثوق)
        if not is_inland and wh < 0.3:
            score -= 3.0

        # خصم البحر المدرر
        if debris_status == "بحر مدرر بكثافة — الأعشاب تخنق الخيوط":
            score -= 4.5

        # خصم التيار الجانبي
        if v_longshore_kmh > 1.5:
            score -= 4.0
        elif v_longshore_kmh > 0.8:
            score -= 2.0

        # FIX #4 — عقوبة الرياح الخطيرة (مفقودة في v6.1)
        if ws_raw > 60:
            score -= 6.0   # عاصفة — إلغاء إلزامي
        elif ws_raw > 50:
            score -= 4.0   # خطر عالٍ
        elif ws_raw > 35:
            score -= 2.0   # صعب
        elif ws_raw > 25:
            score -= 1.0   # تحذير خفيف

        # FIX #3 — مكافأة Écume بـ wave_impact (ليس angle_diff)
        # Écume تتشكل عندما يكسر الموج المعتدل شبه عمودياً على الساحل
        if 0.5 <= wh <= 1.2 and wave_impact < 45 and ws_raw > 12.0:
            score += 1.5

        # مكافأة التنظيف الميكانيكي
        if is_cleansing and is_historically_dirty:
            score += 2.0

        score = max(0.0, min(10.0, score))

        # ساعة الحدث (للتقرير)
        hour_val = t_obj.hour if t_obj else -1

        hourly.append({
            "time":               t_str,
            "hour":               hour_val,
            "score":              round(score, 1),
            "wave_height_m":      round(wh, 2),
            "breaking_height_m":  round(hb, 2),
            "wave_period_s":      round(wp, 1),
            "wind_speed_kmh":     round(ws_raw, 1),
            "wave_impact_deg":    round(wave_impact, 1),
            "angle_diff_deg":     round(angle_diff, 1),
            "longshore_ms":       round(v_longshore, 3),
            "longshore_kmh":      round(v_longshore_kmh, 2),
            "drag_force_n":       round(f_drag, 4),
            "lead_recommendation": lead_recommendation,
            "lead_weight_g":      lead_weight_g,
            "rip_risk":           rip_risk,
            "debris_status":      debris_status,
            "is_inland":          is_inland
        })

    historical_ctx = {
        "avg_past_wh":            round(avg_past_wh, 2),
        "avg_past_wp":            round(avg_past_wp, 1),
        "is_historically_dirty":  is_historically_dirty,
        "tomorrow_date":          tomorrow_date.isoformat(),
        "is_inland":              is_inland
    }

    return hourly, historical_ctx, None


# ==========================================
# FIX #10 — متوسط مُرجَّح يُعطي أولوية لساعات الصيد
# ==========================================
def compute_weighted_avg_score(hourly_data):
    """
    ساعات الصيد الفعلية (17:00-23:00 و 04:00-08:00) تحمل وزناً أعلى
    باقي الساعات وزن عادي
    """
    prime_hours = set(range(17, 24)) | set(range(4, 9))
    total_weight = 0.0
    total_score  = 0.0

    for h in hourly_data:
        hour   = h.get("hour", -1)
        weight = 2.0 if hour in prime_hours else 1.0
        total_score  += h["score"] * weight
        total_weight += weight

    return total_score / total_weight if total_weight > 0 else 0.0


# ==========================================
# GEMINI REPORT — PROMPT TEMPLATE EXACT
# ==========================================
@st.cache_data(ttl=1800, show_spinner=False)
def generate_report(hourly_data, historical_ctx, location_name, shoreline_normal, weighted_avg):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, "GEMINI_API_KEY مفقود"

    try:
        genai.configure(api_key=api_key)
        config = genai.GenerationConfig(temperature=0.1, top_p=0.1, max_output_tokens=2800)
        model  = genai.GenerativeModel('gemini-1.5-flash', generation_config=config)

        historical_status = (
            "بحر مدرر (تردد قصير < 6ث = موج ريح عشوائي)"
            if historical_ctx["is_historically_dirty"]
            else "بحر نظيف (Swell منتظم أو هادئ)"
        )
        shoreline_str = f"{round(shoreline_normal, 1)}°" if shoreline_normal else "غير محسوب (إحداثيات برية)"
        inland_note   = "⚠️ إحداثيات برية — لا توجد بيانات أمواج حقيقية" if historical_ctx["is_inland"] else ""

        json_payload = json.dumps(hourly_data, ensure_ascii=False)

        prompt = f"""
أنت خبير محيطات ساحلية وصياد محترف تونسي متخصص في هيدروديناميكا Surfcasting.

📍 الموقع: {location_name}
🧭 اتجاه الساحل العمودي: {shoreline_str}
📅 التاريخ: {historical_ctx['tomorrow_date']}
📜 الحالة التاريخية (48 ساعة): {historical_status}
📊 متوسط الموج الماضي: {historical_ctx['avg_past_wh']}م
📊 متوسط التردد الماضي: {historical_ctx['avg_past_wp']}ث
{inland_note}
🎯 المتوسط المُرجَّح لساعات الصيد: {round(weighted_avg, 2)}/10

البيانات الحركية ليوم غد (JSON):
{json_payload}

حقول البيانات (استخدمها بدقة):
- score: السكور الرياضي المُرجَّح (0-10)
- wave_height_m: ارتفاع الموج المفتوح (م)
- breaking_height_m: ارتفاع موج الكسر Hb = 1.4 × H_offshore (م) — هذا المستخدم في حسابات التيار
- wave_period_s: تردد الموج (ث) — أقل من 6ث = مدرر، أكثر من 8ث = Swell نظيف
- wind_speed_kmh: سرعة الرياح (كم/س)
- wave_impact_deg: زاوية اصطدام الموج بالساحل (0°=عمودي، 90°=جانبي)
- angle_diff_deg: فرق الزاوية بين الرياح والموج
- longshore_ms: سرعة التيار الجانبي (م/ث) — محسوبة بـ Hb الصحيح
- longshore_kmh: نفس السرعة بـ كم/س
- drag_force_n: قوة جر الرصاص (نيوتن)
- lead_recommendation: نوع الرصاص الموصى به
- lead_weight_g: وزن الرصاص بالجرام
- rip_risk: خطر التيارات الساحبة (عالي جداً فقط عند 20°≤wave_impact≤60°)
- debris_status: حالة الأعشاب (تردد قصير=مدرر، Swell=نظيف)
- is_inland: هل الموقع بري؟

⚠️ قواعد صارمة:
1. ابدأ مباشرة بالنص (لا مقدمات)
2. لا تخترع أرقاماً — استخدم البيانات فقط
3. احترم التوصيات الحرفية للرصاص
4. إذا كانت is_inland=true، وضّح أن التوصيات مبنية على الرياح فقط
5. استخدم المصطلحات التونسية: بحر مدرر، تيار الحمل، ريح وش مستقيمة، مصفاة الموج، الرصاص يرجع للشط، البحر ينظف نفسه، Écume، plomb، bas de ligne، daurade، loup، marbré

التزم حرفياً بهذا القالب:

بناءً على الحسابات الرياضية الصارمة لسكور الصيد ساعة بساعة (متوسط مُرجَّح: {round(weighted_avg,2)}/10) ومقارنتها بالـ 48 ساعة الماضية، التقييم التقني يمنح القرار لـ {location_name}.

## 1. تحليل التغير الحركي وسكور الصيد ساعة بساعة

(حلل تطور السكور والظروف ساعة بساعة. حدد الساعة الذهبية. هل يحدث "البحر ينظف نفسه"؟ استخدم debris_status. اذكر أن التنظيف مرتبط بـ Swell ≥ 8ث وليس بالتردد القصير)

## 2. ميكانيكا حركة الرصاص ومعادلة نيوتن وتيار الحمل الجانبي

(حلل:
- سرعة التيار الجانبي longshore_kmh وتأثيرها على المونتاج
- قوة الجر drag_force_n بالنيوتن — محسوبة بـ breaking_height_m الصحيح
- نوع الرصاص lead_recommendation ووزنه lead_weight_g — الزم هذه التوصية
- خطر التيارات الساحبة rip_risk
- هل سيرجع الرصاص للشط؟)

## 3. النوافذ البيولوجية ونشاط السمك وتطور حزام الرغوة (Écume)

(متى تتشكل Écume؟ — تتطلب wave_impact<45° وليس angle_diff فقط
متى تدخل الدنيس Daurade والقاروص Loup والورطة Marbré؟
أفضل نافذة بيولوجية بين 17:00-23:00 و04:00-08:00)

------------------------------

## 🎯 القرار النهائي الحاسم (بناءً على المتوسط المُرجَّح {round(weighted_avg,2)}/10):

(>= 5.0 = GO مؤكد مع الأسباب. < 5.0 = NO-GO قاطع مع الأسباب)

* تكتيك الصيد المصيري: [نوع الرصاص: lead_recommendation، الوزن: lead_weight_g جرام، المسافة المثالية، الطعوم: دود البحر/جمبري/بلح البحر، وقت البدء والإنهاء]
"""
        response = model.generate_content(prompt)
        return response.text, None

    except Exception as e:
        return None, f"خطأ Gemini: {str(e)}"


# ==========================================
# MAIN FLOW
# ==========================================
with st.spinner("جلب البيانات الهيدروديناميكية..."):
    marine_data, weather_data, is_inland, fetch_error = fetch_data(
        st.session_state.lat, st.session_state.lon
    )

if fetch_error:
    st.error(fetch_error)
    st.stop()

if is_inland:
    st.warning("""
    ⚠️ **إحداثيات برية!**
    - لا توجد بيانات أمواج حقيقية
    - التيار الجانبي وقوة الجر = صفر (غير محسوب)
    - التوصيات مبنية على الرياح فقط
    - السكور غير كامل الموثوقية
    """)

location_name = get_location_name(st.session_state.lat, st.session_state.lon)
st.info(f"📍 **الموقع:** {location_name}")

with st.spinner("حساب المعادلات الفيزيائية الحتمية..."):
    hourly_data, historical_ctx, score_error = compute_scores(
        marine_data, weather_data, is_inland, shoreline_normal
    )

if score_error:
    st.error(score_error)
    st.stop()

# ==========================================
# عرض الجدول
# ==========================================
st.subheader("📊 المصفوفة الزمنية ليوم غد")

df = pd.DataFrame(hourly_data)

# تلوين السكور
def color_score(val):
    if val >= 7.5:
        return 'background-color: #0a3d0a; color: #00ff00'
    elif val >= 5.0:
        return 'background-color: #3d3d0a; color: #ffff00'
    elif val >= 4.0:
        return 'background-color: #3d2e0a; color: #ffa500'
    else:
        return 'background-color: #3d0a0a; color: #ff4b4b'

df_display = df[[
    "time", "score", "wave_height_m", "breaking_height_m",
    "wave_period_s", "wind_speed_kmh",
    "wave_impact_deg", "longshore_kmh", "drag_force_n",
    "lead_weight_g", "lead_recommendation",
    "rip_risk", "debris_status"
]].copy()

df_display.columns = [
    "الوقت", "السكر", "الموج (م)", "Hb (م)",
    "التردد (ث)", "الرياح (كم/س)",
    "زاوية الموج-الساحل", "التيار الجانبي (كم/س)", "قوة الجر (N)",
    "وزن الرصاص (غ)", "نوع الرصاص",
    "التيارات الساحبة", "الأعشاب"
]

styled_df = df_display.style.applymap(color_score, subset=["السكر"])
st.dataframe(styled_df, use_container_width=True, hide_index=True)

# ==========================================
# ملخصات — FIX #10 متوسط مُرجَّح
# ==========================================
weighted_avg  = compute_weighted_avg_score(hourly_data)
simple_avg    = sum(h["score"] for h in hourly_data) / len(hourly_data)
max_hour      = max(hourly_data, key=lambda x: x["score"])
avg_longshore = sum(h["longshore_kmh"] for h in hourly_data) / len(hourly_data)
avg_drag      = sum(h["drag_force_n"]  for h in hourly_data) / len(hourly_data)

col1, col2, col3, col4, col5 = st.columns(5)
col1.metric("متوسط السكر (مُرجَّح)", f"{weighted_avg:.1f}/10",
            delta=f"بسيط: {simple_avg:.1f}", delta_color="off")
col2.metric("الساعة الذهبية", max_hour["time"][-5:],
            delta=f"سكر: {max_hour['score']}")
col3.metric("التيار الجانبي (متوسط)", f"{avg_longshore:.2f} كم/س")
col4.metric("قوة الجر (متوسط)", f"{avg_drag:.3f} N")
col5.metric("حالة الأعشاب",
            "🟢 نظيف" if not historical_ctx["is_historically_dirty"] else "🔴 مدرر")

# ==========================================
# صندوق القرار العسكري — بناءً على المتوسط المُرجَّح
# ==========================================
st.subheader("⚡ القرار العسكري السريع")

if weighted_avg >= 7.5:
    st.markdown(f"""
    <div class='go-box'>
    <h2 style='color:#00ff00; text-align:center;'>✅ GO — انطلاق ممتاز</h2>
    <p style='text-align:center; font-size:1.2em;'>المتوسط المُرجَّح: {weighted_avg:.1f}/10 — ظروف مثالية</p>
    </div>
    """, unsafe_allow_html=True)
elif weighted_avg >= 5.0:
    st.markdown(f"""
    <div class='go-box'>
    <h2 style='color:#ffff00; text-align:center;'>🟡 GO — انطلاق ممكن</h2>
    <p style='text-align:center; font-size:1.2em;'>المتوسط المُرجَّح: {weighted_avg:.1f}/10 — ظروف مقبولة مع تحضيرات</p>
    </div>
    """, unsafe_allow_html=True)
elif weighted_avg >= 4.0:
    st.markdown(f"""
    <div class='warning-box'>
    <h2 style='color:#ffa500; text-align:center;'>🟠 تحذير — للخبراء فقط</h2>
    <p style='text-align:center; font-size:1.2em;'>المتوسط المُرجَّح: {weighted_avg:.1f}/10 — ظروف صعبة</p>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown(f"""
    <div class='nogo-box'>
    <h2 style='color:#ff4b4b; text-align:center;'>🔴 NO-GO — إلغاء قطعي</h2>
    <p style='text-align:center; font-size:1.2em;'>المتوسط المُرجَّح: {weighted_avg:.1f}/10 — ظروف خطيرة</p>
    </div>
    """, unsafe_allow_html=True)

st.divider()

# ==========================================
# تقرير Gemini
# ==========================================
st.subheader("🧠 التقرير التكتيكي النهائي")
with st.spinner("جاري إعداد التقرير العسكري الشامل..."):
    report, gen_error = generate_report(
        hourly_data, historical_ctx, location_name,
        shoreline_normal, weighted_avg
    )

if gen_error:
    st.error(gen_error)
else:
    st.markdown(report)

st.divider()

# ==========================================
# DEBUG PANEL (اختياري — للتطوير)
# ==========================================
with st.expander("🔧 لوحة التصحيح (Debug Panel)", expanded=False):
    st.json({
        "historical_ctx": historical_ctx,
        "shoreline_normal": shoreline_normal,
        "weighted_avg_score": round(weighted_avg, 2),
        "simple_avg_score": round(simple_avg, 2),
        "is_inland": is_inland,
        "hours_analyzed": len(hourly_data)
    })

st.caption("© المستشار الفيزيائي الحاسم v6.2 Fixed | "
           "FIX: Marine/Weather time-alignment + Dirty-sea period logic + "
           "Écume wave_impact + Wind penalty + Hb breaking height + "
           "Rip current angles + Inland fallback + Swell cleansing + "
           "NameError guard + Weighted avg score + Cache consistency")
