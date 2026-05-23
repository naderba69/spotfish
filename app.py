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

# ══════════════════════════════════════════════════════════════
# CONFIG
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="مستشار الصيد | تونس",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
  body { direction: rtl; }
  .block-container { padding-top: 1rem; }
  .stMetric {
      background:#0e1117; padding:10px;
      border-radius:8px; border-left:4px solid #1f77b4;
  }
  .go-box   { background:#0a3d0a; padding:18px; border-radius:10px;
              border:2px solid #00ff00; }
  .nogo-box { background:#3d0a0a; padding:18px; border-radius:10px;
              border:2px solid #ff0000; }
  .warn-box { background:#3d2e0a; padding:18px; border-radius:10px;
              border:2px solid #ffa500; }
  .spot-card{ background:#0a1a2e; padding:14px; border-radius:8px;
              border:1px solid #1f77b4; margin-bottom:8px; }
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════
_DEFAULTS = {
    "lat": 36.4561,
    "lon": 10.7376,
    "shoreline_normal": None,
    "location_name":    "",
    "is_inland":        False,
    "geo_result":       None,      # FIX #1 — guard NameError
}
for _k, _v in _DEFAULTS.items():
    if _k not in st.session_state:
        st.session_state[_k] = _v

st.title("🌊 مستشار الصيد الفيزيائي | تونس الكاملة")
st.markdown("**اختر أي موقع على الخريطة ← جميع العوامل تُحسب لإحداثياته الدقيقة — v7.2**")

# ══════════════════════════════════════════════════════════════
# MATH HELPERS
# ══════════════════════════════════════════════════════════════
def destination_point(lat1, lon1, bearing_deg, distance_km):
    R  = 6371.0
    b  = math.radians(bearing_deg)
    φ1 = math.radians(lat1)
    λ1 = math.radians(lon1)
    φ2 = math.asin(
        math.sin(φ1)*math.cos(distance_km/R) +
        math.cos(φ1)*math.sin(distance_km/R)*math.cos(b)
    )
    λ2 = λ1 + math.atan2(
        math.sin(b)*math.sin(distance_km/R)*math.cos(φ1),
        math.cos(distance_km/R) - math.sin(φ1)*math.sin(φ2)
    )
    return math.degrees(φ2), math.degrees(λ2)


def circular_mean(angles_deg):
    if not angles_deg:
        return 0.0
    s = sum(math.sin(math.radians(a)) for a in angles_deg) / len(angles_deg)
    c = sum(math.cos(math.radians(a)) for a in angles_deg) / len(angles_deg)
    return math.degrees(math.atan2(s, c)) % 360


def angle_diff_180(a, b):
    """فرق زاوي دائري في [0°, 180°]"""
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d


def safe_avg(lst):
    return sum(lst) / len(lst) if lst else 0.0


def moon_phase_factor(target_date):
    """
    عامل نشاط القمر [0.0, 1.0]
    1.0 = بدر أو محاق (أعلى نشاط للسمك)
    دورة القمر = 29.53 يوم
    """
    known_new_moon = date(2024, 1, 11)
    delta          = (target_date - known_new_moon).days % 29.53
    phase_rad      = 2 * math.pi * delta / 29.53
    return round(0.5 + 0.5 * abs(math.cos(phase_rad)), 3)

# ══════════════════════════════════════════════════════════════
# SHORELINE GEOMETRY
# FIX #8 — circular_std بالصيغة الصحيحة
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def compute_shoreline_geometry(lat, lon):
    """
    يحسب لكل نقطة:
      shoreline_normal : اتجاه البحر (°)
      bay_factor       : 0=مفتوح  1=خليج مغلق
      coast_exposure   : نسبة محيط البحر
      coast_type       : وصف الساحل
    """
    radius_km = 3.0
    points    = []
    for bearing in range(0, 360, 10):
        lat2, lon2 = destination_point(lat, lon, bearing, radius_km)
        points.append({"lat": round(lat2, 5), "lon": round(lon2, 5),
                        "bearing": bearing})

    lats_str = ",".join(str(p["lat"]) for p in points)
    lons_str = ",".join(str(p["lon"]) for p in points)

    try:
        resp = requests.get(
            "https://api.open-meteo.com/v1/elevation",
            params={"latitude": lats_str, "longitude": lons_str},
            timeout=12
        )
        resp.raise_for_status()
        elevations = resp.json().get("elevation", [])
    except Exception as e:
        return None, f"خطأ API الارتفاع: {e}"

    if len(elevations) != len(points):
        return None, "بيانات ارتفاع غير مكتملة"

    sea_bearings  = []
    land_bearings = []
    for p, elev in zip(points, elevations):
        if elev is None:
            continue
        if elev <= 0.5:
            sea_bearings.append(p["bearing"])
        else:
            land_bearings.append(p["bearing"])

    if not sea_bearings:
        return None, "inland"

    # Shoreline normal
    shoreline_normal = circular_mean(sea_bearings)

    # coast_exposure
    coast_exposure = round(len(sea_bearings) / len(points), 3)

    # FIX #8 — Circular std الصحيح (Mardia & Jupp)
    if len(sea_bearings) >= 2:
        avg_sin_b = sum(math.sin(math.radians(b)) for b in sea_bearings) / len(sea_bearings)
        avg_cos_b = sum(math.cos(math.radians(b)) for b in sea_bearings) / len(sea_bearings)
        R_bar     = math.sqrt(avg_sin_b**2 + avg_cos_b**2)
        R_bar     = min(R_bar, 0.9999)   # تجنب log(0)
        circ_std  = math.degrees(math.sqrt(-2.0 * math.log(R_bar)))
        bay_factor = round(max(0.0, 1.0 - circ_std / 90.0), 3)
    else:
        bay_factor = 0.5

    # FIX #12 — coast_type مع كشف البحيرات والمراسي
    if coast_exposure < 0.05:
        coast_type = "🔴 بحيرة / سبخة — ليست بحر مفتوح"
    elif coast_exposure > 0.65:
        coast_type = "رأس بحري / ساحل مفتوح"
    elif coast_exposure > 0.35:
        coast_type = "خليج شبه مغلق" if bay_factor > 0.55 else "ساحل عادي"
    else:
        coast_type = "خليج مغلق / مرسى"

    return {
        "shoreline_normal":    round(shoreline_normal, 1),
        "coast_exposure":      coast_exposure,
        "bay_factor":          bay_factor,
        "coast_type":          coast_type,
        "sea_bearings_count":  len(sea_bearings),
        "land_bearings_count": len(land_bearings),
    }, None


# ══════════════════════════════════════════════════════════════
# WIND CLASSIFICATION
# FIX #11 — ريح البر الخفيفة تحصل على bonus
# ══════════════════════════════════════════════════════════════
def classify_wind(wdir_going_to, shoreline_normal, ws_kmh):
    """
    يُصنّف الريح بالنسبة لاتجاه الساحل الفعلي للنقطة المختارة.
    كل نقطة في تونس لها shoreline_normal مختلف.
    """
    if shoreline_normal is None:
        return "غير محدد", 90.0, 0.0

    diff = angle_diff_180(wdir_going_to, shoreline_normal)

    if diff <= 45:
        label = "ريح وش 🟢"
        # وش مثالية: 8-25 كم/س
        if 8.0 <= ws_kmh <= 25.0:
            bonus = +1.5
        elif ws_kmh < 8.0:
            bonus = +0.5
        else:
            bonus = -0.5   # وش قوية جداً

    elif diff >= 135:
        label = "ريح بر 🔵"
        # FIX #11: بر خفيفة = أفضل للصيد العميق
        if ws_kmh <= 15.0:
            bonus = +1.0
        elif ws_kmh <= 25.0:
            bonus = +0.3
        else:
            bonus = -1.5   # بر قوية = الطعم لا يصل

    elif diff <= 90:
        label = "ريح جانبي-وش 🟡"
        bonus = -0.5 if ws_kmh <= 20.0 else -1.5

    else:
        label = "ريح جانبي-بر 🟠"
        bonus = -0.8 if ws_kmh <= 20.0 else -2.5

    return label, round(diff, 1), round(bonus, 2)


# ══════════════════════════════════════════════════════════════
# REVERSE GEOCODING
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def get_location_name(lat, lon):
    try:
        resp = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={"lat": lat, "lon": lon, "format": "json",
                    "accept-language": "ar", "zoom": 14},
            headers={"User-Agent": "TunisiaSurfcasting/7.2"},
            timeout=8
        )
        addr = resp.json().get("address", {})
        return (addr.get("hamlet") or addr.get("village") or
                addr.get("suburb") or addr.get("town")   or
                addr.get("city")   or addr.get("county") or
                addr.get("state")  or "ساحل تونسي")
    except Exception:
        return "منطقة ساحلية"


# ══════════════════════════════════════════════════════════════
# MAP
# ══════════════════════════════════════════════════════════════
col_map, col_info = st.columns([2, 1])

# FIX #1 — تهيئة كل المتغيرات قبل أي استخدام
geo_result       = st.session_state.geo_result        # لن يكون NameError أبداً
shoreline_normal = st.session_state.shoreline_normal
is_inland        = st.session_state.is_inland
location_name    = st.session_state.location_name

with col_map:
    st.markdown("##### 🗺️ اختر موقع الصيد — انقر على الخريطة")
    m = folium.Map(
        location=[st.session_state.lat, st.session_state.lon],
        zoom_start=10,
        tiles="CartoDB dark_matter"
    )

    # رسم اتجاه البحر
    if shoreline_normal is not None:
        lat_e, lon_e = destination_point(
            st.session_state.lat, st.session_state.lon,
            shoreline_normal, 2.5
        )
        folium.PolyLine(
            [[st.session_state.lat, st.session_state.lon], [lat_e, lon_e]],
            color="cyan", weight=3,
            tooltip=f"اتجاه البحر: {shoreline_normal}°"
        ).add_to(m)

    folium.Marker(
        [st.session_state.lat, st.session_state.lon],
        tooltip=f"🎣 {location_name or 'الموقع'}",
        icon=folium.Icon(color="red", icon="anchor", prefix="fa")
    ).add_to(m)

    map_data = st_folium(m, width=None, height=460,
                         returned_objects=["last_clicked"])

    if map_data and map_data.get("last_clicked"):
        new_lat = round(map_data["last_clicked"]["lat"], 5)
        new_lon = round(map_data["last_clicked"]["lng"], 5)
        if (new_lat != st.session_state.lat or
                new_lon != st.session_state.lon):
            st.session_state.lat              = new_lat
            st.session_state.lon              = new_lon
            st.session_state.shoreline_normal = None
            st.session_state.location_name    = ""
            st.session_state.geo_result       = None   # FIX #1
            st.session_state.is_inland        = False
            st.rerun()

with col_info:
    st.markdown("##### 📍 بيانات الموقع")
    st.metric("Latitude",  f"{st.session_state.lat}°")
    st.metric("Longitude", f"{st.session_state.lon}°")
    st.divider()

    with st.spinner("تحليل هندسة الساحل..."):
        computed_geo, geo_error = compute_shoreline_geometry(
            st.session_state.lat, st.session_state.lon
        )

    if geo_error == "inland":
        st.error("📍 موقع بري — اختر نقطة على الشاطئ أو البحر")
        st.session_state.is_inland        = True
        st.session_state.shoreline_normal = None
        st.session_state.geo_result       = None
        geo_result       = None
        shoreline_normal = None
        is_inland        = True

    elif geo_error:
        st.warning(f"⚠️ {geo_error}")
        st.session_state.shoreline_normal = None
        st.session_state.geo_result       = None
        geo_result       = None
        shoreline_normal = None

    else:
        # FIX #12: تحقق من بحيرة/سبخة
        if "بحيرة" in computed_geo["coast_type"]:
            st.warning(f"⚠️ {computed_geo['coast_type']}")
            st.caption("هذا الموقع ليس ساحلاً بحرياً مفتوحاً")

        st.session_state.is_inland        = False
        st.session_state.shoreline_normal = computed_geo["shoreline_normal"]
        st.session_state.geo_result       = computed_geo
        geo_result       = computed_geo
        shoreline_normal = computed_geo["shoreline_normal"]
        is_inland        = False

        st.markdown(f"""
        <div class='spot-card'>
        🧭 <b>اتجاه البحر:</b> {computed_geo['shoreline_normal']}°<br>
        🏖️ <b>نوع الساحل:</b> {computed_geo['coast_type']}<br>
        📊 <b>انكشاف البحر:</b> {int(computed_geo['coast_exposure']*100)}%<br>
        🌊 <b>درجة إغلاق الخليج:</b> {int(computed_geo['bay_factor']*100)}%
        </div>
        """, unsafe_allow_html=True)

    # اسم الموقع
    if not st.session_state.location_name:
        st.session_state.location_name = get_location_name(
            st.session_state.lat, st.session_state.lon
        )
    location_name = st.session_state.location_name
    st.info(f"📍 **{location_name}**")

    # FIX #2 — عرض عامل قمر الغد (ليس اليوم)
    tomorrow_display = date.today() + timedelta(days=1)
    moon_f_display   = moon_phase_factor(tomorrow_display)
    moon_pct         = int(moon_f_display * 100)
    if moon_pct >= 75:
        moon_lbl = f"🌕 نشاط عالٍ ({moon_pct}%)"
    elif moon_pct >= 40:
        moon_lbl = f"🌓 نشاط متوسط ({moon_pct}%)"
    else:
        moon_lbl = f"🌑 نشاط ضعيف ({moon_pct}%)"
    st.metric("🌙 عامل القمر غداً", moon_lbl)

    if os.environ.get("GEMINI_API_KEY"):
        st.success("✅ Gemini جاهز")
    else:
        st.error("❌ GEMINI_API_KEY مفقود")

# توقف إذا برّي أو بحيرة
if is_inland:
    st.error("⛔ اختر نقطة على الشاطئ أو البحر للمتابعة.")
    st.stop()

if geo_result and "بحيرة" in geo_result.get("coast_type", ""):
    st.error("⛔ هذا الموقع بحيرة أو سبخة — اختر ساحلاً بحرياً.")
    st.stop()

st.divider()

# ══════════════════════════════════════════════════════════════
# DATA FETCHING
# FIX #3 — حذف ocean_current (غير متوفر)
# FIX #7 — SST في نفس طلب Marine (مع past_days)
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_all_data(lat, lon):
    """
    جلب كل البيانات لإحداثيات الموقع الدقيق.
    SST مدمج في طلب Marine الرئيسي لضمان تطابق الـ time index.
    ocean_current محذوف (غير متوفر في المجاني).
    """
    # ── Marine + SST في طلب واحد ──
    marine_params = {
        "latitude":  lat, "longitude": lon,
        "hourly": (
            "wave_height,wave_direction,wave_period,"
            "wind_wave_height,wind_wave_direction,wind_wave_period,"
            "swell_wave_height,swell_wave_direction,swell_wave_period,"
            "sea_surface_temperature"
        ),
        "past_days": 2, "forecast_days": 3, "timezone": "auto"
    }

    # ── Weather ──
    weather_params = {
        "latitude":  lat, "longitude": lon,
        "hourly": (
            "wind_speed_10m,wind_direction_10m,"
            "wind_gusts_10m,precipitation,visibility"
        ),
        "past_days": 2, "forecast_days": 3, "timezone": "auto"
    }

    marine_data  = None
    weather_data = None

    try:
        r = requests.get(
            "https://marine-api.open-meteo.com/v1/marine",
            params=marine_params, timeout=14
        )
        r.raise_for_status()
        marine_data = r.json()
        if "error" in marine_data:
            raise ValueError(marine_data.get("reason", ""))
    except Exception:
        marine_data = None

    try:
        r = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params=weather_params, timeout=12
        )
        r.raise_for_status()
        weather_data = r.json()
    except Exception as e:
        return None, None, f"فشل جلب الطقس: {e}"

    return marine_data, weather_data, None


# ══════════════════════════════════════════════════════════════
# DATA HELPERS
# ══════════════════════════════════════════════════════════════
def build_lookup(data):
    if not data:
        return {}
    return {t: i for i, t in enumerate(data['hourly'].get('time', []))}


def gv(data, lookup, key, ts, default=0.0):
    """Get Value — آمن بالكامل مع fallback"""
    if not data or not lookup:
        return default
    idx = lookup.get(ts)
    if idx is None:
        return default
    arr = data['hourly'].get(key, [])
    if idx < len(arr) and arr[idx] is not None:
        try:
            return float(arr[idx])
        except (TypeError, ValueError):
            return default
    return default


# ══════════════════════════════════════════════════════════════
# PHYSICS ENGINE v7.2 — جميع الأخطاء مُصلَحة
# FIX #6 — معاملات hashable بدل dict
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def compute_scores(
    marine_data,
    weather_data,
    shoreline_normal,
    # FIX #6: tuple بدل dict لضمان cache صحيح
    bay_factor,
    coast_exposure,
    coast_type
):
    time_array = weather_data['hourly']['time']
    wind_spd   = weather_data['hourly'].get('wind_speed_10m',    [])
    wind_dir   = weather_data['hourly'].get('wind_direction_10m', [])
    wind_gust  = weather_data['hourly'].get('wind_gusts_10m',    [])
    precip     = weather_data['hourly'].get('precipitation',     [])
    # FIX #13 — visibility قد يكون غائباً
    visibility = weather_data['hourly'].get('visibility',        [])

    time_dt = []
    for t in time_array:
        try:    time_dt.append(datetime.fromisoformat(t))
        except: time_dt.append(None)

    marine_lk = build_lookup(marine_data)

    def gm(key, ts, d=0.0):
        return gv(marine_data, marine_lk, key, ts, d)

    # ── tomorrow ──
    valid = [(i, t) for i, t in enumerate(time_dt) if t]
    if not valid:
        return None, None, "فشل تحليل الزمن"

    first_date    = valid[0][1].date()
    tomorrow_date = first_date + timedelta(days=1)
    tom_idx       = [i for i, t in valid if t.date() == tomorrow_date]
    if not tom_idx:
        return None, None, "لا بيانات لليوم القادم"

    start_idx = tom_idx[0]
    end_idx   = tom_idx[-1] + 1

    # ── Historical 48h ──
    p_wwh, p_wwp, p_swh, p_swp = [], [], [], []
    for i in range(max(0, start_idx - 48), start_idx):
        ts = time_array[i]
        v  = gm('wind_wave_height',  ts)
        if v > 0: p_wwh.append(v)
        v  = gm('wind_wave_period',  ts)
        if v > 0: p_wwp.append(v)
        v  = gm('swell_wave_height', ts)
        if v > 0: p_swh.append(v)
        v  = gm('swell_wave_period', ts)
        if v > 0: p_swp.append(v)

    avg_wwh = safe_avg(p_wwh)
    avg_wwp = safe_avg(p_wwp)
    avg_swh = safe_avg(p_swh)
    avg_swp = safe_avg(p_swp)

    # FIX #2 — عامل قمر الغد الصحيح
    moon_f = moon_phase_factor(tomorrow_date)

    # تردد موج رياح قصير < 6s = بحر مدرر
    is_dirty = (avg_wwh > 1.2) and (avg_wwp < 6.0)

    hourly = []

    for i in range(start_idx, end_idx):
        score = 10.0
        ts    = time_array[i]
        t_obj = time_dt[i]

        # ── Marine vars (منفصل بالوقت — FIX #1) ──
        wh  = gm('wave_height',           ts)
        wd  = gm('wave_direction',         ts)
        wp  = gm('wave_period',            ts)

        wwh = gm('wind_wave_height',       ts)
        wwd = gm('wind_wave_direction',    ts)
        wwp = gm('wind_wave_period',       ts)

        swh = gm('swell_wave_height',      ts)
        swd = gm('swell_wave_direction',   ts)
        swp = gm('swell_wave_period',      ts)

        # FIX #7 — SST من نفس marine_lk (past_days متطابق)
        sst = gm('sea_surface_temperature', ts, 18.0)

        # ── Weather ──
        ws   = (float(wind_spd[i])
                if i < len(wind_spd)   and wind_spd[i]   is not None else 0.0)
        wd_r = (float(wind_dir[i])
                if i < len(wind_dir)   and wind_dir[i]   is not None else 0.0)
        gust = (float(wind_gust[i])
                if i < len(wind_gust)  and wind_gust[i]  is not None else 0.0)
        rain = (float(precip[i])
                if i < len(precip)     and precip[i]     is not None else 0.0)
        # FIX #10 + #13 — visibility: default صحيح + قائمة فارغة آمنة
        vis  = (float(visibility[i])
                if i < len(visibility) and visibility[i] is not None
                else 24140.0)

        # ── FIX #5 — ws_effective يأخذ الهبات بعين الاعتبار ──
        ws_effective = max(ws, gust * 0.7)

        # Meteorological → Oceanographic
        wdir_going = (wd_r + 180) % 360

        # ── Wind vs Shoreline (خاص بهذا الموقع) ──
        wind_label, wind_shore_a, wind_bonus = classify_wind(
            wdir_going, shoreline_normal, ws_effective
        )

        # ── wave_impact لكل مكون ──
        sn = shoreline_normal if shoreline_normal is not None else 0.0
        wave_impact = angle_diff_180(wd,  sn)
        ww_impact   = angle_diff_180(wwd, sn)
        sw_impact   = angle_diff_180(swd, sn)

        # ── FIX #4 — wh_eff من المكونَين المنفصلَين (لا تناقض) ──
        wwh_eff = wwh * (1.0 - bay_factor * 0.50)   # موج ريح يتأثر أكثر بالخليج
        swh_eff = swh * (1.0 - bay_factor * 0.30)   # Swell يتأثر أقل
        wh_eff  = wwh_eff + swh_eff                 # FIX: مجموع المكونَين (لا wh المُدمج)

        # ── Breaking height ──
        hb_wind  = wwh_eff * 1.4
        hb_swell = swh_eff * 1.2

        # ── Longshore current (بدون ocean_current الوهمي) ──
        def v_ls(hb, impact_deg):
            ir = math.radians(impact_deg)
            if hb > 0.05 and impact_deg > 10:
                return 1.17 * math.sqrt(9.81 * hb) * math.sin(ir) * math.cos(ir)
            return 0.0

        v_ls_total = v_ls(hb_wind, ww_impact) + v_ls(hb_swell, sw_impact)

        # FIX #3 — تقدير Ekman بدل ocean_current_velocity الوهمي
        cur_ekman   = ws_effective * 0.03 * 0.5   # تأثير جانبي مُقدَّر
        v_ls_total += cur_ekman
        v_ls_kmh    = v_ls_total * 3.6

        # ── Drag force ──
        f_drag = 0.5 * 1025 * 1.5 * 0.0025 * (v_ls_total ** 2)

        if f_drag > 2.5:
            lead_rec, lead_g = "شواكيش سبايك", 140
        elif f_drag > 1.0:
            lead_rec, lead_g = "هرمي",          120
        else:
            lead_rec, lead_g = "زيتوني",        100

        # ── Rip current ──
        if wh_eff > 1.2 and wp > 8.0 and 20 <= wave_impact <= 60:
            rip = "عالي جداً ⚠️"
        elif wh_eff > 1.0 and wp > 6.0 and wave_impact < 30:
            rip = "متوسط"
        else:
            rip = "منخفض"

        # ── Debris — Swell حقيقي فقط ينظف ──
        is_cleansing = (swp >= 8.0 and sw_impact < 45 and swh_eff <= 1.2)
        if is_cleansing and is_dirty:
            debris = "Swell ينظف البحر 🟢"
        elif is_dirty and wwp < 6.0:
            debris = "مدرر — موج رياح قصير 🔴"
        else:
            debris = "نظيف 🟢"

        # ══════════════════════════════════════
        # SCORING
        # ══════════════════════════════════════

        # بحر ميت
        if wh_eff < 0.3:
            score -= 3.0

        # مدرر
        if "مدرر" in debris:
            score -= 4.5

        # تيار جانبي
        if v_ls_kmh > 1.5:
            score -= 4.0
        elif v_ls_kmh > 0.8:
            score -= 2.0

        # FIX #5 — خصم ws_effective (يشمل الهبات)
        if ws_effective > 65:
            score -= 7.0
        elif ws_effective > 55:
            score -= 5.0
        elif ws_effective > 42:
            score -= 3.0
        elif ws_effective > 32:
            score -= 1.5
        elif ws_effective > 26:
            score -= 0.5

        # مطر
        if rain > 5.0:
            score -= 2.0
        elif rain > 1.0:
            score -= 0.5

        # رؤية — FIX #10 عتبات صحيحة
        if vis < 1000:
            score -= 3.0
        elif vis < 3000:
            score -= 1.0

        # نوع الريح (خاص بالموقع)
        score += wind_bonus

        # Écume: ريح وش + موج معتدل فعلي
        if ("وش" in wind_label and
                0.4 <= wh_eff <= 1.4 and
                wave_impact < 50 and
                ws >= 8.0):
            score += 1.5

        # Swell نقي
        if swh_eff > 0.3 and wwh_eff < 0.3 and swp > 9.0:
            score += 1.5

        # تنظيف Swell
        if is_cleansing and is_dirty:
            score += 2.0

        # FIX #9 — عامل القمر: bonus فقط (لا خصم)، تأثير مُقلَّل
        moon_bonus = max(0.0, (moon_f - 0.55)) * 1.5   # [0, +0.68]
        score     += moon_bonus

        # تأثير انكشاف الموقع
        if coast_exposure > 0.7 and wh_eff > 1.5:
            score -= 1.5
        if bay_factor > 0.8 and wh_eff < 0.5:
            score -= 1.0

        # حرارة الماء
        if sst < 15.0:
            score -= 2.0
        elif sst < 17.0:
            score -= 1.0
        elif 19.0 <= sst <= 24.0:
            score += 0.5

        score = max(0.0, min(10.0, score))

        # Écume flag
        ecume_flag = (
            "نعم ✅" if ("وش" in wind_label and
                         0.4 <= wh_eff <= 1.4 and
                         wave_impact < 50 and ws >= 8.0)
            else "لا"
        )

        hourly.append({
            "time":          ts,
            "hour":          t_obj.hour if t_obj else -1,
            "score":         round(score, 1),
            # Waves (FIX #4: مكونات منفصلة)
            "wh_eff":        round(wh_eff, 2),
            "wp":            round(wp, 1),
            "ww_h":          round(wwh_eff, 2),
            "ww_p":          round(wwp, 1),
            "ww_impact":     round(ww_impact, 1),
            "sw_h":          round(swh_eff, 2),
            "sw_p":          round(swp, 1),
            "sw_impact":     round(sw_impact, 1),
            # Wind (FIX #5: ws_effective)
            "wind_kmh":      round(ws, 1),
            "gust_kmh":      round(gust, 1),
            "ws_eff":        round(ws_effective, 1),
            "wind_dir":      round(wd_r, 0),
            # Spot-specific
            "wind_type":     wind_label,
            "wind_shore_a":  wind_shore_a,
            # Physics
            "longshore_kmh": round(v_ls_kmh, 2),
            "drag_n":        round(f_drag, 4),
            "lead_rec":      lead_rec,
            "lead_g":        lead_g,
            # Conditions
            "rip":           rip,
            "debris":        debris,
            "ecume":         ecume_flag,
            "sst_c":         round(sst, 1),
            "rain_mm":       round(rain, 1),
            "vis_km":        round(vis / 1000, 1),
        })

    historical_ctx = {
        "avg_wwh":     round(avg_wwh, 2),
        "avg_wwp":     round(avg_wwp, 1),
        "avg_swh":     round(avg_swh, 2),
        "avg_swp":     round(avg_swp, 1),
        "is_dirty":    is_dirty,
        "tomorrow":    tomorrow_date.isoformat(),
        "moon_f":      round(moon_f, 3),
        "bay_f":       round(bay_factor, 3),
        "exposure":    round(coast_exposure, 3),
        "coast_type":  coast_type,
        "sn":          shoreline_normal,
    }
    return hourly, historical_ctx, None


# ══════════════════════════════════════════════════════════════
# WEIGHTED SCORE
# ══════════════════════════════════════════════════════════════
def weighted_avg_score(hourly_data):
    """ساعات الصيد الفعلية تحمل وزن ×2.5"""
    prime   = set(range(17, 24)) | set(range(4, 9))
    tw = ts = 0.0
    for h in hourly_data:
        w   = 2.5 if h["hour"] in prime else 1.0
        ts += h["score"] * w
        tw += w
    return ts / tw if tw else 0.0


# ══════════════════════════════════════════════════════════════
# GEMINI REPORT
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=1800, show_spinner=False)
def generate_report(hourly_data, ctx, location_name,
                    shoreline_normal, w_avg):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None, "GEMINI_API_KEY مفقود"

    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            generation_config=genai.GenerationConfig(
                temperature=0.05, top_p=0.1, max_output_tokens=3200
            )
        )

        dirty_str = (
            "بحر مدرر (wind_wave_period < 6ث — موج ريح قصير)"
            if ctx["is_dirty"] else "بحر نظيف"
        )
        shore_str = f"{shoreline_normal}°" if shoreline_normal else "غير محسوب"
        moon_pct  = int(ctx["moon_f"] * 100)

        prompt = f"""
أنت خبير هيدروديناميكا ساحلية وصياد محترف تونسي.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📍 الموقع: {location_name}
🧭 اتجاه البحر لهذا الـ Spot: {shore_str}
🏖️ نوع الساحل: {ctx['coast_type']}
📊 انكشاف: {int(ctx['exposure']*100)}% | خليج: {int(ctx['bay_f']*100)}%
📅 غد: {ctx['tomorrow']}
🌙 عامل القمر: {ctx['moon_f']} ({moon_pct}%)
📜 48ساعة ماضية: {dirty_str}
   موج رياح: {ctx['avg_wwh']}م / {ctx['avg_wwp']}ث
   Swell    : {ctx['avg_swh']}م / {ctx['avg_swp']}ث
🎯 سكور مُرجَّح: {round(w_avg,2)}/10
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

بيانات ساعة بساعة:
{json.dumps(hourly_data, ensure_ascii=False)}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
حقول جوهرية:
• wind_type    : نوع الريح لهذا الـ spot تحديداً
• ws_eff       : سرعة الرياح الفعلية = max(wind_kmh, gust×0.7)
• wh_eff       : موج فعلي = wwh_eff + swh_eff (مُعدَّل بعامل الخليج)
• ww_h/ww_p    : موج رياح (مدرر إذا ww_p < 6ث)
• sw_h/sw_p    : Swell (ينظف إذا sw_p ≥ 8ث)
• longshore_kmh: تيار جانبي حقيقي
• sst_c        : حرارة الماء
• ecume        : هل تتشكل رغوة بيضاء
• moon_f       : عامل القمر (bonus بيولوجي فقط)
• vis_km       : الرؤية بالكيلومتر
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

قواعد صارمة:
① ابدأ مباشرة بدون مقدمات
② لا تخترع أرقاماً — البيانات فوق فقط
③ هذا التحليل خاص بإحداثيات هذا الـ spot فقط
④ استخدم: بحر مدرر، Swell، Écume، daurade، loup، marbré، bar، sar

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## 1. هوية الـ Spot
نوع الساحل، اتجاه البحر، تأثير الخليج على الموج الفعلي

## 2. تحليل الريح ساعة بساعة
متى وش؟ متى جانبي؟ أثر ws_eff على الإستراتيجية

## 3. Swell vs موج الرياح
هل البحر ينظف نفسه؟ متى؟ تطور debris

## 4. الفيزياء الميكانيكية
longshore، drag، نوع الرصاص، متى تتشكل Écume

## 5. النوافذ البيولوجية
حرارة الماء، عامل القمر ({moon_pct}%)، أي سمك؟ متى الذروة؟

──────────────────────────────

## 🎯 القرار النهائي ({round(w_avg,2)}/10)
≥ 5.0 → ✅ GO + تكتيك كامل
< 5.0 → 🔴 NO-GO + سبب رقمي

▸ الرصاص: {' '} | الوزن: {' '} | المسافة: {' '} | الطعم: {' '} | البدء: {' '} | الإنهاء: {' '}
"""
        resp = model.generate_content(prompt)
        return resp.text, None

    except Exception as e:
        return None, f"خطأ Gemini: {e}"


# ══════════════════════════════════════════════════════════════
# MAIN FLOW
# ══════════════════════════════════════════════════════════════
with st.spinner("جلب البيانات..."):
    marine_data, weather_data, fetch_err = fetch_all_data(
        st.session_state.lat, st.session_state.lon
    )

if fetch_err:
    st.error(fetch_err)
    st.stop()

if not marine_data:
    st.warning("⚠️ لا بيانات أمواج — الموقع بعيد عن البحر المفتوح.")

# FIX #6 — تمرير قيم scalar بدل dict
_bay      = geo_result.get("bay_factor",     0.0) if geo_result else 0.0
_exposure = geo_result.get("coast_exposure", 1.0) if geo_result else 1.0
_ctype    = geo_result.get("coast_type",     "ساحل عادي") if geo_result else "ساحل عادي"

with st.spinner("حساب المعادلات الفيزيائية..."):
    hourly_data, historical_ctx, score_err = compute_scores(
        marine_data, weather_data,
        shoreline_normal,
        _bay, _exposure, _ctype
    )

if score_err:
    st.error(score_err)
    st.stop()

# ══════════════════════════════════════════════════════════════
# DISPLAY
# ══════════════════════════════════════════════════════════════
w_avg   = weighted_avg_score(hourly_data)
s_avg   = sum(h["score"] for h in hourly_data) / len(hourly_data)
best_h  = max(hourly_data, key=lambda x: x["score"])
avg_ls  = sum(h["longshore_kmh"] for h in hourly_data) / len(hourly_data)
avg_sst = sum(h["sst_c"]         for h in hourly_data) / len(hourly_data)
ecume_c = sum(1 for h in hourly_data if "نعم" in h["ecume"])
total   = len(hourly_data) or 1
on_cnt  = sum(1 for h in hourly_data if "وش"   in h["wind_type"])
off_cnt = sum(1 for h in hourly_data if "بر"   in h["wind_type"])
cr_cnt  = sum(1 for h in hourly_data if "جانبي" in h["wind_type"])

# ── جدول ──
st.subheader("📊 المصفوفة الزمنية — غد")

df = pd.DataFrame(hourly_data)

def cs(v):
    if   v >= 7.5: return 'background:#0a3d0a;color:#00ff00'
    elif v >= 5.0: return 'background:#3d3d0a;color:#ffff00'
    elif v >= 4.0: return 'background:#3d2e0a;color:#ffa500'
    else:          return 'background:#3d0a0a;color:#ff4b4b'

def cw(v):
    s = str(v)
    if "وش"    in s: return 'color:#00ff00;font-weight:bold'
    if "بر"    in s: return 'color:#4da6ff;font-weight:bold'
    if "جانبي" in s: return 'color:#ffa500;font-weight:bold'
    return ''

show  = ["time","score","wind_type","wind_kmh","gust_kmh","ws_eff",
         "ww_h","ww_p","sw_h","sw_p","wh_eff",
         "longshore_kmh","drag_n","lead_g","lead_rec",
         "rip","debris","ecume","sst_c","rain_mm","vis_km"]
names = ["الوقت","السكر","نوع الريح","ريح","هبات","ريح فعلية",
         "موج ريح م","تردده ث","Swell م","تردده ث","موج فعلي م",
         "تيار جانبي","جر الرصاص","وزن رصاص","نوع رصاص",
         "تيار ساحب","أعشاب","Écume","حرارة°","مطر mm","رؤية كم"]

df_disp = df[show].copy()
df_disp.columns = names

styled = (
    df_disp.style
    .applymap(cs, subset=["السكر"])
    .applymap(cw, subset=["نوع الريح"])
)
st.dataframe(styled, use_container_width=True, hide_index=True)

# ── ملخصات ──
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("سكور مُرجَّح",  f"{w_avg:.1f}/10",
          delta=f"بسيط:{s_avg:.1f}", delta_color="off")
c2.metric("الساعة الذهبية", best_h["time"][-5:],
          delta=f"سكر:{best_h['score']}")
c3.metric("تيار جانبي",    f"{avg_ls:.2f} كم/س")
c4.metric("حرارة البحر",   f"{avg_sst:.1f}°C")
c5.metric("Écume متوقعة",  f"{ecume_c}/{total} ساعة")

st.markdown("---")
st.markdown("#### 🌬️ توزيع نوع الريح")
w1, w2, w3 = st.columns(3)
w1.metric("🟢 وش",    f"{on_cnt}/{total}",  delta=f"{on_cnt*100//total}%")
w2.metric("🔵 بر",    f"{off_cnt}/{total}", delta=f"{off_cnt*100//total}%")
w3.metric("🟠 جانبي", f"{cr_cnt}/{total}",  delta=f"{cr_cnt*100//total}%")

# ── القرار ──
st.subheader("⚡ القرار النهائي")

if w_avg >= 7.5:
    st.markdown(f"""<div class='go-box'>
    <h2 style='color:#00ff00;text-align:center'>✅ GO — ممتاز</h2>
    <p style='text-align:center;font-size:1.2em'>{w_avg:.1f}/10 — ظروف مثالية</p>
    </div>""", unsafe_allow_html=True)
elif w_avg >= 5.0:
    st.markdown(f"""<div class='go-box'>
    <h2 style='color:#ffff00;text-align:center'>🟡 GO — ممكن</h2>
    <p style='text-align:center;font-size:1.2em'>{w_avg:.1f}/10 — ظروف مقبولة</p>
    </div>""", unsafe_allow_html=True)
elif w_avg >= 4.0:
    st.markdown(f"""<div class='warn-box'>
    <h2 style='color:#ffa500;text-align:center'>🟠 للخبراء فقط</h2>
    <p style='text-align:center;font-size:1.2em'>{w_avg:.1f}/10 — ظروف صعبة</p>
    </div>""", unsafe_allow_html=True)
else:
    st.markdown(f"""<div class='nogo-box'>
    <h2 style='color:#ff4b4b;text-align:center'>🔴 NO-GO — إلغاء قطعي</h2>
    <p style='text-align:center;font-size:1.2em'>{w_avg:.1f}/10 — ظروف خطيرة</p>
    </div>""", unsafe_allow_html=True)

st.divider()

# ── Gemini ──
st.subheader("🧠 التقرير التكتيكي")
with st.spinner("إعداد التقرير..."):
    report, gen_err = generate_report(
        hourly_data, historical_ctx,
        location_name, shoreline_normal, w_avg
    )
if gen_err:
    st.error(gen_err)
else:
    st.markdown(report)

st.divider()

# ── Debug ──
with st.expander("🔧 Debug Panel", expanded=False):
    st.json({
        "coords":        [st.session_state.lat, st.session_state.lon],
        "shoreline_n":   shoreline_normal,
        "coast_type":    historical_ctx["coast_type"],
        "bay_factor":    historical_ctx["bay_f"],
        "exposure":      historical_ctx["exposure"],
        "is_dirty":      historical_ctx["is_dirty"],
        "moon_f":        historical_ctx["moon_f"],
        "avg_sst":       round(avg_sst, 1),
        "w_avg":         round(w_avg, 2),
        "s_avg":         round(s_avg, 2),
        "marine_ok":     marine_data is not None,
        "wind_dist":     {"onshore": on_cnt, "offshore": off_cnt, "cross": cr_cnt},
        "ecume_hours":   ecume_c,
        "fixes_applied": [
            "FIX1:geo_result_NameError",
            "FIX2:moon_tomorrow_date",
            "FIX3:ocean_current_removed_Ekman_added",
            "FIX4:wh_eff=wwh+swh",
            "FIX5:ws_effective=max(ws,gust*0.7)",
            "FIX6:hashable_cache_params",
            "FIX7:SST_in_main_marine_request",
            "FIX8:circular_std_Mardia",
            "FIX9:moon_bonus_only",
            "FIX10:visibility_default_24140",
            "FIX11:offshore_light_wind_bonus",
            "FIX12:lake_detection",
            "FIX13:visibility_empty_list_safe",
        ]
    })

st.caption(
    "© مستشار الصيد v7.2 | 13/13 أخطاء مُصلَحة | "
    "كل نقطة = تحليل مستقل | تونس الكاملة"
        )
