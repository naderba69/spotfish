import streamlit as st
import folium
from streamlit_folium import st_folium
import requests
import math
import json
import os
import pandas as pd
import datetime
from typing import Dict, List, Optional

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

# ---------- إعدادات الصفحة ----------
st.set_page_config(page_title="Surfcasting Predictor", layout="wide")
st.title("🌊 مقياس ديناميكية الصيد بالقصبة (Surfcasting Dynamic Predictor)")

# ---------- الحالة الدائمة ----------
if "lat" not in st.session_state:
    st.session_state.lat = 36.4000
if "lon" not in st.session_state:
    st.session_state.lon = 10.6000
if "last_processed_coords" not in st.session_state:
    st.session_state.last_processed_coords = (None, None)
if "analysis_triggered" not in st.session_state:
    st.session_state.analysis_triggered = False
if "results_cache" not in st.session_state:
    st.session_state.results_cache = None
if "avg_score_cache" not in st.session_state:
    st.session_state.avg_score_cache = None
if "report_cache" not in st.session_state:
    st.session_state.report_cache = None

# ---------- دوال جلب البيانات ----------
@st.cache_data(ttl=1800)
def fetch_marine_data(lat: float, lon: float) -> Optional[Dict]:
    base_url = "https://marine-api.open-meteo.com/v1/marine"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wave_height,wave_direction,wave_period,wind_direction_10m,wind_speed_10m",
        "past_days": 2,
        "forecast_days": 3,
        "timeformat": "iso8601",
    }
    try:
        resp = requests.get(base_url, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "hourly" in data and data["hourly"].get("wave_height"):
            valid = [h for h in data["hourly"]["wave_height"] if h is not None]
            if valid and max(valid) < 0.1:
                return None
        return data
    except Exception:
        return None

@st.cache_data(ttl=1800)
def fetch_atmospheric_fallback(lat: float, lon: float) -> Dict:
    base_url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "past_days": 2,
        "forecast_days": 3,
        "timeformat": "iso8601",
    }
    resp = requests.get(base_url, params=params, timeout=10)
    resp.raise_for_status()
    return resp.json()

@st.cache_data(ttl=7200)
def get_shoreline_normal(lat: float, lon: float) -> float:
    delta = 0.001
    points = [f"{lat+dlat},{lon+dlon}" for dlat in (-delta, 0, delta) for dlon in (-delta, 0, delta)]
    url = "https://api.opentopodata.org/v1/srtm30m"
    resp = requests.get(url, params={"locations": "|".join(points)}, timeout=10)
    if resp.status_code != 200:
        return 0.0
    elev = [r["elevation"] for r in resp.json()["results"]]
    dz_dlat = (elev[7] - elev[1]) / (2 * delta * 111320)
    dz_dlon = (elev[5] - elev[3]) / (2 * delta * 111320 * math.cos(math.radians(lat)))
    angle = math.degrees(math.atan2(-dz_dlon, -dz_dlat))
    return (angle + 360) % 360

# ---------- دوال حسابية ----------
def circular_diff(a: float, b: float) -> float:
    diff = abs(a - b) % 360
    return diff if diff <= 180 else 360 - diff

def safe_float(value, default=0.0):
    return float(value) if value is not None else default

def analyze_hour(hour_idx: int, hourly: Dict, baseline_dirty: bool, shore_normal: float) -> Dict:
    wave_h   = safe_float(hourly["wave_height"][hour_idx])
    wave_dir = safe_float(hourly["wave_direction"][hour_idx])
    wave_per = safe_float(hourly["wave_period"][hour_idx])
    wind_spd = safe_float(hourly["wind_speed_10m"][hour_idx])
    wind_dir = safe_float(hourly["wind_direction_10m"][hour_idx])

    wave_angle_diff = circular_diff(wave_dir, shore_normal)
    wind_angle_diff = circular_diff(wind_dir, shore_normal)
    wave_angle_rad = math.radians(wave_angle_diff)

    wind_impact = "ريح وش مستقيمة وممتازة"
    if 30 < wind_angle_diff < 150:
        wind_impact = "ريح جنب مائلة جارفة"

    V_longshore = 0.0
    if wave_h > 0.1 and wave_angle_diff > 15:
        V_longshore = 1.17 * math.sqrt(9.81 * wave_h) * math.sin(wave_angle_rad) * math.cos(wave_angle_rad)

    A_exposed = 0.0025
    rho = 1025
    Cd = 1.5
    F_drag = 0.5 * rho * Cd * A_exposed * (V_longshore ** 2)

    if F_drag > 2.5:
        lead_rec = "140g-150g سبايك (Spike)"
    elif F_drag > 1.0:
        lead_rec = "120g-130g هرمي (Pyramid)"
    else:
        lead_rec = "100g-110g ثقالة عادية"

    rip_risk = "منخفض"
    if wave_h > 1.2 and wave_per > 8.0 and wave_angle_diff < 30:
        rip_risk = "عالي جداً (خطر الرمي في المجرى)"

    wave_wind_diff = circular_diff(wave_dir, wind_dir)
    opposing_wind = 90 < wave_wind_diff < 270

    debris_status = "نظيف"
    if baseline_dirty:
        if 4 <= wave_per <= 7 and wave_h <= 1.1 and wave_angle_diff < 30 and opposing_wind:
            debris_status = "البحر ينظف نفسه (مصفاة الموج تقذف العشب نحو الرمل)"
        else:
            debris_status = "بحر مدرر بكثافة"
    else:
        if wave_h > 1.2 and wave_per > 8.0:
            debris_status = "بداية تقليب القاع واتساخ الماء"

    score = 10.0
    if wave_h < 0.2:
        score -= 3.0
    if debris_status == "بحر مدرر بكثافة":
        score -= 4.5
    if wind_impact == "ريح جنب مائلة جارفة":
        score -= 4.0
    if wave_h > 0.5 and 6 <= wave_per <= 10 and wave_angle_diff < 30:
        score += 1.5
    if debris_status == "البحر ينظف نفسه (مصفاة الموج تقذف العشب نحو الرمل)":
        score += 2.0
    score = max(0.0, min(10.0, score))

    local_hour = (hour_idx % 24 + 1) % 24  # UTC+1
    time_str = f"{local_hour:02d}:00"

    return {
        "time": time_str,
        "wave_height": round(wave_h, 2),
        "wave_direction": round(wave_dir, 1),
        "wave_period": round(wave_per, 1),
        "wind_speed": round(wind_spd, 1),
        "wind_direction": round(wind_dir, 1),
        "wave_angle_diff": round(wave_angle_diff, 1),
        "wind_angle_diff": round(wind_angle_diff, 1),
        "wind_impact": wind_impact,
        "V_longshore": round(V_longshore, 2),
        "F_drag": round(F_drag, 2),
        "lead_rec": lead_rec,
        "rip_risk": rip_risk,
        "debris_status": debris_status,
        "score": round(score, 2),
    }

# ---------- عرض الجدول الاحتياطي ----------
def render_table_report(results: List[Dict], spot_name: str, day_label: str, avg_score: float):
    st.markdown(f"### 🧾 تقرير تفصيلي لـ {spot_name} - {day_label}")
    df = pd.DataFrame(results)
    st.dataframe(df[[
        "time", "wave_height", "wave_direction", "wave_period",
        "wind_speed", "wind_direction", "wind_impact", "V_longshore",
        "F_drag", "lead_rec", "rip_risk", "debris_status", "score"
    ]], use_container_width=True)

# ---------- توليد التقرير عبر Gemini مع نماذج احتياطية ----------
def generate_gemini_report(prompt: str) -> Optional[str]:
    if not GENAI_AVAILABLE or not os.environ.get("GEMINI_API_KEY"):
        return None
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    # قائمة النماذج بالترتيب الذي نحاوله
    models_to_try = [
        "gemini-1.5-flash",
        "gemini-2.0-flash-exp",
        "gemini-1.5-pro",
        "gemini-1.0-pro",
    ]
    for model_name in models_to_try:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            # إذا كان الخطأ 404 نتجاوزه لنجرب النموذج التالي
            if "404" in str(e):
                continue
            # أي خطأ آخر نعرضه ونتوقف
            else:
                raise e
    raise RuntimeError("جميع نماذج Gemini فشلت (تأكد من صلاحية المفتاح وتفعيل النماذج)")

# ---------- دالة الأيام بالعربية ----------
def get_day_labels():
    weekdays_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
    today = datetime.date.today()
    labels = []
    for offset in range(3):
        d = today + datetime.timedelta(days=offset)
        weekday = weekdays_ar[d.weekday()]  # Monday=0 -> الإثنين
        if offset == 0:
            labels.append(f"اليوم ({weekday})")
        elif offset == 1:
            labels.append(f"غداً ({weekday})")
        else:
            labels.append(f"بعد غد ({weekday})")
    return labels

# ---------- التطبيق الرئيسي ----------
def main():
    # الخريطة
    m = folium.Map(location=[st.session_state.lat, st.session_state.lon], zoom_start=7)
    folium.Marker(
        [st.session_state.lat, st.session_state.lon],
        popup="📍 موقع الصيد",
        icon=folium.Icon(color="red", icon="anchor"),
    ).add_to(m)

    # التقاط النقرة وتحديث الإحداثيات فقط دون تحليل
    map_data = st_folium(m, key="surfcast_map", height=400, width=700)
    if map_data and map_data.get("last_clicked"):
        new_lat = map_data["last_clicked"]["lat"]
        new_lon = map_data["last_clicked"]["lng"]
        if (new_lat, new_lon) != st.session_state.last_processed_coords:
            st.session_state.lat = new_lat
            st.session_state.lon = new_lon
            st.session_state.last_processed_coords = (new_lat, new_lon)
            # أي نقرة جديدة تلغي التحليل السابق
            st.session_state.analysis_triggered = False
            st.rerun()

    # قائمة الأيام الديناميكية
    day_labels = get_day_labels()
    day = st.selectbox("🗓️ حدد يوم الرحلة", day_labels)
    day_offset = day_labels.index(day)

    lat = st.session_state.lat
    lon = st.session_state.lon
    st.write(f"📍 الإحداثيات المختارة: `{lat:.4f}, {lon:.4f}`")

    # زر الفحص
    if st.button("🔍 فحص وتحليل الموقع", type="primary"):
        st.session_state.analysis_triggered = True
        st.rerun()

    # لا نكمل التحليل إلا إذا ضغط المستخدم على الزر
    if not st.session_state.analysis_triggered:
        return

    # ---------- بدء التحليل ----------
    with st.spinner("⏳ جاري جلب البيانات وتحليلها..."):
        marine_data = fetch_marine_data(lat, lon)
        fallback_used = False

        if marine_data is None:
            st.warning(
                "⚠️ الإحداثيات المختارة بعيدة عن الساحل أو لا تتوفر بيانات بحرية لها. "
                "سيتم استخدام بيانات الرياح فقط من نموذج الطقس الجوي، وستُعتبر معاملات الأمواج صفرية. "
                "يُرجى اختيار نقطة ساحلية للحصول على تحليل كامل."
            )
            fallback_used = True
            atmospheric = fetch_atmospheric_fallback(lat, lon)
            times = atmospheric["hourly"]["time"]
            marine_data = {
                "hourly": {
                    "time": times,
                    "wave_height": [0.0] * len(times),
                    "wave_direction": [0.0] * len(times),
                    "wave_period": [0.0] * len(times),
                    "wind_speed_10m": [safe_float(v) for v in atmospheric["hourly"]["wind_speed_10m"]],
                    "wind_direction_10m": [safe_float(v) for v in atmospheric["hourly"]["wind_direction_10m"]],
                }
            }

        hourly = marine_data["hourly"]

        # العكارة التاريخية
        if not fallback_used:
            past_h = [h for h in hourly["wave_height"][:48] if h is not None]
            past_p = [p for p in hourly["wave_period"][:48] if p is not None]
            avg_h = sum(past_h) / len(past_h) if past_h else 0
            avg_p = sum(past_p) / len(past_p) if past_p else 0
            sea_initially_dirty = avg_h > 1.2 and avg_p > 8.0
        else:
            sea_initially_dirty = False

        shore_normal = get_shoreline_normal(lat, lon)

        day_start = 48 + day_offset * 24
        day_end = day_start + 24

        if day_end > len(hourly["time"]):
            st.error("❌ بيانات الساعة غير كافية لليوم المطلوب.")
            st.stop()

        results = []
        for i in range(day_start, day_end):
            results.append(analyze_hour(i, hourly, sea_initially_dirty, shore_normal))

        avg_score = sum(r["score"] for r in results) / len(results)

        # تخزين النتائج مؤقتاً
        st.session_state.results_cache = results
        st.session_state.avg_score_cache = avg_score

    # ---------- الحكم النهائي ----------
    if avg_score >= 7.5:
        banner_color = "#28a745"
        verdict_text = "✅ استثنائي (مميز) – البحر مثالي ونظيف والمرسى ثابت تماماً"
    elif avg_score >= 5.0:
        banner_color = "#fd7e14"
        verdict_text = "⚠️ ممكن بتكتيك خاص – الرحلة صعبة لكنها ممكنة باستخدام أثقال متخصصة ونوافذ التوقيت"
    else:
        banner_color = "#dc3545"
        verdict_text = "🚫 مستحيل ووجب تغيير السبوت – إلغاء الرحلة أو تغيير المكان فوراً بسبب الأعشاب الكثيفة أو التيارات الجارفة"

    st.markdown(
        f"""
        <div style="background-color:{banner_color};padding:15px;border-radius:10px;margin-bottom:20px">
            <h2 style="color:white;text-align:center">{verdict_text}</h2>
            <p style="color:white;text-align:center">المعدل العام: {avg_score:.2f} / 10</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # ---------- اسم المكان ----------
    try:
        reverse_url = "https://nominatim.openstreetmap.org/reverse"
        reverse_params = {
            "format": "json",
            "lat": lat,
            "lon": lon,
            "zoom": 10,
            "accept-language": "ar",
        }
        headers = {"User-Agent": "SurfcastPredictor/1.0"}
        geo_resp = requests.get(reverse_url, params=reverse_params, headers=headers, timeout=5)
        if geo_resp.status_code == 200:
            spot_name = geo_resp.json().get("display_name", "موقع الساحل المختار")
        else:
            spot_name = "موقع الساحل المختار"
    except Exception:
        spot_name = "موقع الساحل المختار"

    # ---------- تقرير Gemini ----------
    prompt = f"""
أنت خبير صيد بالقصبة تونسي. قم بترجمة وسياق البيانات التالية إلى تقرير مفصل بالعربية الدارجة التونسية، باستخدام مصطلحات الصيادين المحليين (مثل: بحر مدرر، مصفاة الموج، إيكوم، الريح الجنب، سبايك، ثقالة هرمية...).
لا تغير أي قيمة حسابية أو نتيجة. اذكر الأسباب والنتائج ساعة بساعة، مع الإشارة الدقيقة إلى توقيت تحول البحر من حال إلى آخر.

**اسم الموقع: {spot_name}**
**اليوم المختار: {day}**
**المعدل العام: {avg_score:.2f} / 10**

**البيانات الساعية (JSON):**
{json.dumps(results, ensure_ascii=False, indent=2)}

نظم التقرير بالعناوين التالية:
1. ## التفصيل الزمني ساعة بساعة (حركة الأعشاب، العكارة، صفاء المياه)
2. ## سلوك الثقالة الميكانيكي وسرعة التيار (نيوتن والانجراف)
3. ## تطور حزام الإيكوم الأبيض وقمم النشاط البيولوجي للأسماك
4. ## الحكم النهائي القاطع (استثنائي، ممكن، أو مستحيل)
5. ## الاستراتيجية التكتيكية للصيد (نوع الثقالة، وزنها، مسافة الرمي، تحسين الطعم) أو اقتراح نافذة جوية بديلة في حالة الإلغاء
"""
    try:
        with st.spinner("🧠 يولد التقرير الذكي..."):
            report = generate_gemini_report(prompt)
            st.markdown(report, unsafe_allow_html=True)
    except Exception as e:
        st.error(f"⚠️ تعذر توليد التقرير الذكي: {e}")
        st.info("يُعرض جدول البيانات المباشر.")
        render_table_report(results, spot_name, day, avg_score)

if __name__ == "__main__":
    main()
