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
USER_AGENT   = "TunisiaFishingAdvisor/10.6"
GEMINI_MODEL = "gemini-2.5-flash"

st.set_page_config(
    page_title="🎣 مستشار الصيد | تونس",
    page_icon="🎣",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
body{direction:rtl}
.block-container{padding-top:.5rem}
.go-box{background:linear-gradient(135deg,#0a3d0a,#0d520d);
        padding:18px;border-radius:10px;border:2px solid #00ff00;margin:10px 0}
.warn-box{background:linear-gradient(135deg,#3d2e0a,#52400d);
          padding:18px;border-radius:10px;border:2px solid #ffa500;margin:10px 0}
.nogo-box{background:linear-gradient(135deg,#3d0a0a,#520d0d);
          padding:18px;border-radius:10px;border:2px solid #ff0000;margin:10px 0}
.spot-card{background:#0a1a2e;padding:12px;border-radius:8px;
           border:1px solid #1f77b4;margin-bottom:6px}
.top-spot{background:#111c2d;padding:12px;border-radius:8px;
          border:1px solid #3b82f6;margin-bottom:6px}
</style>
""", unsafe_allow_html=True)

# ══════════════════════════════════════════════════════════════
# 2. SESSION STATE
# ══════════════════════════════════════════════════════════════
_DEF = {
    "lat": 36.8333, "lon": 11.1000,
    "day_offset": 1,
    "scan_results": None,
    "deep_result": None,
}
for k, v in _DEF.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ══════════════════════════════════════════════════════════════
# 3. SPOTS DATABASE
# ══════════════════════════════════════════════════════════════
SPOTS = [
    {"name": "طبرقة",                "lat": 36.9544, "lon":  8.7578, "region": "جندوبة"},
    {"name": "رأس أنجلة",           "lat": 37.3470, "lon":  9.7440, "region": "بنزرت"},
    {"name": "بنزرت المرسى",         "lat": 37.2744, "lon":  9.8628, "region": "بنزرت"},
    {"name": "رأس الدرك",            "lat": 37.2742, "lon":  9.8739, "region": "بنزرت"},
    {"name": "غار الملح",            "lat": 37.1728, "lon": 10.0872, "region": "بنزرت"},
    {"name": "رفراف",                "lat": 37.1889, "lon": 10.1833, "region": "بنزرت"},
    {"name": "سيدي علي المكي",       "lat": 37.1470, "lon": 10.2500, "region": "بنزرت"},
    {"name": "قمرت",                 "lat": 36.9200, "lon": 10.2900, "region": "تونس"},
    {"name": "المرسى",               "lat": 36.8780, "lon": 10.3300, "region": "تونس"},
    {"name": "سليمان الشاطئ",        "lat": 36.7060, "lon": 10.4920, "region": "نابل"},
    {"name": "قربة",                 "lat": 36.5780, "lon": 10.8580, "region": "نابل"},
    {"name": "منزل تميم",            "lat": 36.7810, "lon": 10.9950, "region": "نابل"},
    {"name": "قليبية",               "lat": 36.8333, "lon": 11.1000, "region": "نابل"},
    {"name": "الهوارية",             "lat": 37.0539, "lon": 11.0581, "region": "نابل"},
    {"name": "نابل الشاطئ",          "lat": 36.4561, "lon": 10.7376, "region": "نابل"},
    {"name": "الحمامات الشمالية",    "lat": 36.4300, "lon": 10.7000, "region": "نابل"},
    {"name": "الحمامات الجنوبية",    "lat": 36.3600, "lon": 10.5400, "region": "نابل"},
    {"name": "هرقلة",                "lat": 36.0330, "lon": 10.5100, "region": "سوسة"},
    {"name": "شط مريم",              "lat": 35.9300, "lon": 10.5600, "region": "سوسة"},
    {"name": "سوسة بوجعفر",          "lat": 35.8256, "lon": 10.6369, "region": "سوسة"},
    {"name": "المنستير",             "lat": 35.7672, "lon": 10.8111, "region": "المنستير"},
    {"name": "صيادة",                "lat": 35.6680, "lon": 10.8900, "region": "المنستير"},
    {"name": "المهدية",              "lat": 35.5047, "lon": 11.0622, "region": "المهدية"},
    {"name": "الشابة",               "lat": 35.2370, "lon": 11.1150, "region": "المهدية"},
    {"name": "صفاقس",                "lat": 34.7333, "lon": 10.7633, "region": "صفاقس"},
    {"name": "قرقنة",                "lat": 34.7333, "lon": 11.1167, "region": "صفاقس"},
    {"name": "قابس",                 "lat": 33.8815, "lon": 10.0982, "region": "قابس"},
    {"name": "بوغرارة",              "lat": 33.6500, "lon": 10.7500, "region": "مدنين"},
    {"name": "جربة أجيم",            "lat": 33.7167, "lon": 10.7667, "region": "جربة"},
    {"name": "أغير",                 "lat": 33.7700, "lon": 11.0300, "region": "جربة"},
    {"name": "جرجيس",                "lat": 33.5042, "lon": 10.8681, "region": "مدنين"},
]

SPOT_NAMES = [f"{s['name']} — {s['region']}" for s in SPOTS]

# ══════════════════════════════════════════════════════════════
# 4. MATH
# ══════════════════════════════════════════════════════════════
def safe_avg(lst):
    return sum(lst)/len(lst) if lst else 0.0

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
    dlat = math.radians(lat2-lat1); dlon = math.radians(lon2-lon1)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(lat1))*math.cos(math.radians(lat2))*math.sin(dlon/2)**2
    return round(2*R*math.asin(math.sqrt(a)), 1)

def destination_point(lat1, lon1, bearing, dist):
    R = 6371.0; b = math.radians(bearing)
    p1 = math.radians(lat1); l1 = math.radians(lon1)
    p2 = math.asin(math.sin(p1)*math.cos(dist/R)+math.cos(p1)*math.sin(dist/R)*math.cos(b))
    l2 = l1+math.atan2(math.sin(b)*math.sin(dist/R)*math.cos(p1),math.cos(dist/R)-math.sin(p1)*math.sin(p2))
    return math.degrees(p2), math.degrees(l2)

def fmt_date_ar(d):
    days = ["الاثنين","الثلاثاء","الأربعاء","الخميس","الجمعة","السبت","الأحد"]
    months = {1:"جانفي",2:"فيفري",3:"مارس",4:"أفريل",5:"ماي",6:"جوان",
              7:"جويلية",8:"أوت",9:"سبتمبر",10:"أكتوبر",11:"نوفمبر",12:"ديسمبر"}
    return f"{days[d.weekday()]} {d.day} {months[d.month]} {d.year}"

def parse_dt(ts): return datetime.fromisoformat(ts)

def target_date_from_offset(off):
    return datetime.now(TUNIS_TZ).date() + timedelta(days=off)

# ══════════════════════════════════════════════════════════════
# 5. HTTP
# ══════════════════════════════════════════════════════════════
def get_json(url, params, timeout=20):
    r = requests.get(url, params=params, timeout=timeout,
                     headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.json()

def build_lookup(data):
    if not data or "hourly" not in data: return {}
    return {t: i for i,t in enumerate(data["hourly"].get("time",[]))}

def gv(data, lookup, key, ts, default=0.0):
    if not data or not lookup: return default
    idx = lookup.get(ts)
    if idx is None: return default
    arr = data["hourly"].get(key,[])
    if idx < len(arr) and arr[idx] is not None:
        try: return float(arr[idx])
        except: return default
    return default

# ══════════════════════════════════════════════════════════════
# 6. API CALLS
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=86400, show_spinner=False)
def analyze_coast(lat, lon):
    pts = [destination_point(lat, lon, b, 3.0) for b in range(0,360,30)]
    lats_s = ",".join(str(round(p[0],4)) for p in pts)
    lons_s = ",".join(str(round(p[1],4)) for p in pts)
    try:
        data = get_json("https://api.open-meteo.com/v1/elevation",
                        {"latitude":lats_s,"longitude":lons_s}, 12)
        elevs = data.get("elevation",[])
    except requests.HTTPError as e:
        code = e.response.status_code if e.response else 0
        return None, "rate_limit" if code==429 else f"elev_{code}"
    except Exception as e:
        return None, f"elev:{e}"

    if len(elevs) != len(pts): return None, "elev_incomplete"
    sea_b = [b for b,e in zip(range(0,360,30), elevs) if e is not None and e <= 0.5]
    if not sea_b: return None, "inland"

    sn = circular_mean(sea_b)
    exp = round(len(sea_b)/len(pts), 3)

    if len(sea_b) >= 2:
        avg_s = safe_avg([math.sin(math.radians(b)) for b in sea_b])
        avg_c = safe_avg([math.cos(math.radians(b)) for b in sea_b])
        R_bar = min(math.sqrt(avg_s**2+avg_c**2), 0.9999)
        bay = round(max(0,1-math.degrees(math.sqrt(-2*math.log(R_bar)))/90), 3)
    else: bay = 0.5

    if exp < 0.05:   ct = "بحيرة/سبخة"
    elif exp > 0.65: ct = "ساحل مفتوح"
    elif bay > 0.55: ct = "خليج شبه مغلق"
    else:            ct = "ساحل عادي"

    return {"shoreline_normal":round(sn,1),"coast_exposure":exp,
            "bay_factor":bay,"coast_type":ct}, None

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_marine(lat, lon):
    try:
        data = get_json("https://marine-api.open-meteo.com/v1/marine",{
            "latitude":lat,"longitude":lon,
            "hourly":"wave_height,wave_direction,wave_period,wind_wave_height,wind_wave_direction,wind_wave_period,swell_wave_height,swell_wave_direction,swell_wave_period,sea_surface_temperature",
            "past_days":2,"forecast_days":3,"timezone":"auto"
        }, 20)
        return (data,None) if "hourly" in data else (None,"marine_no_hourly")
    except requests.HTTPError as e:
        c = e.response.status_code if e.response else 0
        return None, "rate_limit" if c==429 else f"marine_{c}"
    except Exception as e: return None, str(e)

@st.cache_data(ttl=3600, show_spinner=False)
def fetch_weather(lat, lon):
    try:
        data = get_json("https://api.open-meteo.com/v1/forecast",{
            "latitude":lat,"longitude":lon,
            "hourly":"wind_speed_10m,wind_direction_10m,wind_gusts_10m,precipitation,visibility",
            "past_days":2,"forecast_days":3,"timezone":"auto"
        }, 20)
        return (data,None) if "hourly" in data else (None,"weather_no_hourly")
    except requests.HTTPError as e:
        c = e.response.status_code if e.response else 0
        return None, "rate_limit" if c==429 else f"weather_{c}"
    except Exception as e: return None, str(e)

@st.cache_data(ttl=86400, show_spinner=False)
def fetch_location_name(lat, lon):
    try:
        data = get_json("https://nominatim.openstreetmap.org/reverse",
                        {"lat":lat,"lon":lon,"format":"json",
                         "accept-language":"ar","zoom":14}, 8)
        a = data.get("address",{})
        return (a.get("beach") or a.get("hamlet") or a.get("village") or
                a.get("suburb") or a.get("town") or a.get("city") or
                a.get("state") or "ساحل تونسي")
    except: return "ساحل تونسي"

# ══════════════════════════════════════════════════════════════
# 7. PHYSICS ENGINE
# ══════════════════════════════════════════════════════════════
def classify_wind(wd_from, sn, ws_eff):
    diff = angle_diff_180(wd_from, sn)
    if diff <= 45:
        lbl = "وش 🟢"
        bon = +1.5 if 10<=ws_eff<=25 else (+0.5 if ws_eff<10 else -0.5)
    elif diff >= 135:
        lbl = "بر 🔵"
        bon = +1.0 if ws_eff<=15 else (+0.2 if ws_eff<=25 else -1.2)
    elif diff <= 90:
        lbl = "جانبي-وش 🟡"
        bon = -0.5 if ws_eff<=20 else -1.5
    else:
        lbl = "جانبي-بر 🟠"
        bon = -0.8 if ws_eff<=20 else -2.0
    return lbl, round(diff,1), round(bon,2)

def past_48h(marine, weather, tgt):
    times = weather["hourly"].get("time",[])
    lk = build_lookup(marine)
    ts0 = datetime.combine(tgt, datetime.min.time())
    t48 = ts0 - timedelta(hours=48)

    wwh,wwp,swh,swp = [],[],[],[]
    for ts in times:
        dt = parse_dt(ts)
        if not (t48 <= dt < ts0): continue
        v = gv(marine,lk,"wind_wave_height",ts)
        if v>0.05: wwh.append(v); wwp.append(gv(marine,lk,"wind_wave_period",ts))
        v2 = gv(marine,lk,"swell_wave_height",ts)
        if v2>0.05: swh.append(v2); swp.append(gv(marine,lk,"swell_wave_period",ts))

    a_wwh = safe_avg(wwh); a_wwp = safe_avg(wwp)
    return {
        "avg_wwh":round(a_wwh,2),"avg_wwp":round(a_wwp,1),
        "avg_swh":round(safe_avg(swh),2),"avg_swp":round(safe_avg(swp),1),
        "is_dirty":(a_wwh>1.2) and (a_wwp<6.5)
    }

def compute_hourly(marine, weather, coast, tgt, past_data):
    sn = coast["shoreline_normal"]; bay = coast["bay_factor"]
    exp = coast["coast_exposure"]
    lk = build_lookup(marine)
    times = weather["hourly"].get("time",[])
    wsp = weather["hourly"].get("wind_speed_10m",[])
    wdr = weather["hourly"].get("wind_direction_10m",[])
    gst = weather["hourly"].get("wind_gusts_10m",[])
    prp = weather["hourly"].get("precipitation",[])
    vis = weather["hourly"].get("visibility",[])
    moon_b = max(0,(moon_phase_factor(tgt)-0.55)*1.2)
    rows=[]; flags=set()

    def _w(arr,i,d=0.0):
        if i<len(arr) and arr[i] is not None:
            try: return float(arr[i])
            except: return d
        return d

    for i,ts in enumerate(times):
        dt = parse_dt(ts)
        if dt.date()!=tgt: continue

        ws=_w(wsp,i); wd=_w(wdr,i); gu=_w(gst,i); rn=_w(prp,i)
        vi=_w(vis,i,24140) or 24140
        ws_eff = ws + 0.35*max(0,gu-ws)

        wh=gv(marine,lk,"wave_height",ts)
        w_dir=gv(marine,lk,"wave_direction",ts)
        wp=gv(marine,lk,"wave_period",ts)
        wwh=gv(marine,lk,"wind_wave_height",ts)
        wwp=gv(marine,lk,"wind_wave_period",ts)
        sw_h=gv(marine,lk,"swell_wave_height",ts)
        sw_d=gv(marine,lk,"swell_wave_direction",ts)
        sw_p=gv(marine,lk,"swell_wave_period",ts)
        sst=gv(marine,lk,"sea_surface_temperature",ts,18)

        wh_e = wh*(1-bay*0.4); wwh_e=wwh*(1-bay*0.5); swh_e=sw_h*(1-bay*0.3)
        total_h = max(wh_e, wwh_e+swh_e)

        wlbl,wsa,wbon = classify_wind(wd,sn,ws_eff)
        wi = angle_diff_180(w_dir,sn)
        swi = angle_diff_180(sw_d,sn)

        if 10<wi<=80 and total_h>0.05:
            ir=math.radians(wi)
            vls=1.17*math.sqrt(9.81*total_h)*math.sin(ir)*math.cos(ir)
        else: vls=0.0
        vk = max(0,(vls+ws_eff*0.015)*3.6)

        if vk>1.8:   lead="سبايك 140غ"
        elif vk>1.0: lead="هرمي 120غ"
        else:        lead="زيتوني 100غ"

        cl_sw = past_data["is_dirty"] and sw_p>=8 and swh_e>=0.35 and swi<45
        if cl_sw:                  deb="Swell ينظف 🟢"
        elif past_data["is_dirty"]:deb="مدرر 🔴"
        else:                      deb="نظيف 🟢"

        ecu = "نعم ✅" if ("وش" in wlbl and 0.4<=total_h<=1.5 and wi<55 and ws_eff>=10) else "لا ❌"

        if total_h>1.2 and wp>8 and 20<=wi<=60: rip="عالي ⚠️"
        elif total_h>0.9 and wp>6:              rip="متوسط"
        else:                                    rip="منخفض"

        sc = 10.0 + wbon + moon_b
        if total_h<0.25: sc-=3
        elif total_h>2.2: sc-=2
        if vk>2.2:   sc-=3.5; flags.add("تيار جانبي قوي")
        elif vk>1.2: sc-=1.5
        if ws_eff>55: sc-=5; flags.add("ريح عنيفة")
        elif ws_eff>40: sc-=3
        elif ws_eff>30: sc-=1.5
        if rn>3: sc-=1.5
        elif rn>1: sc-=0.5
        if vi<1500: sc-=2
        elif vi<3000: sc-=1
        if sst<15: sc-=1.5
        elif 19<=sst<=24: sc+=0.4
        if ecu=="نعم ✅": sc+=1.2
        if cl_sw: sc+=1.4
        elif past_data["is_dirty"]: sc-=2; flags.add("بحر مدرر")
        if exp>0.75 and total_h>1.6: sc-=1
        sc = round(max(0,min(10,sc)),1)

        rows.append({
            "time":ts[-5:],"hour":dt.hour,"score":sc,
            "wind_kmh":round(ws,1),"gust_kmh":round(gu,1),"ws_eff":round(ws_eff,1),
            "wind_dir":round(wd,0),"wind_type":wlbl,"wind_shore_a":wsa,
            "wave_h":round(wh_e,2),"wave_p":round(wp,1),"wave_impact":round(wi,1),
            "ww_h":round(wwh_e,2),"ww_p":round(wwp,1),
            "sw_h":round(swh_e,2),"sw_p":round(sw_p,1),"sw_impact":round(swi,1),
            "longshore_kmh":round(vk,2),"lead":lead,"rip":rip,
            "debris":deb,"ecume":ecu,"sst_c":round(sst,1),
            "rain_mm":round(rn,1),"vis_km":round(vi/1000,1),
        })
    return rows, sorted(flags)

def weighted_score(rows):
    prime = set(range(4,9))|set(range(17,24))
    tw=ts=0.0
    for r in rows:
        w = 2.5 if r["hour"] in prime else 1.0
        tw+=w; ts+=r["score"]*w
    return round(ts/tw,2) if tw else 0.0

def build_summary(rows, coast, past_data, flags, tgt):
    ws = weighted_score(rows)
    best = max(rows, key=lambda x:x["score"])
    return {
        "weighted_score":ws,
        "simple_score":round(safe_avg([r["score"] for r in rows]),2),
        "best_hour":best,
        "avg_longshore":round(safe_avg([r["longshore_kmh"] for r in rows]),2),
        "avg_wind":round(safe_avg([r["ws_eff"] for r in rows]),1),
        "ecume_hours":sum(1 for r in rows if "نعم" in r["ecume"]),
        "confidence":max(35,92-14*len(flags)),
        "coast":coast,"past":past_data,"red_flags":flags,
        "rows":rows,"moon":moon_phase_factor(tgt),
        "target_date":str(tgt),
    }

# ══════════════════════════════════════════════════════════════
# 8. SCOUT
# ══════════════════════════════════════════════════════════════
def _quick_score(spot, tgt):
    coast, err = analyze_coast(spot["lat"],spot["lon"])
    if err or not coast or coast["coast_type"]=="بحيرة/سبخة": return None
    marine,e1 = fetch_marine(spot["lat"],spot["lon"])
    weather,e2 = fetch_weather(spot["lat"],spot["lon"])
    if e1 or e2 or not marine or not weather: return None
    lk=build_lookup(marine); sn=coast["shoreline_normal"]; bay=coast["bay_factor"]
    scores=[]
    for i,ts in enumerate(weather["hourly"].get("time",[])):
        if parse_dt(ts).date()!=tgt: continue
        def _w(arr,d=0.0):
            if i<len(arr) and arr[i] is not None:
                try: return float(arr[i])
                except: return d
            return d
        ws=_w(weather["hourly"].get("wind_speed_10m",[]))
        gu=_w(weather["hourly"].get("wind_gusts_10m",[]))
        wd=_w(weather["hourly"].get("wind_direction_10m",[]))
        wh=gv(marine,lk,"wave_height",ts)*(1-bay*0.4)
        w_d=gv(marine,lk,"wave_direction",ts)
        sw_p=gv(marine,lk,"swell_wave_period",ts)
        sst=gv(marine,lk,"sea_surface_temperature",ts,18)
        ws_e=ws+0.35*max(0,gu-ws); dw=angle_diff_180(wd,sn); dwv=angle_diff_180(w_d,sn)
        s=10.0
        s+=1.0 if dw<=45 else (0.4 if dw>=135 else -1.0)
        s-=3.0 if wh<0.2 else (1.8 if wh>2 else 0)
        s+=0.3 if 10<dwv<=80 else (-0.8 if dwv>90 else 0)
        s-=4 if ws_e>45 else (2 if ws_e>35 else 0)
        s+=0.4 if sw_p>=8 else 0
        s-=1.3 if sst<15 else (-0.3 if 19<=sst<=24 else 0)
        s=max(0,min(10,s))
        hr=parse_dt(ts).hour
        w=2.5 if hr in set(range(4,9))|set(range(17,24)) else 1.0
        scores.append((s,w))
    if not scores: return None
    return round(sum(s*w for s,w in scores)/sum(w for _,w in scores),2)

@st.cache_data(ttl=3600, show_spinner=False)
def scan_tunisia(tgt_str):
    tgt = date.fromisoformat(tgt_str)
    results=[]
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(_quick_score,s,tgt):s for s in SPOTS}
        for f in as_completed(futs):
            sp = futs[f]
            sc = f.result()
            if sc is not None:
                results.append({"name":sp["name"],"region":sp["region"],
                                "lat":sp["lat"],"lon":sp["lon"],"score":sc})
    results.sort(key=lambda x:x["score"], reverse=True)
    return results

# ══════════════════════════════════════════════════════════════
# 9. REPORTS
# ══════════════════════════════════════════════════════════════
def det_report(loc, summary, alts, tgt):
    sc=summary["weighted_score"]; b=summary["best_hour"]; p=summary["past"]
    co=summary["confidence"]
    alt = alts[0] if alts else None

    if alt and alt["score"]>sc:
        cmp = f"المقارنة التقنية تمنح الأفضلية لـ **{alt['name']}** ({alt['score']}/10) مقارنة بـ {loc} ({sc}/10)."
    else:
        cmp = f"التحليل يعطي الأفضلية لـ **{loc}** ({sc}/10) على البدائل المتاحة."

    wi=b["wave_impact"]
    wp = "بزاوية مستقيمة" if wi<=20 else ("بزاوية مائلة" if wi<=55 else "بزاوية جانبية مزعجة")
    dp = "Swell ينظف" if "ينظف" in b["debris"] else ("البحر مدرر" if "مدرر" in b["debris"] else "البحر نظيف")
    fp = "حزام الرغوة متوقع — يقرّب السمك" if "نعم" in b["ecume"] else "رغوة ضعيفة"

    if sc>=7: vd="✅ GO — ممتاز"; tc="اذهب — رحلة المساء/الليل مثالية"
    elif sc>=5: vd="🟡 GO بحذر"; tc="اذهب لكن انتبه للتيار"
    else: vd="🔴 NO-GO"; tc="لا تذهب لهذا السبوت — البدائل أفضل"

    bait = "دود + ثوم" if ("ينظف" in b["debris"] or "نعم" in b["ecume"]) else "سردين/طعوم ثابتة"
    fl = " | ".join(summary["red_flags"]) if summary["red_flags"] else "لا توجد"

    return f"""
تحديثات البيانات الحية ليوم {fmt_date_ar(tgt)}، {cmp}

## 1. زاوية الموج والتيار الجانبي
- الموج يدخل {wp} — الزاوية: **{wi}°**
- نوع الريح: **{b['wind_type']}** — سرعة فعلية: **{b['ws_eff']} كم/س**
- التيار الجانبي: **{b['longshore_kmh']} كم/س** → **{b['lead']}**

## 2. الأعشاب والفساد
- متوسط موج الرياح 48س: **{p['avg_wwh']}م / {p['avg_wwp']}ث**
- الحالة السابقة: **{"مدرر" if p["is_dirty"] else "نظيف"}**
- {dp}. تردد Swell: **{b['sw_p']}ث**

## 3. نشاط السمك
- ارتفاع الموج: **{b['wave_h']}م** | Écume: **{b['ecume']}**
- {fp}. حرارة البحر: **{b['sst_c']}°C**

---
## 🎯 القرار ({sc}/10 | ثقة {co}%)
**{vd}** — {tc}
▸ الرصاص: **{b['lead']}** | ▸ أفضل ساعة: **{b['time']}**
▸ الطعم: **{bait}** | ▸ Rip: **{b['rip']}** | ▸ تحذيرات: {fl}
""".strip()

@st.cache_data(ttl=1800, show_spinner=False)
def gemini_report(payload_json, det_text, tgt_str):
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key: return None, "GEMINI_API_KEY غير موجود"
    try:
        client = genai.Client(api_key=api_key)
        prompt = f"""أنت خبير صيد تونسي محترف. شرح القرار الحسابي فقط.
التاريخ: {tgt_str}
البيانات الرقمية:
{payload_json}
التقرير الحتمي:
{det_text}
القواعد: لا تخترع أرقاماً. القرار يبقى مطابقاً للـ weighted_score.
اتبع: تحديثات البيانات الحية ليوم... / 1.زاوية الموج / 2.الأعشاب / 3.نشاط السمك / القرار والتكتيك.
اكتب بالعربية التقنية التونسية."""
        resp = client.models.generate_content(
            model=GEMINI_MODEL, contents=prompt,
            config=types.GenerateContentConfig(
                temperature=0.05, top_p=0.15, max_output_tokens=2000))
        return (resp.text or "").strip(), None
    except Exception as e: return None, f"Gemini: {e}"

# ══════════════════════════════════════════════════════════════
# 10. UI — الخريطة المستقرة
# ══════════════════════════════════════════════════════════════
st.title("🎣 مستشار الصيد الفيزيائي | تونس v10.6")
st.markdown("**المحرك الحسابي = القرار | Gemini = الشرح فقط**")

# ── اختيار اليوم ──
c1,c2,c3 = st.columns(3)
with c1:
    if st.button("🔵 اليوم", use_container_width=True):
        st.session_state.day_offset=0; st.session_state.deep_result=None; st.rerun()
with c2:
    if st.button("🟢 غداً", use_container_width=True):
        st.session_state.day_offset=1; st.session_state.deep_result=None; st.rerun()
with c3:
    if st.button("🟡 بعد غد", use_container_width=True):
        st.session_state.day_offset=2; st.session_state.deep_result=None; st.rerun()

tgt = target_date_from_offset(st.session_state.day_offset)
st.info(f"📅 **{fmt_date_ar(tgt)}**")
st.divider()

col_map, col_scout = st.columns([2,1])

# ── Scout ──
with col_scout:
    st.subheader("🏆 ترتيب السبوتات")
    with st.spinner("يفحص الساحل التونسي..."):
        scout = scan_tunisia(str(tgt))
        st.session_state.scan_results = scout

    for i,s in enumerate(scout[:5],1):
        clr = "#00ff00" if s["score"]>=7 else "#ffff00" if s["score"]>=5 else "#ff8c00"
        st.markdown(f"""<div class="top-spot">
          <b>{i}. {s['name']}</b> — {s['region']}<br>
          🎯 <span style="color:{clr};font-weight:bold">{s['score']}/10</span>
        </div>""", unsafe_allow_html=True)
        if st.button(f"⚓ {s['name']}", key=f"go_{i}", use_container_width=True):
            st.session_state.lat=s["lat"]; st.session_state.lon=s["lon"]
            st.session_state.deep_result=None; st.rerun()

# ── خريطة مستقرة بدون حلقة لا نهائية ──
with col_map:
    st.subheader("🗺️ اختر السبوت")

    # 3 طرق مستقرة لاختيار الموقع
    tab1, tab2, tab3 = st.tabs(["📋 من القائمة", "🖱️ من الخريطة", "📝 إدخال يدوي"])

    with tab1:
        idx = st.selectbox(
            "اختر سبوت مشهور:",
            range(len(SPOTS)),
            format_func=lambda i: SPOT_NAMES[i],
            index=next((i for i,s in enumerate(SPOTS)
                        if s["lat"]==st.session_state.lat
                        and s["lon"]==st.session_state.lon), 0)
        )
        if st.button("✅ تأكيد هذا السبوت", key="confirm_list", use_container_width=True):
            st.session_state.lat = SPOTS[idx]["lat"]
            st.session_state.lon = SPOTS[idx]["lon"]
            st.session_state.deep_result = None
            st.rerun()

    with tab2:
        st.caption("🖱️ انقر على الخريطة لتحديد الموقع")
        m = folium.Map(
            location=[st.session_state.lat, st.session_state.lon],
            zoom_start=8,
            tiles="CartoDB dark_matter",
        )
        # الماركر الحالي
        folium.Marker(
            [st.session_state.lat, st.session_state.lon],
            icon=folium.Icon(color="red", icon="anchor", prefix="fa"),
            tooltip="📍 الموقع الحالي"
        ).add_to(m)
        # سبوتات Scout
        for s in scout[:8]:
            clr = "green" if s["score"]>=7 else "orange" if s["score"]>=5 else "red"
            folium.CircleMarker(
                [s["lat"],s["lon"]], radius=5,
                color=clr, fill=True, fill_opacity=0.7,
                tooltip=f"{s['name']} {s['score']}/10"
            ).add_to(m)

        map_data = st_folium(
            m, width=None, height=350,
            returned_objects=["last_clicked"],
            key="stable_map"
        )

        if map_data and map_data.get("last_clicked"):
            cl = map_data["last_clicked"]
            new_lat = round(cl["lat"],5)
            new_lon = round(cl["lng"],5)
            if (abs(new_lat-st.session_state.lat)>0.001 or
                abs(new_lon-st.session_state.lon)>0.001):
                st.session_state.lat = new_lat
                st.session_state.lon = new_lon
                st.session_state.deep_result = None
                st.rerun()

    with tab3:
        in_lat = st.number_input("Latitude", value=st.session_state.lat,
                                  format="%.5f", step=0.01)
        in_lon = st.number_input("Longitude", value=st.session_state.lon,
                                  format="%.5f", step=0.01)
        if st.button("✅ تأكيد الإحداثيات", key="confirm_manual", use_container_width=True):
            st.session_state.lat = round(in_lat,5)
            st.session_state.lon = round(in_lon,5)
            st.session_state.deep_result = None
            st.rerun()

    st.markdown(f"""<div class="spot-card">
      ⚓ <b>الموقع الحالي:</b> {st.session_state.lat:.5f}, {st.session_state.lon:.5f}
    </div>""", unsafe_allow_html=True)

st.divider()

# ══════════════════════════════════════════════════════════════
# 11. DEEP SCAN
# ══════════════════════════════════════════════════════════════
if st.button("🔬 Deep Scan — تحليل فيزيائي عميق", type="primary", use_container_width=True):

    with st.spinner("🧭 تحليل الساحل..."):
        coast_info, ce = analyze_coast(st.session_state.lat, st.session_state.lon)
    if ce=="rate_limit":
        st.error("⏳ Rate limit — حاول بعد دقيقة."); st.stop()
    if ce=="inland":
        st.error("📍 موقع بري — اختر نقطة على الشاطئ."); st.stop()
    if ce:
        st.error(f"❌ {ce}"); st.stop()
    if coast_info["coast_type"]=="بحيرة/سبخة":
        st.error("⛔ بحيرة/سبخة — اختر ساحلاً بحرياً."); st.stop()

    with st.spinner("📡 جلب بيانات البحر والطقس..."):
        marine_d, me = fetch_marine(st.session_state.lat, st.session_state.lon)
        weather_d, we = fetch_weather(st.session_state.lat, st.session_state.lon)
    if "rate_limit" in (me or "",we or ""):
        st.error("⏳ Rate limit."); st.stop()
    if me or we or not marine_d or not weather_d:
        st.error(f"❌ {me or we}"); st.stop()

    with st.spinner("📊 تحليل 48 ساعة سابقة..."):
        past_data = past_48h(marine_d, weather_d, tgt)

    with st.spinner("⚙️ الحسابات الفيزيائية..."):
        rows, flags = compute_hourly(marine_d, weather_d, coast_info, tgt, past_data)
    if not rows:
        st.error("لا توجد بيانات لهذا اليوم."); st.stop()

    summary = build_summary(rows, coast_info, past_data, flags, tgt)
    loc = fetch_location_name(st.session_state.lat, st.session_state.lon)

    cur_sc = summary["weighted_score"]
    alts = [s for s in scout
            if haversine_km(st.session_state.lat,st.session_state.lon,
                            s["lat"],s["lon"])>1 and s["score"]>cur_sc]

    det = det_report(loc, summary, alts, tgt)
    payload = json.dumps({
        "location":loc,"weighted_score":summary["weighted_score"],
        "simple_score":summary["simple_score"],"confidence":summary["confidence"],
        "red_flags":summary["red_flags"],"coast":summary["coast"],
        "past_48h":summary["past"],"best_hour":summary["best_hour"],
        "avg_longshore":summary["avg_longshore"],"avg_wind":summary["avg_wind"],
        "ecume_hours":summary["ecume_hours"],"moon":summary["moon"],
        "alternatives":alts[:3],
    }, ensure_ascii=False, indent=2)

    with st.spinner("🧠 Gemini يصوغ التقرير..."):
        ai_txt, ai_err = gemini_report(payload, det, str(tgt))

    st.session_state.deep_result = {
        "loc":loc,"summary":summary,"det":det,
        "ai_txt":ai_txt,"ai_err":ai_err,
        "alts":alts,"payload":payload
    }
    st.rerun()

# ══════════════════════════════════════════════════════════════
# 12. RESULTS
# ══════════════════════════════════════════════════════════════
if st.session_state.deep_result:
    R = st.session_state.deep_result
    S = R["summary"]; B = S["best_hour"]
    sc = S["weighted_score"]; co = S["confidence"]

    # القرار
    st.subheader("⚖️ القرار النهائي")
    if sc>=7 and co>=70 and not S["red_flags"]:
        st.markdown(f"""<div class="go-box"><h2 style="color:#0f0;text-align:center">
        ✅ GO — ممتاز</h2><p style="text-align:center">{sc}/10 | ثقة {co}%</p>
        </div>""", unsafe_allow_html=True)
    elif sc>=5:
        st.markdown(f"""<div class="warn-box"><h2 style="color:#ffd166;text-align:center">
        🟡 GO بحذر</h2><p style="text-align:center">{sc}/10 | ثقة {co}%</p>
        </div>""", unsafe_allow_html=True)
    else:
        st.markdown(f"""<div class="nogo-box"><h2 style="color:#f44;text-align:center">
        🔴 NO-GO</h2><p style="text-align:center">{sc}/10 | ثقة {co}%</p>
        </div>""", unsafe_allow_html=True)

    if S["red_flags"]:
        st.error("🚩 " + " | ".join(S["red_flags"]))

    # مؤشرات
    m1,m2,m3,m4,m5 = st.columns(5)
    m1.metric("⭐ أفضل ساعة", B["time"])
    m2.metric("🌊 تيار", f"{S['avg_longshore']} كم/س")
    m3.metric("💨 Écume", f"{S['ecume_hours']}h")
    m4.metric("🌙 القمر", f"{int(S['moon']*100)}%")
    m5.metric("⚖️ رصاص", B["lead"])

    st.divider()

    # هوية السبوت
    st.markdown(f"""<div class="spot-card"><b>📍 {R['loc']}</b><br>
    🧭 {S['coast']['shoreline_normal']}° | 🏖️ {S['coast']['coast_type']} |
    📊 انكشاف {int(S['coast']['coast_exposure']*100)}% |
    🌊 خليج {int(S['coast']['bay_factor']*100)}%</div>""", unsafe_allow_html=True)

    # إرث 48 ساعة
    st.subheader("📊 إرث 48 ساعة")
    q1,q2,q3,q4,q5 = st.columns(5)
    q1.metric("موج رياح", f"{S['past']['avg_wwh']}م")
    q2.metric("تردده", f"{S['past']['avg_wwp']}ث")
    q3.metric("Swell", f"{S['past']['avg_swh']}م")
    q4.metric("تردده", f"{S['past']['avg_swp']}ث")
    q5.metric("الحالة", "🔴 مدرر" if S["past"]["is_dirty"] else "🟢 نظيف")

    st.divider()

    # التقرير الحتمي
    st.subheader("🧮 التقرير الحتمي (المحرك)")
    st.markdown(R["det"])

    st.divider()

    # Gemini
    st.subheader("🧠 تقرير Gemini")
    if R["ai_err"]:
        st.warning(f"⚠️ {R['ai_err']}")
    elif R["ai_txt"]:
        st.markdown(R["ai_txt"])

    st.divider()

    # الجدول
    st.subheader("📊 ساعة بساعة")
    df = pd.DataFrame(S["rows"])[[
        "time","score","wind_type","wind_kmh","gust_kmh","ws_eff",
        "wave_h","wave_p","wave_impact","ww_h","sw_h","sw_p","sw_impact",
        "longshore_kmh","lead","rip","debris","ecume","sst_c","rain_mm","vis_km"
    ]].copy()
    df.columns = [
        "الوقت","سكور","ريح","كم/س","هبات","فعلية",
        "موج","تردد","زاوية","م.ريح","Sw","ت.Sw","ز.Sw",
        "تيار","رصاص","Rip","أعشاب","Écu","°C","مطر","رؤية"
    ]
    def cs(v):
        if v>=7: return "background:#0a3d0a;color:#0f0"
        if v>=5: return "background:#3d3d0a;color:#ff0"
        if v>=4: return "background:#3d2e0a;color:#fa0"
        return "background:#3d0a0a;color:#f44"

    st.dataframe(
        df.style.applymap(cs, subset=["سكور"]),
        use_container_width=True, hide_index=True, height=400
    )

    # بدائل
    if R["alts"]:
        st.divider()
        st.subheader("💡 بدائل أقوى")
        for alt in R["alts"][:3]:
            d = haversine_km(st.session_state.lat,st.session_state.lon,alt["lat"],alt["lon"])
            df2 = round(alt["score"]-sc,1)
            st.markdown(f"""<div class="spot-card"><b>{alt['name']}</b> — {alt['region']}
            | 🎯 {alt['score']}/10 <span style="color:#0f0">(+{df2})</span>
            | 📏 {d}كم</div>""", unsafe_allow_html=True)
            if st.button(f"⚓ {alt['name']}", key=f"a_{alt['name']}", use_container_width=True):
                st.session_state.lat=alt["lat"]; st.session_state.lon=alt["lon"]
                st.session_state.deep_result=None; st.rerun()

    with st.expander("🔧 Payload → Gemini"):
        st.code(R["payload"], language="json")

st.caption("© Tunisia Fishing Advisor v10.6 | Physics First — AI Explains")
