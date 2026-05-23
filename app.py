# =============================================================================
# SURFCASTING FISHING ADVISOR — app.py  ★ FINAL CORRECTED VERSION ★
# North African / Tunisian Coastal Hydrodynamics Decision Engine
# All 12 audit bugs fixed + Nabeul governorate geo-coastal database
# Deployment: Render Free Tier — Python 3.11+
# =============================================================================

import os
import json
import math
import time
import requests
import pandas as pd
import folium
import streamlit as st
import google.generativeai as genai
from streamlit_folium import st_folium
from datetime import datetime, timezone, timedelta

# =============================================================================
# 0. PAGE CONFIGURATION — MUST be the absolute first Streamlit call
# =============================================================================
st.set_page_config(
    page_title="مستشار صيد الشاطئ 🎣",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# =============================================================================
# 1. GLOBAL SCORING CONSTANTS — Single source of truth, never duplicated
# =============================================================================
DEFAULT_LAT: float = 36.4500
DEFAULT_LON: float = 10.7800

# BUG FIX #9: Force UTC on both APIs to prevent timezone drift between arrays
TIMEZONE: str = "UTC"

MARINE_API_BASE: str  = "https://marine-api.open-meteo.com/v1/marine"
WEATHER_API_BASE: str = "https://api.open-meteo.com/v1/forecast"
PAST_DAYS:        int = 2
FORECAST_DAYS:    int = 3
HISTORY_HOURS:    int = 48          # past 48 h window for baseline analysis

# --- Scoring thresholds ---
DEAD_SEA_MAX_H:       float = 0.30  # m   — no biological movement below this
DEAD_SEA_PENALTY:     float = 3.00

WEED_MIN_H:           float = 1.20  # m   — seabed scraping threshold
WEED_MIN_T:           float = 8.00  # s
WEED_PENALTY:         float = 4.50

LATERAL_ANGLE_LOW:    float = 30.0  # °   — oblique coastal band start
LATERAL_ANGLE_HIGH:   float = 150.0 # °   — oblique coastal band end
LATERAL_STRONG_SPD:   float = 22.0  # km/h
LATERAL_STRONG_PEN:   float = 4.00
LATERAL_MOD_SPD:      float = 18.0
LATERAL_MOD_PEN:      float = 1.50

FOAM_MIN_H:           float = 0.50  # m
FOAM_MAX_H:           float = 1.20  # m
FOAM_MIN_SPD:         float = 12.0  # km/h
FOAM_BONUS:           float = 1.50

SIEVE_MIN_T:          float = 4.00  # s
SIEVE_MAX_T:          float = 7.00  # s
SIEVE_MIN_H:          float = 0.50  # m
SIEVE_BONUS:          float = 2.00

DIRTY_DECAY_HOURS:    float = 24.0  # hours over which dirty baseline fades
SCORE_MAX:            float = 10.0
SCORE_MIN:            float = 0.0
SCORE_BASELINE:       float = 10.0

GO_MIN_AVG:           float = 6.0   # BUG FIX #8: AND logic — avg must meet this
GO_MIN_HOURS:         int   = 8     # BUG FIX #8: AND minimum good hours (not 6)

# =============================================================================
# 2. COASTAL GEO-DATABASE — Tunisian Shoreline Normals
#    BUG FIX #3: wind assessed against SHORE normal, not wave direction
#
#    shoreline_normal = compass bearing (°) pointing SEAWARD (perpendicular to coast)
#    0° = seaward direction faces True North
#    90° = seaward direction faces True East
#
#    Nabeul Governorate zones are split at fine resolution because:
#      - الرتيبة  (Rteiba)      : eastern Gulf of Hammamet shore → faces E  → normal ≈ 90°
#                                  North wind = lateral, East wind = frontal وش
#      - سيدي محرصي (Sidi Mahrassi): transitional NE shore cap  → faces NE → normal ≈ 55°
#                                  NW wind = oblique وس
#      - كركوان  (Kerkouane)   : northern cap face, Cap Bon tip  → faces N  → normal ≈ 15°
#                                  SW/SE wind = lateral جانبي
# =============================================================================
COASTAL_ZONES: list[dict] = [

    # ── NABEUL GOVERNORATE — High-resolution sub-zones ──────────────────────
    {
        "name_ar":  "الرتيبة — خليج الحمامات الشرقي",
        "name_fr":  "Rteiba — Gulf of Hammamet East",
        "lat_min":  36.37, "lat_max": 36.52,
        "lon_min":  10.58, "lon_max": 10.78,
        "normal":   90.0,   # faces due East
        "depth_profile": "رملي ضحل — sandy shallow",
        "target_species": "تاكوست، سباط، دنيس صغير",
        "wind_notes": "ريح الشرق = وش مثالي | ريح الشمال = جانبي | ريح الغرب = ظهري",
    },
    {
        "name_ar":  "سيدي محرصي — الرأس الانتقالي",
        "name_fr":  "Sidi Mahrassi — Transitional Cape",
        "lat_min":  36.52, "lat_max": 36.72,
        "lon_min":  10.68, "lon_max": 10.92,
        "normal":   55.0,   # faces NE
        "depth_profile": "صخري-رملي مختلط",
        "target_species": "مورين، سباط، شرش",
        "wind_notes": "ريح الشمال الشرقي = وش | ريح الشمال الغربي = وس مائل | ريح الجنوب = ظهري",
    },
    {
        "name_ar":  "كركوان — رأس بون الشمالي",
        "name_fr":  "Kerkouane — Cap Bon North",
        "lat_min":  36.72, "lat_max": 37.10,
        "lon_min":  10.92, "lon_max": 11.18,
        "normal":   15.0,   # faces NNE (northern tip of Cap Bon)
        "depth_profile": "صخري عميق — rocky deep",
        "target_species": "مورين، لُقُّوس، سرغ، روبيان خشن",
        "wind_notes": "ريح الشمال = وش | ريح الشرق/الغرب = جانبي | ريح الجنوب = ظهري مساعد",
    },
    {
        "name_ar":  "نابل — المدينة",
        "name_fr":  "Nabeul — City Front",
        "lat_min":  36.44, "lat_max": 36.50,
        "lon_min":  10.72, "lon_max": 10.80,
        "normal":   82.0,   # slight NE tilt
        "depth_profile": "رملي متوسط",
        "target_species": "تاكوست، سباط",
        "wind_notes": "ريح الشرق-شمال الشرقي = وش | ريح الشمال = وس مائل",
    },
    {
        "name_ar":  "قربة — خليج الحمامات الجنوبي",
        "name_fr":  "Korba — Gulf of Hammamet South",
        "lat_min":  36.55, "lat_max": 36.72,
        "lon_min":  10.78, "lon_max": 10.95,
        "normal":   70.0,   # ENE
        "depth_profile": "رملي عميق تدريجياً",
        "target_species": "دنيس، تاكوست كبير",
        "wind_notes": "ريح الشرق-شمال = وش | ريح الشمال = وس جزئي",
    },
    {
        "name_ar":  "الحمامات الجنوبية",
        "name_fr":  "Hammamet South",
        "lat_min":  36.34, "lat_max": 36.44,
        "lon_min":  10.55, "lon_max": 10.72,
        "normal":   95.0,   # slightly south of East
        "depth_profile": "رملي مفتوح",
        "target_species": "تاكوست، سباط نهاري",
        "wind_notes": "ريح الشرق الجنوبي = وش | ريح الشمال = جانبي كبير",
    },

    # ── GREATER TUNIS / NORTH ────────────────────────────────────────────────
    {
        "name_ar":  "بنزرت — الشاطئ الشمالي",
        "name_fr":  "Bizerte — Northern Shore",
        "lat_min":  37.20, "lat_max": 37.40,
        "lon_min":  9.75,  "lon_max": 10.05,
        "normal":   330.0,  # NNW — faces open Mediterranean
        "depth_profile": "صخري-رملي",
        "target_species": "تون، سرغ، مكنين",
        "wind_notes": "ريح الشمال الشمالي الغربي = وش | ريح الغرب = وس جانبي",
    },
    {
        "name_ar":  "رأس الطيب",
        "name_fr":  "Ras El Tib",
        "lat_min":  37.05, "lat_max": 37.20,
        "lon_min":  11.00, "lon_max": 11.18,
        "normal":   45.0,   # NE facing
        "depth_profile": "صخري عميق",
        "target_species": "مورين، شرش، سرغ",
        "wind_notes": "ريح الشمال الشرقي = وش | ريح الشمال = وس قليل",
    },
    {
        "name_ar":  "خليج تونس الشرقي — رادس",
        "name_fr":  "Gulf of Tunis East — Rades",
        "lat_min":  36.75, "lat_max": 37.05,
        "lon_min":  10.18, "lon_max": 10.45,
        "normal":   60.0,
        "depth_profile": "طيني-رملي",
        "target_species": "سباط، تاكوست",
        "wind_notes": "ريح الشمال الشرقي = وش",
    },

    # ── SAHEL / CENTER ───────────────────────────────────────────────────────
    {
        "name_ar":  "سوسة — الشاطئ الشرقي",
        "name_fr":  "Sousse — Eastern Beach",
        "lat_min":  35.70, "lat_max": 36.05,
        "lon_min":  10.55, "lon_max": 10.75,
        "normal":   85.0,
        "depth_profile": "رملي مفتوح",
        "target_species": "تاكوست، دنيس، سباط",
        "wind_notes": "ريح الشرق = وش مثالي | ريح الشمال = وس مائل",
    },
    {
        "name_ar":  "المهدية",
        "name_fr":  "Mahdia",
        "lat_min":  35.35, "lat_max": 35.65,
        "lon_min":  10.95, "lon_max": 11.15,
        "normal":   75.0,
        "depth_profile": "صخري-رملي متبادل",
        "target_species": "مورين ليلي، دنيس، شرش",
        "wind_notes": "ريح الشرق = وش | ريح الشمال الشرقي = وش قوي | ريح الشمال = وس",
    },
    {
        "name_ar":  "صفاقس — خليج قابس الشمالي",
        "name_fr":  "Sfax — North Gulf of Gabes",
        "lat_min":  34.55, "lat_max": 35.35,
        "lon_min":  10.55, "lon_max": 11.10,
        "normal":   100.0,  # ESE — shallow gulf
        "depth_profile": "طيني ضحل — تأثير مدي قوي",
        "target_species": "روبيان، قرباس، سيج",
        "wind_notes": "تأثير المد والجزر أهم من الريح في هذه المنطقة",
    },

    # ── SOUTH / DJERBA ───────────────────────────────────────────────────────
    {
        "name_ar":  "جربة — الشاطئ الشمالي",
        "name_fr":  "Djerba — North Shore",
        "lat_min":  33.85, "lat_max": 33.95,
        "lon_min":  10.85, "lon_max": 11.10,
        "normal":   10.0,   # faces North
        "depth_profile": "رملي ضحل أبيض",
        "target_species": "دنيس، سباط، بلطي بحري",
        "wind_notes": "ريح الشمال = وش | ريح الشرق/الغرب = جانبي شديد",
    },
    {
        "name_ar":  "جربة — الشاطئ الشرقي",
        "name_fr":  "Djerba — East Shore",
        "lat_min":  33.72, "lat_max": 33.86,
        "lon_min":  11.05, "lon_max": 11.22,
        "normal":   80.0,
        "depth_profile": "رملي-صخري",
        "target_species": "دنيس، تاكوست",
        "wind_notes": "ريح الشرق = وش | ريح الجنوب = وس جانبي",
    },
    {
        "name_ar":  "زارزيس — الساحل الجنوبي",
        "name_fr":  "Zarzis — Southern Coast",
        "lat_min":  33.40, "lat_max": 33.72,
        "lon_min":  11.05, "lon_max": 11.40,
        "normal":   120.0,  # SSE
        "depth_profile": "رملي مع صخور متناثرة",
        "target_species": "دنيس كبير، مكنين، روبيان",
        "wind_notes": "ريح الجنوب الشرقي = وش | ريح الشرق = وس",
    },
]


def get_coastal_zone(lat: float, lon: float) -> dict:
    """
    Returns the matching coastal zone dict for the given coordinates.
    Falls back to a generic Mediterranean default if no zone matches.
    BUG FIX #3: provides real shoreline_normal for each local zone.
    """
    for zone in COASTAL_ZONES:
        if (zone["lat_min"] <= lat <= zone["lat_max"] and
                zone["lon_min"] <= lon <= zone["lon_max"]):
            return zone

    # Generic Mediterranean default (East-facing coast assumption)
    return {
        "name_ar":  "ساحل متوسطي غير محدد",
        "name_fr":  "Unregistered Mediterranean Coast",
        "normal":   90.0,
        "depth_profile": "غير معروف",
        "target_species": "غير محدد",
        "wind_notes": "استخدام اتجاه شرقي افتراضي — حدد موقعاً ساحلياً معروفاً",
    }


# =============================================================================
# 3. SESSION STATE BOOTSTRAP — idempotent, safe on every rerun
# =============================================================================
def _init_session() -> None:
    defaults = {
        "lat":               DEFAULT_LAT,
        "lon":               DEFAULT_LON,
        "data_ready":        False,
        "scores":            None,
        "avg_score":         0.0,
        "max_score":         0.0,
        "best_hour":         "N/A",
        "go_hours":          0,
        "go_decision":       "NO-GO",
        "sea_dirty":         False,
        "is_inland":         False,
        "zone":              None,
        "gemini_report":     None,
        "past_avg_h":        0.0,
        "past_avg_t":        0.0,
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

_init_session()

# =============================================================================
# 4. CUSTOM CSS — RTL + score palette + premium UI
# =============================================================================
st.markdown("""
<style>
    /* RTL Arabic rendering */
    .rtl { direction: rtl; text-align: right;
           font-family: 'Segoe UI', Tahoma, Arial, sans-serif;
           font-size: 1.05em; line-height: 1.8; }

    /* Score color system */
    .s-green  { color: #1e8449; font-weight: 700; }
    .s-yellow { color: #b7950b; font-weight: 700; }
    .s-red    { color: #922b21; font-weight: 700; }

    /* Header banner */
    .banner {
        background: linear-gradient(135deg, #0b2545, #1565c0, #0288d1);
        padding: 22px 30px; border-radius: 14px; margin-bottom: 20px;
    }
    .banner h1 { color: #ffffff; margin: 0; font-size: 1.9em; }
    .banner p  { color: #b3d4f5; margin: 6px 0 0 0; font-size: 0.95em; }

    /* Zone info card */
    .zone-card {
        background: #0d3349; color: #e8f4fd;
        border-left: 4px solid #0288d1;
        padding: 12px 18px; border-radius: 8px;
        margin: 10px 0; font-size: 0.92em;
    }
    .zone-card b { color: #4fc3f7; }

    /* Map iframe */
    iframe { border-radius: 12px; }

    /* Streamlit block padding */
    .block-container { padding-top: 0.8rem; }
</style>
""", unsafe_allow_html=True)

# =============================================================================
# 5. HEADER
# =============================================================================
st.markdown("""
<div class="banner">
  <h1>🎣 مستشار صيد الشاطئ — Surfcasting Advisor</h1>
  <p>محرك الهيدروديناميكا الساحلية النهائي — ولاية نابل والسواحل التونسية •
     Final Coastal Hydrodynamics Decision Engine</p>
</div>
""", unsafe_allow_html=True)

# =============================================================================
# 6. INTERACTIVE FOLIUM MAP — Zero-lag reactive coordinates
# =============================================================================
st.subheader("📍 اختر نقطة الصيد / Select Fishing Spot")
st.caption(
    "انقر مباشرة على الشاطئ • بطاقات المناطق الزرقاء = مناطق محددة مسبقاً • "
    "Click on the coastline — blue markers = pre-mapped zones"
)

_m = folium.Map(
    location=[st.session_state.lat, st.session_state.lon],
    zoom_start=9,
    tiles="CartoDB positron",
    control_scale=True,
)

# Current-selection anchor marker
folium.Marker(
    location=[st.session_state.lat, st.session_state.lon],
    popup=folium.Popup(
        f"<b>📍 نقطة الصيد المختارة</b><br>"
        f"Lat: {st.session_state.lat:.5f}<br>"
        f"Lon: {st.session_state.lon:.5f}",
        max_width=240,
    ),
    tooltip="نقطتك الحالية",
    icon=folium.Icon(color="red", icon="anchor", prefix="fa"),
).add_to(_m)

# Plot all known coastal zones as clickable circles
_ZONE_CENTERS = {
    "الرتيبة":       (36.45, 10.72),
    "سيدي محرصي":    (36.62, 10.80),
    "كركوان":        (36.88, 11.05),
    "نابل":          (36.47, 10.74),
    "قربة":          (36.61, 10.87),
    "الحمامات ج":    (36.39, 10.62),
    "بنزرت":         (37.28, 9.87),
    "رأس الطيب":     (37.12, 11.08),
    "سوسة":          (35.83, 10.63),
    "المهدية":       (35.50, 11.05),
    "جربة ش":        (33.90, 10.97),
    "زارزيس":        (33.55, 11.22),
}
for _zname, (_zlat, _zlon) in _ZONE_CENTERS.items():
    folium.CircleMarker(
        location=[_zlat, _zlon],
        radius=8, color="#0288d1",
        fill=True, fill_color="#0288d1", fill_opacity=0.65,
        tooltip=_zname,
    ).add_to(_m)

_map_out = st_folium(
    _m, width="100%", height=480,
    returned_objects=["last_clicked"],
    key="map_main",
)

# BUG FIX: rerun ONLY when coords genuinely change — eliminates render loops
if _map_out and _map_out.get("last_clicked"):
    _nc = _map_out["last_clicked"]
    _nlat = round(float(_nc["lat"]), 6)
    _nlon = round(float(_nc["lng"]), 6)
    if _nlat != st.session_state.lat or _nlon != st.session_state.lon:
        st.session_state.lat      = _nlat
        st.session_state.lon      = _nlon
        st.session_state.data_ready   = False
        st.session_state.scores       = None
        st.session_state.gemini_report = None
        st.rerun()

# Coordinate display
_c1, _c2, _c3 = st.columns(3)
_c1.metric("🌐 خط العرض / Latitude",  f"{st.session_state.lat:.6f}°")
_c2.metric("🌐 خط الطول / Longitude", f"{st.session_state.lon:.6f}°")

# Zone detection — instant, no API call
_active_zone = get_coastal_zone(st.session_state.lat, st.session_state.lon)
st.session_state.zone = _active_zone
_c3.metric("📍 المنطقة / Zone", _active_zone.get("name_ar", "N/A")[:28])

# Zone information card (RTL)
st.markdown(f"""
<div class="zone-card">
  <b>🗺️ المنطقة الساحلية المكتشفة:</b> {_active_zone.get("name_ar","—")}
  &nbsp;|&nbsp; {_active_zone.get("name_fr","—")}<br>
  <b>📐 اتجاه العمود على الشاطئ (Normal):</b>
  {_active_zone.get("normal", 90.0):.1f}°
  &nbsp;|&nbsp;
  <b>🌊 القاع:</b> {_active_zone.get("depth_profile","—")}<br>
  <b>🐟 الأسماك المستهدفة:</b> {_active_zone.get("target_species","—")}<br>
  <b>💨 ملاحظات الريح المحلية:</b>
  <span class="rtl">{_active_zone.get("wind_notes","—")}</span>
</div>
""", unsafe_allow_html=True)

st.markdown("---")

# =============================================================================
# 7. API FETCHING FUNCTIONS — Parameterized dict, no f-string URL building
# =============================================================================

def fetch_marine(lat: float, lon: float) -> dict:
    """
    BUG FIX #2 params dict pattern.
    BUG FIX #9 timezone forced to UTC.
    """
    params = {
        "latitude":      lat,
        "longitude":     lon,
        "hourly":        "wave_height,wave_period,wave_direction",
        "past_days":     PAST_DAYS,
        "forecast_days": FORECAST_DAYS,
        "timezone":      TIMEZONE,
    }
    r = requests.get(MARINE_API_BASE, params=params, timeout=25)
    r.raise_for_status()
    data = r.json()
    if "hourly" not in data:
        raise ValueError(f"No 'hourly' block. Keys: {list(data.keys())}")
    return data["hourly"]


def fetch_weather(lat: float, lon: float) -> dict:
    """
    BUG FIX #9 timezone forced UTC — same as marine to prevent array drift.
    """
    params = {
        "latitude":        lat,
        "longitude":       lon,
        "hourly":          "wind_speed_10m,wind_direction_10m",
        "past_days":       PAST_DAYS,
        "forecast_days":   FORECAST_DAYS,
        "timezone":        TIMEZONE,
        "wind_speed_unit": "kmh",
    }
    r = requests.get(WEATHER_API_BASE, params=params, timeout=25)
    r.raise_for_status()
    data = r.json()
    if "hourly" not in data:
        raise ValueError("No 'hourly' block in weather response.")
    return data["hourly"]


def jonswap_fallback_marine(n: int, wind_data: dict) -> dict:
    """
    BUG FIX #7: Physics-based JONSWAP approximation replaces flat 0.45m array.
    Hs ≈ 0.0016 * (U²*F/g)^0.5  simplified for Mediterranean fetch ~50 km.
    Wave direction follows wind direction (same source).
    """
    fetch_m   = 50_000.0   # 50 km representative Mediterranean fetch
    g         = 9.81
    speeds    = wind_data.get("wind_speed_10m",    [10.0] * n)
    wdirs     = wind_data.get("wind_direction_10m", [50.0] * n)
    heights, periods, wave_dirs = [], [], []

    for i in range(n):
        u_kmh = float(speeds[i]) if speeds[i] is not None else 10.0
        u_ms  = u_kmh / 3.6
        # JONSWAP significant wave height (simplified, no depth correction)
        hs = 0.0016 * math.sqrt(u_ms ** 2 * fetch_m / g)
        hs = round(max(0.05, min(hs, 2.5)), 3)
        # Peak period from JONSWAP dispersion
        tp = 0.286 * math.sqrt(fetch_m / g) * (u_ms ** (1 / 3)) if u_ms > 0 else 4.0
        tp = round(max(3.0, min(tp, 12.0)), 3)
        # Wave direction = wind direction (wind-driven seas)
        wd = float(wdirs[i]) if wdirs[i] is not None else 50.0
        heights.append(hs)
        periods.append(tp)
        wave_dirs.append(round(wd, 2))

    return {"wave_height": heights, "wave_period": periods, "wave_direction": wave_dirs}


def find_tomorrow_start_index(time_array: list[str]) -> int:
    """
    BUG FIX #1: Parse actual ISO timestamps to locate tomorrow 00:00 UTC.
    Eliminates the hardcoded index-48 assumption that returned today's hours.
    """
    tomorrow = (datetime.now(timezone.utc) + timedelta(days=1)).date()
    for idx, ts in enumerate(time_array):
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
            if dt.date() == tomorrow and dt.hour == 0:
                return idx
        except (ValueError, TypeError):
            continue
    # Arithmetic fallback: PAST_DAYS*24 + 24 = 72 for past_days=2, forecast_days=3
    return PAST_DAYS * 24 + 24


def fmt_ts(ts: str) -> str:
    """
    BUG FIX #12: Robust ISO timestamp formatter replacing the fragile [-8:-3] slice.
    Returns 'DD/MM HH:MM' in UTC for unambiguous display.
    """
    try:
        dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        return dt.strftime("%d/%m %H:%M")
    except (ValueError, TypeError):
        return str(ts)


def null_safe(val, fallback: float) -> float:
    """Coerce None / NaN API values to a safe numeric fallback."""
    if val is None:
        return fallback
    try:
        f = float(val)
        return fallback if math.isnan(f) else f
    except (TypeError, ValueError):
        return fallback


# =============================================================================
# 8. FETCH + SCORE TRIGGER
# =============================================================================
st.subheader("🌊 جلب وتحليل البيانات / Fetch & Analyze")
_btn = st.button(
    "🔍 ابدأ التحليل الهيدروديناميكي / Start Analysis",
    type="primary", use_container_width=True,
)

if _btn:
    st.session_state.data_ready    = False
    st.session_state.is_inland     = False
    st.session_state.gemini_report = None

    # ── 8a. Weather (always exists) ──────────────────────────────────────────
    with st.spinner("📡 جلب بيانات الرياح..."):
        try:
            wx = fetch_weather(st.session_state.lat, st.session_state.lon)
        except Exception as e:
            st.error(f"❌ فشل API الطقس: `{e}`")
            st.stop()

    n_total = len(wx.get("wind_speed_10m", []))

    # ── 8b. Marine (with inland graceful fallback) ───────────────────────────
    with st.spinner("🌊 جلب بيانات الأمواج..."):
        try:
            mx = fetch_marine(st.session_state.lat, st.session_state.lon)
        except Exception as marine_err:
            st.session_state.is_inland = True
            mx = jonswap_fallback_marine(n_total, wx)  # BUG FIX #7
            st.warning(
                "⚠️ **المنطقة المختارة خارج نطاق Marine API — محاكاة JONSWAP مفعّلة**\n\n"
                "تم توليد بيانات الأمواج رياضياً من بيانات الريح باستخدام معادلة JONSWAP "
                "المبسّطة (fetch = 50 كم). هذه تقديرات فيزيائية، وليست قياسات حقيقية. "
                "يُنصح باختيار نقطة ساحلية مسجّلة لتحليل دقيق.\n\n"
                f"*Technical: `{str(marine_err)[:100]}`*"
            )

    # ── 8c. Array alignment & null-safety ────────────────────────────────────
    ts_arr  = wx.get("time",                [f"T{i}" for i in range(n_total)])
    wh_arr  = [null_safe(v, 0.30)  for v in mx.get("wave_height",    [])]
    wp_arr  = [null_safe(v, 5.50)  for v in mx.get("wave_period",    [])]
    wdv_arr = [null_safe(v, 0.00)  for v in mx.get("wave_direction", [])]
    wsp_arr = [null_safe(v, 0.00)  for v in wx.get("wind_speed_10m", [])]
    wdr_arr = [null_safe(v, 0.00)  for v in wx.get("wind_direction_10m", [])]

    n = min(len(ts_arr), len(wh_arr), len(wp_arr),
            len(wdv_arr), len(wsp_arr), len(wdr_arr))

    if n < HISTORY_HOURS + 1:
        st.error(
            f"❌ بيانات غير كافية ({n} نقطة، مطلوب {HISTORY_HOURS + 1}). "
            "حاول لاحقاً أو غيّر الموقع."
        )
        st.stop()

    ts_arr  = ts_arr[:n];  wh_arr  = wh_arr[:n];  wp_arr  = wp_arr[:n]
    wdv_arr = wdv_arr[:n]; wsp_arr = wsp_arr[:n]; wdr_arr = wdr_arr[:n]

    # ── 8d. Historical baseline (past 48 h) ──────────────────────────────────
    past_wh = wh_arr[:HISTORY_HOURS]
    past_wp = wp_arr[:HISTORY_HOURS]
    avg_past_h = sum(past_wh) / len(past_wh)
    avg_past_t = sum(past_wp) / len(past_wp)
    sea_dirty  = (avg_past_h > WEED_MIN_H and avg_past_t > WEED_MIN_T)
    st.session_state.sea_dirty  = sea_dirty
    st.session_state.past_avg_h = avg_past_h
    st.session_state.past_avg_t = avg_past_t

    # ── 8e. BUG FIX #1 — Locate tomorrow's real start index ─────────────────
    tomorrow_idx = find_tomorrow_start_index(ts_arr)
    tomorrow_end = min(tomorrow_idx + 24, n)   # analyse exactly 24 h of tomorrow

    if tomorrow_idx >= n:
        st.error(
            "❌ لا توجد بيانات ليوم الغد في النافذة الزمنية المسترجعة. "
            "تحقق من إعدادات forecast_days."
        )
        st.stop()

    # ── 8f. Shoreline normal for this zone ───────────────────────────────────
    shore_normal = _active_zone.get("normal", 90.0)

    # ── 8g. Hourly Fishing Score Engine (tomorrow only) ──────────────────────
    scores: list[dict] = []

    for i in range(tomorrow_idx, tomorrow_end):
        h   = wh_arr[i]    # wave height (m)
        p   = wp_arr[i]    # wave period (s)
        wdv = wdv_arr[i]   # wave direction TO (°) — Open-Meteo "direction of travel"
        spd = wsp_arr[i]   # wind speed (km/h)
        wnd = wdr_arr[i]   # wind direction FROM (°) — meteorological convention
        ts  = ts_arr[i]

        score = SCORE_BASELINE   # 10.0

        # ── RULE 1: Dead Sea Penalty ─────────────────────────────────────────
        dead_sea = (h < DEAD_SEA_MAX_H)
        if dead_sea:
            score -= DEAD_SEA_PENALTY

        # ── RULE 2: Weed Penalty with temporal decay ─────────────────────────
        # BUG FIX #4: baseline dirty effect decays linearly over 24 h
        # BUG FIX #5: mutually exclusive with dead_sea (0.3m can't suspend weed)
        currently_rough = (h > WEED_MIN_H and p > WEED_MIN_T)
        weed_active = False
        if not dead_sea:
            hours_since_history = i - HISTORY_HOURS
            dirty_decay = max(0.0, 1.0 - (hours_since_history / DIRTY_DECAY_HOURS))
            if currently_rough:
                score -= WEED_PENALTY
                weed_active = True
            elif sea_dirty and dirty_decay > 0.0:
                score -= WEED_PENALTY * dirty_decay
                weed_active = True

        # ── RULE 3 & BUG FIX #2: Unified FROM convention ────────────────────
        # wave_direction in Open-Meteo = direction waves are TRAVELLING TO
        # Convert to FROM convention to match wind_direction_10m (also FROM)
        wave_from = (wdv + 180.0) % 360.0

        # Circular boundary fix (prevents 359°-1° = 358° ghost)
        raw_diff = abs(wnd - wave_from)
        wave_wind_diff = 360.0 - raw_diff if raw_diff > 180.0 else raw_diff

        # ── RULE 3 & BUG FIX #3: Wind vs SHORELINE normal (not wave dir) ────
        raw_shore_diff = abs(wnd - shore_normal)
        wind_vs_shore  = 360.0 - raw_shore_diff if raw_shore_diff > 180.0 else raw_shore_diff
        # 0° = wind blowing straight onshore (وش) → perpendicular, ideal
        # 90° = wind parallel to coast → fully lateral, dangerous

        is_lateral     = LATERAL_ANGLE_LOW < wind_vs_shore < LATERAL_ANGLE_HIGH
        is_perpendicular = not is_lateral

        # ── RULE 4: Lateral Drift Penalty ('تيار الحمل') ─────────────────────
        if is_lateral:
            if spd > LATERAL_STRONG_SPD:
                score -= LATERAL_STRONG_PEN   # lead loses traction entirely
            elif spd > LATERAL_MOD_SPD:
                score -= LATERAL_MOD_PEN      # moderate drift

        # ── RULE 5: White Foam Belt Bonus ('Écume / الرغوة') ─────────────────
        foam_bonus_applied = False
        if (FOAM_MIN_H <= h <= FOAM_MAX_H and
                spd > FOAM_MIN_SPD and is_perpendicular):
            score += FOAM_BONUS
            foam_bonus_applied = True

        # ── RULE 6: Wave Sieve Cleansing Bonus ('الموج ينظف نفسه') ──────────
        # BUG FIX #6: applies whenever sea was dirty AND sieve conditions met,
        # regardless of foam (separate phenomenon)
        sieve_bonus_applied = False
        if (SIEVE_MIN_T <= p <= SIEVE_MAX_T and
                h > SIEVE_MIN_H and
                is_perpendicular and
                sea_dirty):
            score += SIEVE_BONUS
            sieve_bonus_applied = True

        # ── Clamp ────────────────────────────────────────────────────────────
        score = round(max(SCORE_MIN, min(SCORE_MAX, score)), 2)

        scores.append({
            "time":               ts,
            "time_fmt":           fmt_ts(ts),     # BUG FIX #12
            "fishing_score":      score,
            "wave_height_m":      round(h,   3),
            "wave_period_s":      round(p,   3),
            "wave_dir_to_deg":    round(wdv, 2),
            "wave_dir_from_deg":  round(wave_from, 2),
            "wind_speed_kmh":     round(spd, 2),
            "wind_dir_from_deg":  round(wnd, 2),
            "wind_vs_shore_deg":  round(wind_vs_shore, 2),
            "wave_wind_diff_deg": round(wave_wind_diff, 2),
            "shore_normal_deg":   shore_normal,
            "is_lateral":         is_lateral,
            "is_perpendicular":   is_perpendicular,
            "dead_sea":           dead_sea,
            "weed_active":        weed_active,
            "currently_rough":    currently_rough,
            "foam_bonus":         foam_bonus_applied,
            "sieve_bonus":        sieve_bonus_applied,
            "sea_baseline_dirty": sea_dirty,
        })

    # ── 8h. Aggregate statistics ──────────────────────────────────────────────
    avg_score = round(sum(r["fishing_score"] for r in scores) / len(scores), 2) if scores else 0.0
    max_score = max((r["fishing_score"] for r in scores), default=0.0)
    best_hour = next((r["time_fmt"] for r in scores if r["fishing_score"] == max_score), "N/A")
    go_hours  = sum(1 for r in scores if r["fishing_score"] >= GO_MIN_AVG)

    # BUG FIX #8: GO requires BOTH avg AND hours — AND not OR
    if avg_score >= GO_MIN_AVG and go_hours >= GO_MIN_HOURS:
        go_decision = "GO"
    elif avg_score >= 4.0 or go_hours >= 4:
        go_decision = "CONDITIONAL"
    else:
        go_decision = "NO-GO"

    # Persist to session state
    st.session_state.scores      = scores
    st.session_state.avg_score   = avg_score
    st.session_state.max_score   = max_score
    st.session_state.best_hour   = best_hour
    st.session_state.go_hours    = go_hours
    st.session_state.go_decision = go_decision
    st.session_state.data_ready  = True

# =============================================================================
# 9. RESULTS DISPLAY — only when data is ready
# =============================================================================
if st.session_state.data_ready and st.session_state.scores:
    scores      = st.session_state.scores
    avg_score   = st.session_state.avg_score
    max_score   = st.session_state.max_score
    best_hour   = st.session_state.best_hour
    go_hours    = st.session_state.go_hours
    go_decision = st.session_state.go_decision
    sea_dirty   = st.session_state.sea_dirty

    st.markdown("---")
    st.subheader("📊 مصفوفة نقاط الصيد — 24 ساعة / 24-Hour Score Matrix")

    # ── KPI row ──────────────────────────────────────────────────────────────
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("📈 المتوسط / Avg", f"{avg_score:.2f}/10")
    k2.metric("⭐ الذروة / Peak",  f"{max_score:.2f}/10")
    k3.metric("🕐 أفضل ساعة",     best_hour)
    k4.metric("✅ ساعات جيدة (≥6)", f"{go_hours}/24")

    _dec_color = {"GO": "🟢", "CONDITIONAL": "🟡", "NO-GO": "🔴"}
    k5.metric("⚔️ القرار", f"{_dec_color.get(go_decision,'')} {go_decision}")

    # ── Score data-table ──────────────────────────────────────────────────────
    df = pd.DataFrame(scores)
    df_disp = df[[
        "time_fmt", "fishing_score", "wave_height_m", "wave_period_s",
        "wind_speed_kmh", "wind_vs_shore_deg", "is_lateral",
        "weed_active", "foam_bonus", "sieve_bonus",
    ]].copy()
    df_disp.columns = [
        "🕐 الوقت", "🎯 النقطة", "🌊 موج(م)",
        "⏱️ دورة(ث)", "💨 ريح(كم/س)", "📐 زاوية الشاطئ°",
        "↔️ جانبي؟", "🌿 مدرر؟", "🌫️ رغوة+", "🧹 تنظيف+"
    ]

    def _score_style(val):
        if isinstance(val, float):
            if val >= 7.0: return "background:#1e8449;color:white;font-weight:bold"
            if val >= 4.5: return "background:#b7950b;color:white;font-weight:bold"
            return "background:#922b21;color:white;font-weight:bold"
        return ""

    # BUG FIX #10: use .map() — applymap deprecated since pandas 2.1
    styled_df = df_disp.style.map(_score_style, subset=["🎯 النقطة"])
    st.dataframe(styled_df, use_container_width=True, height=440)

    # ── Historical baseline expander ──────────────────────────────────────────
    with st.expander("📜 الخط الأساسي التاريخي (48 ساعة الماضية)"):
        st.markdown(f"""
| المؤشر | القيمة |
|---|---|
| متوسط ارتفاع الموج (48h) | `{st.session_state.past_avg_h:.3f} m` |
| متوسط دورة الموج (48h)   | `{st.session_state.past_avg_t:.3f} s` |
| حالة البحر التاريخية      | **{"🔴 مدرر — Historically Dirty" if sea_dirty else "🟢 نظيف — Clean Baseline"}** |
| عمود الشاطئ (Shore Normal)| **{_active_zone.get("normal",90.0):.1f}°** |
| وضع المحاكاة JONSWAP      | **{"⚠️ نعم" if st.session_state.is_inland else "✅ لا — بيانات حقيقية"}** |
        """)

    # ── Angle interpretation legend ───────────────────────────────────────────
    with st.expander("📐 تفسير زاوية الشاطئ — Angle Interpretation Guide"):
        st.markdown(f"""
**اتجاه العمود على الشاطئ في منطقتك = `{_active_zone.get("normal",90.0):.1f}°`**

| الزاوية (wind vs shore) | التفسير | تأثير الإثقالة |
|---|---|---|
| **0° – 30°** | ريح وش 🟢 — عمودية على الشاطئ | تثبت ممتاز، لا جر |
| **30° – 150°** | ريح وس / جانبي 🟡🔴 — مائلة | الرصاصة تنزلق وترجع للشاطئ |
| **150° – 180°** | ريح ظهري 🟡 — من خلف الصياد | يساعد الرمي لكن يضعف الاستشعار |

{_active_zone.get("wind_notes", "")}
        """)

    st.markdown("---")

    # =========================================================================
    # 10. GEMINI 1.5 FLASH — Strategic Arabic Advisory
    # =========================================================================
    st.subheader("🤖 التقرير الاستراتيجي الكامل / Full Gemini Advisory")

    _key = os.environ.get("GEMINI_API_KEY")
    if not _key:
        st.warning(
            "⚠️ **GEMINI_API_KEY غير موجود**\n\n"
            "أضف المفتاح إلى Environment Variables في Render لتفعيل التقرير الاستراتيجي."
        )
    else:
        genai.configure(api_key=_key)
        _model = genai.GenerativeModel("gemini-1.5-flash")

        # Serialize the pre-computed score array as compact JSON
        scores_json = json.dumps(scores, ensure_ascii=False, indent=2, default=str)

        # Prepare a human-readable sieve hours list for Gemini
        sieve_hours = [r["time_fmt"] for r in scores if r["sieve_bonus"]]
        foam_hours  = [r["time_fmt"] for r in scores if r["foam_bonus"]]
        lateral_hours = [r["time_fmt"] for r in scores if r["is_lateral"]]
        dead_hours  = [r["time_fmt"] for r in scores if r["dead_sea"]]

        # BUG FIX #8: pass pre-computed GO/NO-GO — AI only translates, never decides
        prompt = f"""
أنت صياد شاطئ تونسي محترف (Surfcasting) ومحلل هيدروديناميكي ساحلي.
لديك خبرة ميدانية عميقة في سواحل نابل: الرتيبة، سيدي محرصي، كركوان، قربة، نابل، الحمامات.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 البيانات الرياضية المحسوبة نهائياً (JSON — لا تُعدّل أي رقم إطلاقاً):
```json
{scores_json}
