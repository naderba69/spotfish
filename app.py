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
    page_title="المحلل الهيدروديناميكي الشامل | تونس v5.0",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    .stMetric {background: #0e1117; padding: 15px; border-radius: 8px; border-left: 4px solid #1f77b4;}
    .go-excellent {color: #00ff00; font-weight: bold; font-size: 1.3em;}
    .go-good {color: #ffff00; font-weight: bold; font-size: 1.3em;}
    .go-warning {color: #ffa500; font-weight: bold; font-size: 1.3em;}
    .go-nogo {color: #ff0000; font-weight: bold; font-size: 1.3em;}
    .risk-high {color: #ff4b4b; font-weight: bold;}
    .risk-med {color: #ffa500; font-weight: bold;}
    .risk-low {color: #00cc00; font-weight: bold;}
    .drift-yes {color: #ff4b4b; font-weight: bold;}
    .drift-no {color: #00cc00;}
    .debris-heavy {color: #ff4b4b; font-weight: bold;}
    .debris-med {color: #ffa500;}
    .debris-light {color: #ffff00;}
    .debris-clean {color: #00cc00;}
</style>
""", unsafe_allow_html=True)

# Session state
if 'lat_a' not in st.session_state:
    st.session_state.lat_a = 36.4000  # الحمامات
if 'lon_a' not in st.session_state:
    st.session_state.lon_a = 10.6000
if 'lat_b' not in st.session_state:
    st.session_state.lat_b = 36.8200  # نابل
if 'lon_b' not in st.session_state:
    st.session_state.lon_b = 10.7800
if 'compare_mode' not in st.session_state:    st.session_state.compare_mode = False

st.title("🌊 المحلل الهيدروديناميكي العسكري للصيد v5.0")
st.markdown("#### **محرك فيزيائي حقيقي + 3 أيام + مقارنة موقعين + نماذج السحب والتيارات**")

# ==========================================
# HELPER: HAVERSINE
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

def classify_score(score):
    if score >= 7.5:
        return "🟢 ممتاز (GO+)", "go-excellent", "GO"
    elif score >= 5.0:
        return "🟡 ممكن (GO)", "go-good", "GO"
    elif score >= 4.0:
        return "🟠 تحذير", "go-warning", "WARNING"
    else:
        return "🔴 مستحيل (NO-GO)", "go-nogo", "NO-GO"

# ==========================================
# ADVANCED PHYSICS MODELS (TRUE HYDRODYNAMICS)
# ==========================================
def calculate_longshore_current(wave_height, wave_period, wave_impact_angle_deg):
    """
    حساب سرعة التيار الموازي للشاطئ (Longshore Current)
    V = (g × T × H² × sin(2θ)) / (16 × d)
    """
    if wave_height < 0.1 or wave_period < 1.0:
        return 0.0
    
    g = 9.81
    theta_rad = math.radians(wave_impact_angle_deg)
    d = 1.3 * wave_height
    
    if d < 0.1:
        d = 0.1    
    v_longshore = (g * wave_period * (wave_height ** 2) * math.sin(2 * theta_rad)) / (16 * d)
    return abs(v_longshore)

def calculate_lead_drag_force(current_velocity_ms, lead_weight_g=120, lead_type="pyramid"):
    """
    حساب قوة السحب على الرصاصة ومقارنتها بقوة التثبيت
    F_drag = 0.5 × ρ × Cd × A × V²
    """
    g = 9.81
    rho = 1025  # كثافة مياه البحر (كغ/م³)
    
    cd_values = {
        "pyramid": 0.30,
        "grippo": 0.35,
        "spider": 0.40,
        "olive": 0.50,
        "ball": 0.47
    }
    cd = cd_values.get(lead_type, 0.45)
    
    lead_volume = (lead_weight_g / 1000) / 11340  # كثافة الرصاص
    lead_radius = ((3 * lead_volume) / (4 * math.pi)) ** (1/3)
    cross_section_area = math.pi * (lead_radius ** 2)
    
    f_drag = 0.5 * rho * cd * cross_section_area * (current_velocity_ms ** 2)
    
    lead_mass_kg = lead_weight_g / 1000
    f_grip = lead_mass_kg * g * 0.6  # معامل احتكاك الرمل
    
    drift_ratio = f_drag / f_grip if f_grip > 0 else 999
    
    return {
        "drag_force_n": round(f_drag, 3),
        "grip_force_n": round(f_grip, 3),
        "drift_ratio": round(drift_ratio, 2),
        "will_drift": drift_ratio > 0.8
    }

def calculate_rip_current_risk(wave_height, wave_period, shoreline_normal, wave_direction, fetch_coverage):
    """مؤشر خطر التيارات الساحبة (Rip Currents)"""
    risk_score = 0.0
    
    if wave_height > 1.0 and wave_period > 7.0:
        risk_score += 2.0
    
    if shoreline_normal is not None:
        wave_impact = abs(wave_direction - shoreline_normal)
        if wave_impact > 180:
            wave_impact = 360 - wave_impact        
        if wave_impact < 20 and fetch_coverage > 0.6:
            risk_score += 1.5
    
    if risk_score >= 3.0:
        return "عالي الخطورة", risk_score
    elif risk_score >= 1.5:
        return "متوسط", risk_score
    else:
        return "منخفض", risk_score

def calculate_surface_debris_index(wind_speed, wind_direction_going_to, shoreline_normal, is_historically_dirty):
    """مؤشر نقل الأعشاب السطحية"""
    debris_score = 0.0
    
    if shoreline_normal is not None:
        wind_to_shore = abs(wind_direction_going_to - shoreline_normal)
        if wind_to_shore > 180:
            wind_to_shore = 360 - wind_to_shore
        
        if wind_to_shore < 30 and wind_speed > 15:
            debris_score += 2.0
        elif wind_to_shore < 60 and wind_speed > 20:
            debris_score += 1.5
    
    if is_historically_dirty:
        debris_score += 2.0
    
    if wind_speed > 25:
        debris_score += 1.0
    
    if debris_score >= 4.0:
        return "كثيف جداً", debris_score
    elif debris_score >= 2.5:
        return "متوسط", debris_score
    elif debris_score >= 1.0:
        return "خفيف", debris_score
    else:
        return "نظيف", debris_score

def recommend_lead_weight(current_velocity_ms, wave_height, lead_type="pyramid"):
    """توصية بوزن الرصاصة المطلوب لتثبيت المونتاج"""
    cd_values = {"pyramid": 0.30, "grippo": 0.35, "spider": 0.40, "olive": 0.50, "ball": 0.47}
    cd = cd_values.get(lead_type, 0.45)
    g = 9.81
    rho = 1025
    friction_coef = 0.6
    
    # وزن أساسي يعتمد على سرعة التيار
    if current_velocity_ms < 0.3:        base_weight = 80
    elif current_velocity_ms < 0.6:
        base_weight = 100
    elif current_velocity_ms < 1.0:
        base_weight = 125
    elif current_velocity_ms < 1.5:
        base_weight = 150
    else:
        base_weight = 175
    
    # تعديل حسب ارتفاع الموج
    if wave_height > 1.2:
        base_weight += 25
    elif wave_height > 0.8:
        base_weight += 15
    
    # تعديل حسب نوع الرصاصة (الهرمي يحتاج وزن أقل)
    if lead_type == "pyramid":
        base_weight -= 10
    elif lead_type == "ball":
        base_weight += 20
    
    return max(80, min(200, base_weight))

# ==========================================
# SHORELINE ASPECT CALCULATOR
# ==========================================
@st.cache_data(ttl=86400, show_spinner=False)
def calculate_shoreline_aspect(lat, lon):
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
            return None, None, "unknown", "بيانات غير مكتملة"
                sea_bearings = []
        for p, elev in zip(points, elevations):
            if elev is None:
                continue
            if elev <= 0.5:
                sea_bearings.append(p["bearing"])
        
        if not sea_bearings:
            return None, None, "inland", "إحداثيات برية"
        
        sea_radians = [math.radians(b) for b in sea_bearings]
        avg_sin = sum(math.sin(r) for r in sea_radians) / len(sea_radians)
        avg_cos = sum(math.cos(r) for r in sea_radians) / len(sea_radians)
        shoreline_normal = math.degrees(math.atan2(avg_sin, avg_cos)) % 360
        
        fetch_coverage = len(sea_bearings) / 36.0
        
        if fetch_coverage >= 0.65:
            bay_type = "exposed"
        elif fetch_coverage >= 0.35:
            bay_type = "semi_sheltered"
        else:
            bay_type = "sheltered"
        
        return shoreline_normal, fetch_coverage, bay_type, None
    except Exception as e:
        return None, None, "unknown", str(e)

# ==========================================
# REVERSE GEOCODING
# ==========================================
@st.cache_data(ttl=86400, show_spinner=False)
def get_location_name(lat, lon):
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json", "accept-language": "ar", "zoom": 10},
            headers={"User-Agent": "TunisianSurfcastingAdvisor/5.0"},
            timeout=8
        )
        data = resp.json()
        address = data.get("address", {})
        name = (
            address.get("hamlet") or address.get("village") or
            address.get("town") or address.get("city") or
            address.get("state") or "ساحل تونسي"
        )
        region = address.get("state", "")
        return f"{name}، {region}" if region and name != region else name
    except Exception:        return "منطقة ساحلية"

# ==========================================
# DATA FETCHING
# ==========================================
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_marine_weather(lat, lon):
    marine_params = {
        "latitude": lat, "longitude": lon,
        "hourly": "wave_height,wave_direction,wave_period",
        "past_days": 2, "forecast_days": 5, "timezone": "auto"
    }
    weather_params = {
        "latitude": lat, "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m",
        "past_days": 2, "forecast_days": 5, "timezone": "auto"
    }
    
    is_inland = False
    marine_data = None
    
    try:
        resp = requests.get("https://marine-api.open-meteo.com/v1/marine", params=marine_params, timeout=12)
        resp.raise_for_status()
        marine_data = resp.json()
        if "error" in marine_data:
            raise ValueError(marine_data.get("reason", "Error"))
    except Exception:
        is_inland = True
    
    try:
        resp = requests.get("https://api.open-meteo.com/v1/forecast", params=weather_params, timeout=12)
        resp.raise_for_status()
        weather_data = resp.json()
    except Exception as e:
        return None, None, True, f"فشل جلب الطقس: {e}"
    
    return marine_data, weather_data, is_inland, None

# ==========================================
# 3-DAY PHYSICS ENGINE
# ==========================================
def compute_3day_scores(marine_data, weather_data, is_inland, shoreline_normal, bay_type, fetch_coverage):
    time_array = weather_data['hourly']['time']
    wind_speed = weather_data['hourly']['wind_speed_10m']
    wind_dir_raw = weather_data['hourly']['wind_direction_10m']
    
    time_dt = []
    for t in time_array:
        try:            time_dt.append(datetime.fromisoformat(t))
        except Exception:
            time_dt.append(None)
    
    if not is_inland and marine_data:
        wave_height = marine_data['hourly']['wave_height']
        wave_dir = marine_data['hourly']['wave_direction']
        wave_period = marine_data['hourly']['wave_period']
    else:
        n = len(wind_speed)
        wave_height = [0.0] * n
        wave_dir = [0.0] * n
        wave_period = [0.0] * n
    
    valid_times = [(i, t) for i, t in enumerate(time_dt) if t is not None]
    if not valid_times:
        return None, "فشل تحليل الزمن"
    
    first_date = valid_times[0][1].date()
    days_data = {}
    
    for day_offset in range(3):
        target_date = first_date + timedelta(days=day_offset)
        day_indices = [i for i, t in valid_times if t.date() == target_date]
        if not day_indices:
            continue
        
        start_idx = day_indices[0]
        end_idx = day_indices[-1] + 1
        
        past_end = start_idx
        past_start = max(0, past_end - 48)
        
        past_wh = [x for x in wave_height[past_start:past_end] if x is not None]
        past_wp = [x for x in wave_period[past_start:past_end] if x is not None]
        
        avg_past_wh = sum(past_wh) / max(1, len(past_wh)) if past_wh else 0
        avg_past_wp = sum(past_wp) / max(1, len(past_wp)) if past_wp else 0
        is_dirty = (avg_past_wh > 1.2) and (avg_past_wp > 8.0)
        
        hourly = []
        for i in range(start_idx, end_idx):
            score = 10.0
            
            wh = wave_height[i] if i < len(wave_height) and wave_height[i] is not None else 0.0
            wd = wave_dir[i] if i < len(wave_dir) and wave_dir[i] is not None else 0.0
            wp = wave_period[i] if i < len(wave_period) and wave_period[i] is not None else 0.0
            ws_raw = wind_speed[i] if i < len(wind_speed) and wind_speed[i] is not None else 0.0
            wdir_raw = wind_dir_raw[i] if i < len(wind_dir_raw) and wind_dir_raw[i] is not None else 0.0
            time_str = time_array[i]            
            wdir_going_to = (wdir_raw + 180) % 360
            
            # احتكاك اليابسة
            ws_effective = ws_raw
            wind_land_factor = 1.0
            if shoreline_normal is not None:
                wind_to_shore_angle = abs(wdir_going_to - shoreline_normal)
                if wind_to_shore_angle > 180:
                    wind_to_shore_angle = 360 - wind_to_shore_angle
                
                if wind_to_shore_angle > 90:
                    wind_land_factor = 0.4
                    ws_effective = ws_raw * 0.4
                elif wind_to_shore_angle > 60:
                    wind_land_factor = 0.75
                    ws_effective = ws_raw * 0.75
            
            # معامل الخليج
            bay_wave_factor = 1.0
            if bay_type == "sheltered":
                bay_wave_factor = 0.5
            elif bay_type == "semi_sheltered":
                bay_wave_factor = 0.75
            
            wh_eff = wh * bay_wave_factor
            
            # زاوية اصطدام الموج
            if shoreline_normal is not None:
                wave_impact = abs(wd - shoreline_normal)
                if wave_impact > 180:
                    wave_impact = 360 - wave_impact
            else:
                wave_impact = 0
            
            wind_wave_angle = abs(wdir_going_to - wd)
            if wind_wave_angle > 180:
                wind_wave_angle = 360 - wind_wave_angle
            
            is_wave_frontal = wave_impact <= 25
            is_wave_lateral = 30 < wave_impact < 150
            is_wind_aligned = wind_wave_angle <= 25 or wind_wave_angle >= 155
            
            # ====== النماذج الفيزيائية الحقيقية ======
            v_longshore = calculate_longshore_current(wh_eff, wp, wave_impact)
            v_longshore_kmh = v_longshore * 3.6
            
            lead_analysis = calculate_lead_drag_force(v_longshore, 120, "pyramid")
            recommended_weight = recommend_lead_weight(v_longshore, wh_eff, "pyramid")
                        rip_risk, rip_score = calculate_rip_current_risk(
                wh, wp, shoreline_normal, wd,
                fetch_coverage if fetch_coverage else 0.5
            )
            
            debris_status, debris_score_val = calculate_surface_debris_index(
                ws_effective, wdir_going_to, shoreline_normal, is_dirty
            )
            
            # ====== العقوبات الأساسية ======
            if wh_eff < 0.3:
                score -= 3.0
            
            is_weedy = (wh_eff > 1.2 and wp > 8.0)
            if is_weedy or is_dirty:
                score -= 4.5
            
            # ====== عقوبات النماذج الفيزيائية ======
            if v_longshore_kmh > 1.5:
                score -= 3.0
            elif v_longshore_kmh > 0.8:
                score -= 1.5
            
            if lead_analysis["will_drift"]:
                score -= 2.5
            
            if rip_risk == "عالي الخطورة":
                score -= 3.0
            elif rip_risk == "متوسط":
                score -= 1.5
            
            if debris_status == "كثيف جداً":
                score -= 2.0
            elif debris_status == "متوسط":
                score -= 1.0
            
            # ====== المكافآت ======
            if (0.5 <= wh_eff <= 1.2 and ws_effective > 12.0 and
                is_wind_aligned and is_wave_frontal and wind_land_factor >= 0.75):
                score += 1.5
            
            is_cleansing = (4.0 <= wp <= 7.0 and wh_eff > 0.5 and
                          is_wind_aligned and is_dirty and is_wave_frontal)
            if is_cleansing:
                score += 2.0
                if is_dirty and not is_weedy:
                    score += 4.5
            
            score = max(0.0, min(10.0, score))
                        hourly.append({
                "time": time_str,
                "score": round(score, 1),
                "wh": round(wh_eff, 2),
                "wp": round(wp, 1),
                "ws": round(ws_effective, 1),
                "impact": round(wave_impact, 1),
                "longshore_ms": round(v_longshore, 2),
                "longshore_kmh": round(v_longshore_kmh, 1),
                "lead_drag_n": lead_analysis["drag_force_n"],
                "lead_drift": lead_analysis["will_drift"],
                "lead_recommended_g": recommended_weight,
                "rip_risk": rip_risk,
                "debris": debris_status
            })
        
        avg_score = sum(h["score"] for h in hourly) / len(hourly) if hourly else 0
        confidence = ["🟢 عالية (90%+)", "🟡 عالية-متوسطة (80%+)", "🟠 متوسطة (65%+)"][day_offset]
        
        days_data[target_date.isoformat()] = {
            "hourly": hourly,
            "avg_score": round(avg_score, 1),
            "is_dirty": is_dirty,
            "avg_past_wh": round(avg_past_wh, 2),
            "avg_past_wp": round(avg_past_wp, 1),
            "confidence": confidence,
            "day_offset": day_offset
        }
    
    return days_data, None

# ==========================================
# GEMINI REPORT
# ==========================================
@st.cache_data(ttl=1800, show_spinner=False)
def generate_gemini_report(days_a, days_b, info_a, info_b, compare_mode):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, "GEMINI_API_KEY مفقود"
    
    try:
        genai.configure(api_key=api_key)
        config = genai.GenerationConfig(temperature=0.1, top_p=0.1, max_output_tokens=3500)
        model = genai.GenerativeModel('gemini-1.5-flash', generation_config=config)
        
        bay_ar = {"exposed": "مكشوف", "semi_sheltered": "شبه محمي", "sheltered": "محمي"}
        
        payload = {
            "location_a": {
                "name": info_a["name"],                "bay": bay_ar.get(info_a["bay_type"], info_a["bay_type"]),
                "shoreline_normal": round(info_a["shoreline_normal"], 1) if info_a["shoreline_normal"] else None,
                "days": days_a
            }
        }
        
        if compare_mode and days_b:
            payload["location_b"] = {
                "name": info_b["name"],
                "bay": bay_ar.get(info_b["bay_type"], info_b["bay_type"]),
                "shoreline_normal": round(info_b["shoreline_normal"], 1) if info_b["shoreline_normal"] else None,
                "days": days_b
            }
        
        json_str = json.dumps(payload, ensure_ascii=False)
        
        comparison_part = ""
        if compare_mode and days_b:
            comparison_part = """
## ⚖️ المقارنة التكتيكية بين الموقعين (3 أيام)
(قارن فيزيائياً: أيهما أقل تيار موازي؟ أيهما أقل انجراف رصاص؟ أيهما أنظف من الأعشاب؟)

## 🏆 التوصية النهائية لكل يوم
(الموقع الأفضل لليوم، لغداً، ولما بعد غد)
"""
        
        prompt = f"""
أنت خبير محيطات ساحلية تونسي وصياد محترف متخصص في هيدروديناميكا Surfcasting.

البيانات الكاملة لـ 3 أيام مع النماذج الفيزيائية الحقيقية:
{json_str}

حقول البيانات الجديدة (الحرجة):
- longshore_ms: سرعة التيار الموازي للشاطئ (م/ث) - محسوبة بمعادلة فيزيائية
- longshore_kmh: نفس السرعة بـ كم/س
- lead_drag_n: قوة السحب على الرصاصة (نيوتن)
- lead_drift: هل ستنجرف الرصاصة؟ (true/false)
- lead_recommended_g: الوزن الموصى به للرصاص (جرام) - احترم هذا الرقم
- rip_risk: خطر التيارات الساحبة (منخفض/متوسط/عالي الخطورة)
- debris: كثافة الأعشاب السطحية (نظيف/خفيف/متوسط/كثيف جداً)

⚠️ قواعد صارمة:
1. ابدأ بـ # مباشرة (لا مقدمات، لا "بالتأكيد")
2. لا تخترع أرقاماً - استخدم البيانات المرفقة فقط
3. التصنيف: 🟢 ممتاز (≥7.5) | 🟡 ممكن (5.0-7.4) | 🟠 تحذير (4.0-4.9) | 🔴 مستحيل (<4.0)
4. حلل "الموج ينظف نفسه" و "تيار الحمل" و "Écume" و "بحر مدرر"
5. استخدم المصطلحات التونسية: plomb, bas de ligne, daurade, loup, marbré, ورطة، منكوس، بحر مدرر، تيار الحمل

التزم بهذا القالب:
# 🎯 التقرير الهيدروديناميكي الشامل (3 أيام)

(فقرة افتتاحية عن طبيعة الأيام الثلاثة)

## 📅 اليوم
### 🌊 التحليل الحركي والفيزيائي
(الموج، الرياح، **سرعة التيار الموازي**، **خطر التيارات الساحبة**، **كثافة الأعشاب**)
### ⚓ سلوك الرصاصة
(هل ستنجرف؟ ما الوزن المطلوب حسب lead_recommended_g؟)
### 🎯 التصنيف والقرار
(التصنيف + GO/NO-GO)
### 🎣 التكتيك
(نوع الرصاص، الوزن الدقيق، الطعم، مسافة الرمي)

## 📅 غداً
### 🌊 التحليل الحركي والفيزيائي
(تحليل كامل + هل يحدث "الموج ينظف نفسه"؟)
### ⚓ سلوك الرصاصة
### 🎯 التصنيف والقرار
### 🎣 التكتيك

## 📅 بعد غد (مع تحذير الثقة)
### 🌊 التحليل الحركي والفيزيائي
### ⚓ سلوك الرصاصة
### 🎯 التصنيف والقرار
### 🎣 التكتيك

{comparison_part if compare_mode else ""}

## 📋 الملخص التنفيذي
| اليوم | الموقع | النقاط | التيار الموازي | انجراف الرصاصة | الأعشاب | القرار |
(املأ الجدول بدقة)

## 🎯 أفضل نافذة زمنية على الإطلاق
(أفضل يوم + ساعة + موقع مع التبرير الفيزيائي الكامل)
"""
        
        response = model.generate_content(prompt)
        return response.text, None
    except Exception as e:
        return None, str(e)

# ==========================================
# MAIN UI
# ==========================================
st.subheader("🗺️ اختر مواقع الصيد")

tab_single, tab_compare = st.tabs(["📍 موقع واحد", "⚖️ مقارنة موقعين"])

with tab_single:    st.session_state.compare_mode = False
    col_map, col_info = st.columns([2, 1])
    
    with col_map:
        m = folium.Map(location=[st.session_state.lat_a, st.session_state.lon_a], zoom_start=10)
        folium.Marker(
            [st.session_state.lat_a, st.session_state.lon_a],
            tooltip="الموقع المستهدف",
            icon=folium.Icon(color="red", icon="anchor", prefix="fa")
        ).add_to(m)
        map_data = st_folium(m, width=None, height=450, returned_objects=["last_clicked"], key="single_map")
        
        if map_data and map_data.get("last_clicked"):
            new_lat = round(map_data["last_clicked"]["lat"], 4)
            new_lon = round(map_data["last_clicked"]["lng"], 4)
            if new_lat != st.session_state.lat_a or new_lon != st.session_state.lon_a:
                st.session_state.lat_a = new_lat
                st.session_state.lon_a = new_lon
                st.rerun()
    
    with col_info:
        st.metric("الإحداثيات", f"{st.session_state.lat_a}°, {st.session_state.lon_a}°")
        name_a = get_location_name(st.session_state.lat_a, st.session_state.lon_a)
        st.info(f"📌 **{name_a}**")

with tab_compare:
    st.session_state.compare_mode = True
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🅰️ الموقع الأول")
        m_a = folium.Map(location=[st.session_state.lat_a, st.session_state.lon_a], zoom_start=10)
        folium.Marker(
            [st.session_state.lat_a, st.session_state.lon_a],
            tooltip="الموقع A",
            icon=folium.Icon(color="red", icon="anchor", prefix="fa")
        ).add_to(m_a)
        map_a = st_folium(m_a, width=None, height=350, returned_objects=["last_clicked"], key="map_a")
        if map_a and map_a.get("last_clicked"):
            new_lat = round(map_a["last_clicked"]["lat"], 4)
            new_lon = round(map_a["last_clicked"]["lng"], 4)
            if new_lat != st.session_state.lat_a or new_lon != st.session_state.lon_a:
                st.session_state.lat_a = new_lat
                st.session_state.lon_a = new_lon
                st.rerun()
        name_a = get_location_name(st.session_state.lat_a, st.session_state.lon_a)
        st.info(f"📌 **{name_a}**")
    
    with col2:
        st.markdown("### 🅱️ الموقع الثاني")        m_b = folium.Map(location=[st.session_state.lat_b, st.session_state.lon_b], zoom_start=10)
        folium.Marker(
            [st.session_state.lat_b, st.session_state.lon_b],
            tooltip="الموقع B",
            icon=folium.Icon(color="blue", icon="anchor", prefix="fa")
        ).add_to(m_b)
        map_b = st_folium(m_b, width=None, height=350, returned_objects=["last_clicked"], key="map_b")
        if map_b and map_b.get("last_clicked"):
            new_lat = round(map_b["last_clicked"]["lat"], 4)
            new_lon = round(map_b["last_clicked"]["lng"], 4)
            if new_lat != st.session_state.lat_b or new_lon != st.session_state.lon_b:
                st.session_state.lat_b = new_lat
                st.session_state.lon_b = new_lon
                st.rerun()
        name_b = get_location_name(st.session_state.lat_b, st.session_state.lon_b)
        st.info(f"📌 **{name_b}**")

st.divider()

# ==========================================
# PROCESSING
# ==========================================
st.subheader("⚙️ تحليل 3 أيام مع النماذج الفيزيائية")

# Location A
with st.spinner(f"تحليل {name_a}..."):
    sn_a, fc_a, bt_a, err_a = calculate_shoreline_aspect(st.session_state.lat_a, st.session_state.lon_a)
    if bt_a == "inland":
        st.error(f"🚫 {name_a}: إحداثيات برية")
        st.stop()
    m_data_a, w_data_a, inland_a, err_f_a = fetch_marine_weather(st.session_state.lat_a, st.session_state.lon_a)
    if err_f_a:
        st.error(err_f_a)
        st.stop()
    days_a, err_s_a = compute_3day_scores(m_data_a, w_data_a, inland_a, sn_a, bt_a, fc_a)
    if err_s_a:
        st.error(err_s_a)
        st.stop()

# Location B
days_b = None
sn_b, fc_b, bt_b = None, None, None
name_b_display = ""
if st.session_state.compare_mode:
    name_b_display = name_b
    with st.spinner(f"تحليل {name_b_display}..."):
        sn_b, fc_b, bt_b, err_b = calculate_shoreline_aspect(st.session_state.lat_b, st.session_state.lon_b)
        if bt_b == "inland":
            st.warning(f"⚠️ {name_b_display}: إحداثيات برية - تم تجاهل المقارنة")
            st.session_state.compare_mode = False        else:
            m_data_b, w_data_b, inland_b, err_f_b = fetch_marine_weather(st.session_state.lat_b, st.session_state.lon_b)
            if err_f_b:
                st.warning(f"فشل جلب بيانات الموقع B")
            else:
                days_b, err_s_b = compute_3day_scores(m_data_b, w_data_b, inland_b, sn_b, bt_b, fc_b)
                if err_s_b:
                    st.warning(f"فشل تحليل الموقع B: {err_s_b}")
                    days_b = None

info_a = {"name": name_a, "shoreline_normal": sn_a, "bay_type": bt_a, "fetch": fc_a}
info_b = {
    "name": name_b_display,
    "shoreline_normal": sn_b,
    "bay_type": bt_b,
    "fetch": fc_b
}

st.success("✅ اكتمل التحليل الهيدروديناميكي الشامل")

# ==========================================
# 3-DAY VISUALIZATION
# ==========================================
st.subheader("📊 التصنيف العسكري والنماذج الفيزيائية")

day_names = ["اليوم", "غداً", "بعد غد"]
comparison_rows = []

for i, (date_str, data_a) in enumerate(sorted(days_a.items())):
    date_obj = datetime.fromisoformat(date_str).date()
    classification, css_class, decision = classify_score(data_a["avg_score"])
    
    # اسم اليوم بالعربية
    day_ar = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"][date_obj.weekday()]
    
    st.markdown(f"### 📅 {day_names[i]} - {day_ar} {date_obj.strftime('%d/%m/%Y')}")
    
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    with col_m1:
        st.markdown(f"**{name_a}**")
        st.markdown(f"<span class='{css_class}'>{classification}</span>", unsafe_allow_html=True)
        st.metric("المتوسط", f"{data_a['avg_score']}/10")
    with col_m2:
        st.markdown(f"**الثقة:** {data_a['confidence']}")
        st.markdown(f"**البحر تاريخياً:** {'🟤 مدرر' if data_a['is_dirty'] else '🔵 نظيف'}")
    with col_m3:
        avg_longshore = sum(h["longshore_kmh"] for h in data_a["hourly"]) / len(data_a["hourly"])
        st.metric("التيار الموازي (متوسط)", f"{avg_longshore:.1f} كم/س")
    with col_m4:
        drift_hours = sum(1 for h in data_a["hourly"] if h["lead_drift"])        st.metric("ساعات انجراف الرصاصة", f"{drift_hours}/{len(data_a['hourly'])}")
    
    # جدول A
    df_a = pd.DataFrame(data_a["hourly"])
    df_a_display = df_a[[
        "time", "score", "wh", "wp", "ws", "impact",
        "longshore_kmh", "lead_drift", "lead_recommended_g",
        "rip_risk", "debris"
    ]].copy()
    df_a_display.columns = [
        "الوقت", "النقاط", "الموج (م)", "الدور (ث)", "الرياح (كم/س)", "زاوية الاصطدام",
        "التيار الموازي (كم/س)", "انجراف الرصاص", "وزن الرصاص (غ)",
        "التيارات الساحبة", "الأعشاب"
    ]
    
    if st.session_state.compare_mode and days_b and date_str in days_b:
        data_b = days_b[date_str]
        classification_b, css_class_b, _ = classify_score(data_b["avg_score"])
        
        col_t1, col_t2 = st.columns(2)
        
        with col_t1:
            st.markdown(f"**🅰️ {name_a}** - <span class='{css_class}'>{classification}</span>", unsafe_allow_html=True)
            st.dataframe(df_a_display, use_container_width=True, hide_index=True, height=300)
        
        with col_t2:
            st.markdown(f"**🅱️ {name_b_display}** - <span class='{css_class_b}'>{classification_b}</span>", unsafe_allow_html=True)
            df_b = pd.DataFrame(data_b["hourly"])
            df_b_display = df_b[[
                "time", "score", "wh", "wp", "ws", "impact",
                "longshore_kmh", "lead_drift", "lead_recommended_g",
                "rip_risk", "debris"
            ]].copy()
            df_b_display.columns = df_a_display.columns
            st.dataframe(df_b_display, use_container_width=True, hide_index=True, height=300)
        
        winner = name_a if data_a["avg_score"] > data_b["avg_score"] else name_b_display if data_b["avg_score"] > data_a["avg_score"] else "تعادل"
        diff = abs(data_a["avg_score"] - data_b["avg_score"])
        st.info(f"🏆 **الأفضل لـ {day_names[i]}:** {winner} (فارق: {diff:.1f} نقطة)")
        
        comparison_rows.append({
            "اليوم": f"{day_names[i]} ({day_ar})",
            "الموقع A": f"{data_a['avg_score']}/10",
            "الموقع B": f"{data_b['avg_score']}/10",
            "الأفضل": winner,
            "الفارق": diff
        })
    else:
        st.dataframe(df_a_display, use_container_width=True, hide_index=True, height=350)
        st.divider()

# جدول المقارنة النهائي
if st.session_state.compare_mode and comparison_rows:
    st.subheader("⚖️ جدول المقارنة النهائي")
    df_comp = pd.DataFrame(comparison_rows)
    st.dataframe(df_comp, use_container_width=True, hide_index=True)

# أفضل نافذة
st.subheader("🎯 أفضل نافذة زمنية في الأيام الثلاثة")
all_hours = []
for date_str, data in days_a.items():
    for h in data["hourly"]:
        all_hours.append((h, name_a, date_str))
if st.session_state.compare_mode and days_b:
    for date_str, data in days_b.items():
        for h in data["hourly"]:
            all_hours.append((h, name_b_display, date_str))

best_overall = max(all_hours, key=lambda x: x[0]["score"])
st.success(f"""
⭐ **أفضل ساعة على الإطلاق:**
- 📍 الموقع: **{best_overall[1]}**
- 📅 التاريخ: {best_overall[2]}
- ⏰ الساعة: {best_overall[0]['time'][-5:]}
- 🎯 النقاط: **{best_overall[0]['score']}/10**
- 🌊 الموج: {best_overall[0]['wh']}م | 💨 الرياح: {best_overall[0]['ws']} كم/س
- 🌊 التيار الموازي: {best_overall[0]['longshore_kmh']} كم/س
- ⚓ وزن الرصاص الموصى به: **{best_overall[0]['lead_recommended_g']} جرام**
""")

st.divider()

# ==========================================
# GEMINI REPORT
# ==========================================
st.subheader("🧠 التقرير التكتيكي النهائي")

with st.spinner("جاري إعداد التقرير العسكري الشامل..."):
    report, err = generate_gemini_report(
        days_a, days_b, info_a, info_b, st.session_state.compare_mode
    )

if err:
    st.error(err)
else:
    st.markdown(report)

st.divider()
st.caption("© المحلل الهيدروديناميكي العسكري v5.0 | Longshore Current + Lead Drag + Rip Current + Surface Debris")
