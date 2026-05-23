import os
import json
import math
import time
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
  body{direction:rtl}
  .block-container{padding-top:1rem}
  .stMetric{background:#0e1117;padding:10px;border-radius:8px;
             border-left:4px solid #1f77b4}
  .go-box  {background:#0a3d0a;padding:18px;border-radius:10px;
             border:2px solid #00ff00}
  .nogo-box{background:#3d0a0a;padding:18px;border-radius:10px;
             border:2px solid #ff0000}
  .warn-box{background:#3d2e0a;padding:18px;border-radius:10px;
             border:2px solid #ffa500}
  .spot-card{background:#0a1a2e;padding:14px;border-radius:8px;
              border:1px solid #1f77b4;margin-bottom:8px}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# SESSION STATE
# ══════════════════════════════════════════════════════════════
_DEF = {
    "lat": 36.4561, "lon": 10.7376,
    "shoreline_normal": None,
    "location_name":    "",
    "is_inland":        False,
    "geo_result":       None,
    "last_click_lat":   None,
    "last_click_lon":   None,
}
for k, v in _DEF.items():
    if k not in st.session_state:
        st.session_state[k] = v

st.title("🌊 مستشار الصيد الفيزيائي | تونس الكاملة")
st.markdown("**v7.5 — بدون تجميد + cache ذكي**")

# ══════════════════════════════════════════════════════════════
# HTTP — بدون sleep في المسار الرئيسي
# الحل الجذري: @st.cache_data يمنع إعادة الطلب
# ══════════════════════════════════════════════════════════════
def _get(url: str, params: dict, timeout: int = 20) -> dict:
    """
    طلب واحد فقط — بدون retry loop يُجمِّد التطبيق.
    @st.cache_data هو الحماية الحقيقية من 429.
    """
    resp = requests.get(
        url, params=params, timeout=timeout,
        headers={"User-Agent": "TunisiaSurfcasting/7.5"}
    )
    resp.raise_for_status()
    return resp.json()

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
    if not angles_deg: return 0.0
    s = sum(math.sin(math.radians(a)) for a in angles_deg) / len(angles_deg)
    c = sum(math.cos(math.radians(a)) for a in angles_deg) / len(angles_deg)
    return math.degrees(math.atan2(s, c)) % 360

def angle_diff_180(a, b):
    d = abs(a - b) % 360
    return d if d <= 180 else 360 - d

def safe_avg(lst): return sum(lst)/len(lst) if lst else 0.0

def moon_phase_factor(d: date) -> float:
    delta = (d - date(2024, 1, 11)).days % 29.53
    return round(0.5 + 0.5*abs(math.cos(2*math.pi*delta/29.53)), 3)

# ══════════════════════════════════════════════════════════════
# SHORELINE GEOMETRY
# ttl=86400 → طلب واحد يومياً لكل موقع
# نقطة 12 فقط (كل 30°) بدل 36 → أقل حجم URL
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def compute_shoreline_geometry(lat: float, lon: float):
    radius_km = 3.0
    points = []
    # 12 نقطة فقط (كل 30°) — كافية للدقة ومنخفضة الضغط
    for bearing in range(0, 360, 30):
        lat2, lon2 = destination_point(lat, lon, bearing, radius_km)
        points.append({"lat": round(lat2, 4),
                        "lon": round(lon2, 4),
                        "bearing": bearing})

    lats_str = ",".join(str(p["lat"]) for p in points)
    lons_str = ",".join(str(p["lon"]) for p in points)

    try:
        data = _get(
            "https://api.open-meteo.com/v1/elevation",
            {"latitude": lats_str, "longitude": lons_str}
        )
        elevations = data.get("elevation", [])
    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 429:
            return None, "rate_limit"
        return None, f"خطأ elevation: {e}"
    except Exception as e:
        return None, f"خطأ elevation: {e}"

    if len(elevations) != len(points):
        return None, "بيانات ارتفاع غير مكتملة"

    sea_b = [p["bearing"] for p, e in zip(points, elevations)
             if e is not None and e <= 0.5]

    if not sea_b:
        return None, "inland"

    sn             = circular_mean(sea_b)
    coast_exposure = round(len(sea_b)/len(points), 3)

    if len(sea_b) >= 2:
        avg_s = sum(math.sin(math.radians(b)) for b in sea_b)/len(sea_b)
        avg_c = sum(math.cos(math.radians(b)) for b in sea_b)/len(sea_b)
        R_bar = min(math.sqrt(avg_s**2+avg_c**2), 0.9999)
        bay_factor = round(max(0.0, 1.0 - math.degrees(
            math.sqrt(-2.0*math.log(R_bar)))/90.0), 3)
    else:
        bay_factor = 0.5

    if   coast_exposure < 0.05: coast_type = "🔴 بحيرة / سبخة"
    elif coast_exposure > 0.65: coast_type = "رأس بحري / ساحل مفتوح"
    elif coast_exposure > 0.35: coast_type = ("خليج شبه مغلق"
                                               if bay_factor > 0.55
                                               else "ساحل عادي")
    else:                        coast_type = "خليج مغلق / مرسى"

    return {
        "shoreline_normal": round(sn, 1),
        "coast_exposure":   coast_exposure,
        "bay_factor":       bay_factor,
        "coast_type":       coast_type,
    }, None

# ══════════════════════════════════════════════════════════════
# DATA FETCHING
# ttl=3600 → طلب واحد كل ساعة لكل موقع
# Marine و Weather في دالتَين مستقلَّتَين
# → إذا فشلت إحداهما لا تُلغي الأخرى
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def fetch_marine(lat: float, lon: float):
    try:
        data = _get(
            "https://marine-api.open-meteo.com/v1/marine",
            {
                "latitude": lat, "longitude": lon,
                "hourly": (
                    "wave_height,wave_direction,wave_period,"
                    "wind_wave_height,wind_wave_direction,wind_wave_period,"
                    "swell_wave_height,swell_wave_direction,swell_wave_period,"
                    "sea_surface_temperature"
                ),
                "past_days": 2, "forecast_days": 3, "timezone": "auto"
            }
        )
        if "error" in data:
            return None, data.get("reason", "Marine error")
        return data, None
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code == 429:
            return None, "rate_limit"
        return None, f"Marine HTTP {code}"
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_weather(lat: float, lon: float):
    try:
        data = _get(
            "https://api.open-meteo.com/v1/forecast",
            {
                "latitude": lat, "longitude": lon,
                "hourly": (
                    "wind_speed_10m,wind_direction_10m,"
                    "wind_gusts_10m,precipitation,visibility"
                ),
                "past_days": 2, "forecast_days": 3, "timezone": "auto"
            }
        )
        return data, None
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else 0
        if code == 429:
            return None, "rate_limit"
        return None, f"Weather HTTP {code}"
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=86400, show_spinner=False)
def fetch_location_name(lat: float, lon: float) -> str:
    try:
        data = _get(
            "https://nominatim.openstreetmap.org/reverse",
            {"lat": lat, "lon": lon, "format": "json",
             "accept-language": "ar", "zoom": 14},
            timeout=8
        )
        a = data.get("address", {})
        return (a.get("hamlet") or a.get("village") or a.get("suburb") or
                a.get("town")   or a.get("city")    or a.get("state") or
                "ساحل تونسي")
    except Exception:
        return "منطقة ساحلية"

# ══════════════════════════════════════════════════════════════
# WIND CLASSIFICATION
# ══════════════════════════════════════════════════════════════
def classify_wind(wdir_going, sn, ws):
    if sn is None: return "غير محدد", 90.0, 0.0
    diff = angle_diff_180(wdir_going, sn)
    if   diff <= 45:
        label = "ريح وش 🟢"
        bonus = +1.5 if 8<=ws<=25 else (+0.5 if ws<8 else -0.5)
    elif diff >= 135:
        label = "ريح بر 🔵"
        bonus = +1.0 if ws<=15 else (+0.3 if ws<=25 else -1.5)
    elif diff <= 90:
        label = "ريح جانبي-وش 🟡"
        bonus = -0.5 if ws<=20 else -1.5
    else:
        label = "ريح جانبي-بر 🟠"
        bonus = -0.8 if ws<=20 else -2.5
    return label, round(diff,1), round(bonus,2)

# ══════════════════════════════════════════════════════════════
# DATA HELPERS
# ══════════════════════════════════════════════════════════════
def build_lookup(data):
    if not data: return {}
    return {t: i for i, t in enumerate(data['hourly'].get('time', []))}

def gv(data, lk, key, ts, default=0.0):
    if not data or not lk: return default
    idx = lk.get(ts)
    if idx is None: return default
    arr = data['hourly'].get(key, [])
    if idx < len(arr) and arr[idx] is not None:
        try: return float(arr[idx])
        except: return default
    return default

# ══════════════════════════════════════════════════════════════
# PHYSICS ENGINE
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=3600, show_spinner=False)
def compute_scores(marine_data, weather_data, sn,
                   bay_factor, coast_exposure, coast_type):

    time_array = weather_data['hourly']['time']
    wind_spd   = weather_data['hourly'].get('wind_speed_10m',    [])
    wind_dir   = weather_data['hourly'].get('wind_direction_10m', [])
    wind_gust  = weather_data['hourly'].get('wind_gusts_10m',    [])
    precip     = weather_data['hourly'].get('precipitation',     [])
    visibility = weather_data['hourly'].get('visibility',        [])

    time_dt = []
    for t in time_array:
        try:    time_dt.append(datetime.fromisoformat(t))
        except: time_dt.append(None)

    lk = build_lookup(marine_data)
    def gm(key, ts, d=0.0): return gv(marine_data, lk, key, ts, d)

    valid = [(i,t) for i,t in enumerate(time_dt) if t]
    if not valid: return None, None, "فشل تحليل الزمن"

    tomorrow_date = valid[0][1].date() + timedelta(days=1)
    tom_idx = [i for i,t in valid if t.date() == tomorrow_date]
    if not tom_idx: return None, None, "لا بيانات لليوم القادم"

    s_idx, e_idx = tom_idx[0], tom_idx[-1]+1

    p_wwh,p_wwp,p_swh,p_swp = [],[],[],[]
    for i in range(max(0, s_idx-48), s_idx):
        ts = time_array[i]
        for lst,k in [(p_wwh,'wind_wave_height'),(p_wwp,'wind_wave_period'),
                       (p_swh,'swell_wave_height'),(p_swp,'swell_wave_period')]:
            v = gm(k, ts)
            if v > 0: lst.append(v)

    avg_wwh=safe_avg(p_wwh); avg_wwp=safe_avg(p_wwp)
    avg_swh=safe_avg(p_swh); avg_swp=safe_avg(p_swp)
    moon_f  = moon_phase_factor(tomorrow_date)
    is_dirty = (avg_wwh > 1.2) and (avg_wwp < 6.0)

    hourly = []
    for i in range(s_idx, e_idx):
        score = 10.0
        ts    = time_array[i]
        t_obj = time_dt[i]

        wd  = gm('wave_direction',ts);         wp  = gm('wave_period',ts)
        wwh = gm('wind_wave_height',ts);       wwd = gm('wind_wave_direction',ts)
        wwp = gm('wind_wave_period',ts);       swh = gm('swell_wave_height',ts)
        swd = gm('swell_wave_direction',ts);   swp = gm('swell_wave_period',ts)
        sst = gm('sea_surface_temperature',ts, 18.0)

        def _w(arr):
            return float(arr[i]) if i<len(arr) and arr[i] is not None else 0.0

        ws   = _w(wind_spd); wd_r = _w(wind_dir)
        gust = _w(wind_gust); rain = _w(precip)
        vis  = _w(visibility) if visibility else 24140.0
        if vis <= 0: vis = 24140.0

        ws_eff     = max(ws, gust*0.7)
        wdir_going = (wd_r+180) % 360
        wind_label, wind_shore_a, wind_bonus = classify_wind(wdir_going, sn, ws_eff)

        _sn = sn if sn is not None else 0.0
        wave_impact = angle_diff_180(wd,  _sn)
        ww_impact   = angle_diff_180(wwd, _sn)
        sw_impact   = angle_diff_180(swd, _sn)

        wwh_eff = wwh*(1.0 - bay_factor*0.50)
        swh_eff = swh*(1.0 - bay_factor*0.30)
        wh_eff  = wwh_eff + swh_eff

        def v_ls(hb, imp):
            ir = math.radians(imp)
            return (1.17*math.sqrt(9.81*hb)*math.sin(ir)*math.cos(ir)
                    if hb>0.05 and imp>10 else 0.0)

        v_t  = v_ls(wwh_eff*1.4, ww_impact) + v_ls(swh_eff*1.2, sw_impact)
        v_t += ws_eff*0.015
        v_kmh = v_t*3.6
        f_drag = 0.5*1025*1.5*0.0025*(v_t**2)

        lead_rec,lead_g = (("شواكيش سبايك",140) if f_drag>2.5 else
                           ("هرمي",120) if f_drag>1.0 else ("زيتوني",100))

        rip = ("عالي جداً ⚠️" if wh_eff>1.2 and wp>8 and 20<=wave_impact<=60 else
               "متوسط"        if wh_eff>1.0 and wp>6 and wave_impact<30       else
               "منخفض")

        is_clean = swp>=8.0 and sw_impact<45 and swh_eff<=1.2
        debris   = ("Swell ينظف 🟢"          if is_clean and is_dirty else
                    "مدرر — موج ريح قصير 🔴" if is_dirty and wwp<6.0  else
                    "نظيف 🟢")

        # SCORING
        if wh_eff<0.3:       score -= 3.0
        if "مدرر" in debris: score -= 4.5
        if v_kmh>1.5:        score -= 4.0
        elif v_kmh>0.8:      score -= 2.0

        if   ws_eff>65: score-=7.0
        elif ws_eff>55: score-=5.0
        elif ws_eff>42: score-=3.0
        elif ws_eff>32: score-=1.5
        elif ws_eff>26: score-=0.5

        if   rain>5.0:  score-=2.0
        elif rain>1.0:  score-=0.5
        if   vis<1000:  score-=3.0
        elif vis<3000:  score-=1.0

        score += wind_bonus
        if "وش" in wind_label and 0.4<=wh_eff<=1.4 and wave_impact<50 and ws>=8:
            score += 1.5
        if swh_eff>0.3 and wwh_eff<0.3 and swp>9.0: score += 1.5
        if is_clean and is_dirty:                    score += 2.0
        score += max(0.0, (moon_f-0.55)*1.5)
        if coast_exposure>0.7 and wh_eff>1.5: score -= 1.5
        if bay_factor>0.8 and wh_eff<0.5:     score -= 1.0
        if   sst<15.0:        score -= 2.0
        elif sst<17.0:        score -= 1.0
        elif 19<=sst<=24:     score += 0.5

        score   = max(0.0, min(10.0, score))
        ecume_f = ("نعم ✅" if "وش" in wind_label and 0.4<=wh_eff<=1.4
                   and wave_impact<50 and ws>=8 else "لا")

        hourly.append({
            "time":ts,"hour":t_obj.hour if t_obj else -1,
            "score":round(score,1),
            "wh_eff":round(wh_eff,2),"wp":round(wp,1),
            "ww_h":round(wwh_eff,2),"ww_p":round(wwp,1),"ww_impact":round(ww_impact,1),
            "sw_h":round(swh_eff,2),"sw_p":round(swp,1),"sw_impact":round(sw_impact,1),
            "wind_kmh":round(ws,1),"gust_kmh":round(gust,1),"ws_eff":round(ws_eff,1),
            "wind_dir":round(wd_r,0),"wind_type":wind_label,"wind_shore_a":wind_shore_a,
            "longshore_kmh":round(v_kmh,2),"drag_n":round(f_drag,4),
            "lead_rec":lead_rec,"lead_g":lead_g,
            "rip":rip,"debris":debris,"ecume":ecume_f,
            "sst_c":round(sst,1),"rain_mm":round(rain,1),"vis_km":round(vis/1000,1),
        })

    ctx = {
        "avg_wwh":round(avg_wwh,2),"avg_wwp":round(avg_wwp,1),
        "avg_swh":round(avg_swh,2),"avg_swp":round(avg_swp,1),
        "is_dirty":is_dirty,"tomorrow":tomorrow_date.isoformat(),
        "moon_f":round(moon_f,3),"bay_f":round(bay_factor,3),
        "exposure":round(coast_exposure,3),"coast_type":coast_type,"sn":sn,
    }
    return hourly, ctx, None

def weighted_avg_score(data):
    prime = set(range(17,24))|set(range(4,9))
    tw=ts=0.0
    for h in data:
        w=2.5 if h["hour"] in prime else 1.0
        ts+=h["score"]*w; tw+=w
    return ts/tw if tw else 0.0

# ══════════════════════════════════════════════════════════════
# GEMINI
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=1800, show_spinner=False)
def generate_report(hourly_data, ctx, location_name, sn, w_avg):
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key: return None, "GEMINI_API_KEY مفقود"
    try:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            'gemini-1.5-flash',
            generation_config=genai.GenerationConfig(
                temperature=0.05, top_p=0.1, max_output_tokens=3200)
        )
        prompt = f"""
أنت خبير هيدروديناميكا ساحلية وصياد محترف تونسي.
📍 {location_name} | 🧭 {sn}° | 🏖️ {ctx['coast_type']}
انكشاف:{int(ctx['exposure']*100)}% خليج:{int(ctx['bay_f']*100)}%
📅 {ctx['tomorrow']} | 🌙 {ctx['moon_f']} | {'مدرر' if ctx['is_dirty'] else 'نظيف'}
موج ريح:{ctx['avg_wwh']}م/{ctx['avg_wwp']}ث Swell:{ctx['avg_swh']}م/{ctx['avg_swp']}ث
🎯 سكور:{round(w_avg,2)}/10
{json.dumps(hourly_data, ensure_ascii=False)}
قواعد: ابدأ مباشرة، لا أرقام مخترعة، استخدم المصطلحات التونسية.
## 1. هوية الـ Spot
## 2. الريح ساعة بساعة
## 3. Swell vs موج الرياح
## 4. الفيزياء (رصاص، تيار، Écume)
## 5. النوافذ البيولوجية
──────────────────────────────
## 🎯 القرار ({round(w_avg,2)}/10)
≥5→GO+تكتيك | <5→NO-GO+سبب
▸ الرصاص: | الوزن: | المسافة: | الطعم: | البدء: | الإنهاء:
"""
        return model.generate_content(prompt).text, None
    except Exception as e:
        return None, f"خطأ Gemini: {e}"

# ══════════════════════════════════════════════════════════════
# MAP
# ══════════════════════════════════════════════════════════════
geo_result       = st.session_state.geo_result
shoreline_normal = st.session_state.shoreline_normal
is_inland        = st.session_state.is_inland
location_name    = st.session_state.location_name

col_map, col_info = st.columns([2, 1])

with col_map:
    st.markdown("##### 🗺️ انقر على الخريطة لاختيار الموقع")
    m = folium.Map(
        location=[st.session_state.lat, st.session_state.lon],
        zoom_start=10, tiles="CartoDB dark_matter"
    )
    if shoreline_normal is not None:
        lat_e, lon_e = destination_point(
            st.session_state.lat, st.session_state.lon, shoreline_normal, 2.5)
        folium.PolyLine(
            [[st.session_state.lat, st.session_state.lon],[lat_e,lon_e]],
            color="cyan", weight=3, tooltip=f"اتجاه البحر: {shoreline_normal}°"
        ).add_to(m)
    folium.Marker(
        [st.session_state.lat, st.session_state.lon],
        tooltip=f"🎣 {location_name or 'الموقع'}",
        icon=folium.Icon(color="red", icon="anchor", prefix="fa")
    ).add_to(m)

    map_data = st_folium(
        m, width=None, height=460,
        returned_objects=["last_clicked"],
        key="main_map"
    )

    if map_data and map_data.get("last_clicked"):
        clat = round(map_data["last_clicked"]["lat"], 5)
        clon = round(map_data["last_clicked"]["lng"], 5)
        new_click = (clat != st.session_state.last_click_lat or
                     clon != st.session_state.last_click_lon)
        new_loc   = (clat != st.session_state.lat or
                     clon != st.session_state.lon)
        if new_click and new_loc:
            st.session_state.last_click_lat   = clat
            st.session_state.last_click_lon   = clon
            st.session_state.lat              = clat
            st.session_state.lon              = clon
            st.session_state.shoreline_normal = None
            st.session_state.location_name    = ""
            st.session_state.geo_result       = None
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

    if geo_error == "rate_limit":
        st.warning("⏳ API مشغول مؤقتاً — انقر زر التحديث بعد دقيقة")
        st.button("🔄 تحديث", on_click=st.cache_data.clear)
        st.stop()

    elif geo_error == "inland":
        st.error("📍 موقع بري — اختر نقطة على الشاطئ")
        st.session_state.is_inland = True
        st.session_state.shoreline_normal = None
        st.session_state.geo_result = None
        geo_result = shoreline_normal = None
        is_inland  = True

    elif geo_error:
        st.warning(f"⚠️ {geo_error}")
        st.session_state.shoreline_normal = None
        st.session_state.geo_result = None
        geo_result = shoreline_normal = None

    else:
        if "بحيرة" in computed_geo["coast_type"]:
            st.warning(f"⚠️ {computed_geo['coast_type']}")
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
        🌊 <b>إغلاق الخليج:</b> {int(computed_geo['bay_factor']*100)}%
        </div>
        """, unsafe_allow_html=True)

    location_name = fetch_location_name(
        st.session_state.lat, st.session_state.lon
    )
    st.session_state.location_name = location_name
    st.info(f"📍 **{location_name}**")

    tomorrow_d = date.today() + timedelta(days=1)
    moon_f_d   = moon_phase_factor(tomorrow_d)
    moon_pct   = int(moon_f_d*100)
    st.metric("🌙 عامل القمر غداً",
              f"🌕 عالٍ ({moon_pct}%)" if moon_pct>=75 else
              f"🌓 متوسط ({moon_pct}%)" if moon_pct>=40 else
              f"🌑 ضعيف ({moon_pct}%)")

    if os.environ.get("GEMINI_API_KEY"):
        st.success("✅ Gemini جاهز")
    else:
        st.error("❌ GEMINI_API_KEY مفقود")

if is_inland:
    st.error("⛔ اختر نقطة على الشاطئ أو البحر.")
    st.stop()
if geo_result and "بحيرة" in geo_result.get("coast_type",""):
    st.error("⛔ بحيرة / سبخة — اختر ساحلاً بحرياً.")
    st.stop()

st.divider()

# ══════════════════════════════════════════════════════════════
# FETCH DATA — منفصل مع معالجة rate_limit بدون تجميد
# ══════════════════════════════════════════════════════════════
with st.spinner("جلب بيانات البحر..."):
    marine_data, marine_err = fetch_marine(
        st.session_state.lat, st.session_state.lon
    )

with st.spinner("جلب بيانات الطقس..."):
    weather_data, weather_err = fetch_weather(
        st.session_state.lat, st.session_state.lon
    )

# معالجة rate_limit بدون تجميد التطبيق
if marine_err == "rate_limit" or weather_err == "rate_limit":
    st.warning("⏳ **Open-Meteo: تجاوزت الحد المسموح مؤقتاً**")
    st.markdown("""
    **الحل:**
    - انتظر **60 ثانية** ثم انقر التحديث
    - أو افتح الموقع في متصفح آخر
    - الحد المجاني = **10,000 طلب/يوم لكل IP**
    """)
    if st.button("🔄 إعادة المحاولة الآن"):
        # مسح cache فقط للبيانات (ليس الـ geometry)
        fetch_marine.clear()
        fetch_weather.clear()
        st.rerun()
    st.stop()

if marine_err and not marine_data:
    st.warning(f"⚠️ Marine: {marine_err} — سيتم المتابعة بدون بيانات أمواج")

if weather_err or not weather_data:
    st.error(f"❌ فشل جلب الطقس: {weather_err}")
    st.stop()

_bay  = geo_result.get("bay_factor",     0.0) if geo_result else 0.0
_exp  = geo_result.get("coast_exposure", 1.0) if geo_result else 1.0
_ctyp = geo_result.get("coast_type","ساحل عادي") if geo_result else "ساحل عادي"

with st.spinner("حساب المعادلات الفيزيائية..."):
    hourly_data, ctx, score_err = compute_scores(
        marine_data, weather_data, shoreline_normal, _bay, _exp, _ctyp
    )

if score_err:
    st.error(score_err)
    st.stop()

# ══════════════════════════════════════════════════════════════
# DISPLAY
# ══════════════════════════════════════════════════════════════
w_avg   = weighted_avg_score(hourly_data)
s_avg   = sum(h["score"] for h in hourly_data)/len(hourly_data)
best_h  = max(hourly_data, key=lambda x: x["score"])
avg_ls  = sum(h["longshore_kmh"] for h in hourly_data)/len(hourly_data)
avg_sst = sum(h["sst_c"] for h in hourly_data)/len(hourly_data)
ecume_c = sum(1 for h in hourly_data if "نعم" in h["ecume"])
total   = len(hourly_data) or 1
on_cnt  = sum(1 for h in hourly_data if "وش"    in h["wind_type"])
off_cnt = sum(1 for h in hourly_data if "بر"    in h["wind_type"])
cr_cnt  = sum(1 for h in hourly_data if "جانبي" in h["wind_type"])

st.subheader("📊 المصفوفة الزمنية — غد")
df = pd.DataFrame(hourly_data)

def cs(v):
    if   v>=7.5: return 'background:#0a3d0a;color:#00ff00'
    elif v>=5.0: return 'background:#3d3d0a;color:#ffff00'
    elif v>=4.0: return 'background:#3d2e0a;color:#ffa500'
    else:        return 'background:#3d0a0a;color:#ff4b4b'

def cw(v):
    s=str(v)
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
styled = (df_disp.style
          .applymap(cs, subset=["السكر"])
          .applymap(cw, subset=["نوع الريح"]))
st.dataframe(styled, use_container_width=True, hide_index=True)

c1,c2,c3,c4,c5 = st.columns(5)
c1.metric("سكور مُرجَّح", f"{w_avg:.1f}/10",
          delta=f"بسيط:{s_avg:.1f}", delta_color="off")
c2.metric("الساعة الذهبية", best_h["time"][-5:],
          delta=f"سكر:{best_h['score']}")
c3.metric("تيار جانبي", f"{avg_ls:.2f} كم/س")
c4.metric("حرارة البحر", f"{avg_sst:.1f}°C")
c5.metric("Écume", f"{ecume_c}/{total} ساعة")

st.markdown("---")
st.markdown("#### 🌬️ توزيع نوع الريح")
w1,w2,w3 = st.columns(3)
w1.metric("🟢 وش",    f"{on_cnt}/{total}",  delta=f"{on_cnt*100//total}%")
w2.metric("🔵 بر",    f"{off_cnt}/{total}", delta=f"{off_cnt*100//total}%")
w3.metric("🟠 جانبي", f"{cr_cnt}/{total}",  delta=f"{cr_cnt*100//total}%")

st.subheader("⚡ القرار النهائي")
if   w_avg>=7.5:
    st.markdown(f"""<div class='go-box'>
    <h2 style='color:#00ff00;text-align:center'>✅ GO — ممتاز</h2>
    <p style='text-align:center;font-size:1.2em'>{w_avg:.1f}/10</p>
    </div>""", unsafe_allow_html=True)
elif w_avg>=5.0:
    st.markdown(f"""<div class='go-box'>
    <h2 style='color:#ffff00;text-align:center'>🟡 GO — ممكن</h2>
    <p style='text-align:center;font-size:1.2em'>{w_avg:.1f}/10</p>
    </div>""", unsafe_allow_html=True)
elif w_avg>=4.0:
    st.markdown(f"""<div class='warn-box'>
    <h2 style='color:#ffa500;text-align:center'>🟠 للخبراء فقط</h2>
    <p style='text-align:center;font-size:1.2em'>{w_avg:.1f}/10</p>
    </div>""", unsafe_allow_html=True)
else:
    st.markdown(f"""<div class='nogo-box'>
    <h2 style='color:#ff4b4b;text-align:center'>🔴 NO-GO</h2>
    <p style='text-align:center;font-size:1.2em'>{w_avg:.1f}/10</p>
    </div>""", unsafe_allow_html=True)

st.divider()

st.subheader("🧠 التقرير التكتيكي")
with st.spinner("إعداد التقرير..."):
    report, gen_err = generate_report(
        hourly_data, ctx, location_name, shoreline_normal, w_avg
    )
if gen_err: st.error(gen_err)
else:       st.markdown(report)

st.divider()

with st.expander("🔧 Debug", expanded=False):
    st.json({
        "coords":    [st.session_state.lat, st.session_state.lon],
        "marine_ok": marine_data is not None,
        "sn":        shoreline_normal,
        "coast":     ctx["coast_type"],
        "w_avg":     round(w_avg, 2),
        "wind":      {"on":on_cnt,"off":off_cnt,"cross":cr_cnt},
    })

st.caption("© مستشار الصيد v7.5 | بدون تجميد + @st.cache_data لكل API")
