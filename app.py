import streamlit as st
import requests
import google.generativeai as genai
import folium
from streamlit_folium import st_folium
import os

# =====================================================================
# 1. إعدادات الخدمات وحماية المفاتيح السرية (Environment Variables)
# =====================================================================
# يسحب المفتاح بأمان من إعدادات سيرفر Render دون كشفه في الكود
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "YOUR_FALLBACK_KEY_IF_LOCAL")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel('gemini-1.5-flash')

st.set_page_config(page_title="رادار ومستشار السورفكاست الحاسم", page_icon="⚓", layout="wide")

st.title("⚓ رادار ومحلل مصايد السورفكاست الاحترافي المطور")
st.write("🗺️ حدد السبوت بدقة على الخريطة لحساب **سكور الصيد الرياضي ساعة بساعة** وإصدار التقرير الفيزيائي الحاسم:")

if 'clicked_lat' not in st.session_state:
    st.session_state.clicked_lat = 36.4000
    st.session_state.clicked_lon = 10.6000

# بناء الخريطة التفاعلية
m = folium.Map(location=[st.session_state.clicked_lat, st.session_state.clicked_lon], zoom_start=10)
folium.LatLngPopup().add_to(m)
folium.Marker([st.session_state.clicked_lat, st.session_state.clicked_lon], icon=folium.Icon(color="blue", icon="anchor", prefix="fa")).add_to(m)

map_data = st_folium(m, height=350, width="100%")
if map_data and map_data.get("last_clicked"):
    st.session_state.clicked_lat = map_data["last_clicked"]["lat"]
    st.session_state.clicked_lon = map_data["last_clicked"]["lng"]

lat, lon = st.session_state.clicked_lat, st.session_state.clicked_lon
st.info(f"📍 السبوت الحالي: خط العرض ({lat:.4f}) | خط الطول ({lon:.4f})")

# =====================================================================
# 2. دالة معالجة الداتا الرياضية ساعة بساعة (صفر هلوسة لغوية)
# =====================================================================
@st.cache_data(ttl=3600) # درع حماية المفتاح من الضغط العالي (Rate Limit)
def process_fishing_analysis(latitude, longitude):
    try:
        marine_url = f"https://open-meteo.com{latitude}&longitude={longitude}&hourly=wave_height,wave_direction,wave_period&past_days=2&forecast_days=3&timezone=auto"
        weather_url = f"https://open-meteo.com{latitude}&longitude={longitude}&hourly=wind_speed_10m,wind_direction_10m&past_days=2&forecast_days=3&timezone=auto"
        
        marine_res = requests.get(marine_url).json()
        weather_res = requests.get(weather_url).json()
        
        # 1. فحص الـ 48 ساعة الماضية لمعرفة هل البحر "مدرر مخنوق" في الأصل أم لا
        past_wave_h = sum(marine_res['hourly']['wave_height'][:48]) / 48
        past_wave_p = sum(marine_res['hourly']['wave_period'][:48]) / 48
        sea_initially_dirty = past_wave_h > 1.2 and past_wave_p > 8.0

        # 2. الحساب الميكانيكي لكل ساعة لـ 24 ساعة القادمة (يوم غد الفعلي)
        hourly_scores = []
        
        for i in range(24):
            idx = 48 + i  # تخطي الـ 48 ساعة الماضية للوصول لبيانات الغد
            h_wave = marine_res['hourly']['wave_height'][idx]
            h_period = marine_res['hourly']['wave_period'][idx]
            h_wave_dir = marine_res['hourly']['wave_direction'][idx]
            h_wind_s = weather_res['hourly']['wind_speed_10m'][idx]
            h_wind_dir = weather_res['hourly']['wind_direction_10m'][idx]
            
            score = 10.0 # السكور الافتراضي المثالي لكل ساعة
            
            # أ) عامل البحر الميت (انعدام الحركة البيولوجية للأسماك)
            if h_wave < 0.3: 
                score -= 3.0
            
            # ب) عامل الأعشاب الطافية (Swell قوي وتردد طويل يقلع القاع)
            if (h_wave > 1.2 and h_period > 8.0) or sea_initially_dirty:
                score -= 4.5 
                
            # ج) تصحيح ثغرة الرياضيات الدائرية للزوايا (Angle Math Fix)
            angle_diff = abs(h_wind_dir - h_wave_dir)
            if angle_diff > 180:
                angle_diff = 360 - angle_diff
            
            # د) تيار الحمل الجانبي وعودة الرصاص للشط
            is_lateral = 30 < angle_diff < 150
            if h_wind_s > 22.0 and is_lateral:
                score -= 4.0 # الرصاص يلف ويرجع
            elif h_wind_s > 18.0:
                score -= 1.5
                
            # هـ) مكافأة حزام الرغوة البيضاء الغنية بالأكسجين (Écume)
            if 0.5 <= h_wave <= 1.2 and h_wind_s > 12.0 and not is_lateral:
                score += 1.5
                
            # و) مصفاة الموج الطبيعية (البحر ينظف نفسه ويقذف العشب على الرمل)
            if 4.0 <= h_period <= 7.0 and h_wave > 0.5 and not is_lateral and h_wind_s > 15.0:
                score += 2.0 
                
            hourly_scores.append({
                "الساعة": f"{i}:00",
                "السكور_النهائي": max(0.0, min(10.0, round(score, 1))),
                "ارتفاع_الموج_م": h_wave,
                "تردد_الموج_ثواني": h_period,
                "سرعة_الرياح_كم_س": h_wind_s,
                "الوضع_الحركي": "ريح وش مستقيمة" if not is_lateral else "تيار حمل جانبي"
            })
            
        return {"status": "success", "past_dirty": sea_initially_dirty, "hourly_data": hourly_scores}
    except Exception as e:
        # خط الدفاع الثاني في حال الضغط بالخطأ على اليابسة (تفعيل محاكاة محطة الأرصاد الساحلية العامة)
        try:
            fallback_url = f"https://open-meteo.com{latitude}&longitude={longitude}&hourly=wind_speed_10m,wind_direction_10m&past_days=2&forecast_days=1&timezone=auto"
            fallback_res = requests.get(fallback_url).json()
            return {
                "status": "fallback_land",
                "past_dirty": False,
                "hourly_data": [{"الساعة": f"{i}:00", "السكور_النهائي": 5.0, "سرعة_الرياح_كم_س": fallback_res['hourly']['wind_speed_10m'][48+i], "الوضع_الحركي": "قراءة يابسة مجاورة"} for i in range(24)],
                "message": "⚠️ تم رصد الضغط فوق اليابسة. تم الانتقال تلقائياً لمحاكاة الرياح الساحلية القريبة لحماية الموقع من التوقف."
            }
        except Exception as err:
            return {"status": "error", "message": str(err)}

# =====================================================================
# 3. إطلاق الحسابات وتوليد التقرير البشري المتزن عبر الـ AI
# =====================================================================
if st.button("🚀 إصدار القرار النهائي والحاسم للرحلة", type="primary", use_container_width=True):
    with st.spinner("⏳ نظام بايثون الرياضي يقوم بفحص الجداول الزمنية وترشيح الساعات الذهبية..."):
        result = process_fishing_analysis(lat, lon)
        
        if result["status"] == "error":
            st.error(f"❌ خطأ غير متوقع في الاتصال بالرادار: {result['message']}")
        else:
            if result["status"] == "fallback_land":
                st.warning(result["message"])
            
            # البرومبت الهجين المعزز لـ Gemini (الصياغة والترجمة والربط الجغرافي فقط)
            prompt = f"""
            You are an elite marine physicist and a master coastal angler specializing in Surfcasting. I have already calculated the exact mathematical Fishing Scores hour-by-hour using Python logic to eliminate AI hallucination. Your job is to translate these numbers into a highly professional, passionate, and realistic fishing report in ARABIC. Use North African fisherman terms ('بحر مدرر', 'تيار الحمل', 'ريح وش مستقيمة', 'مصفاة الموج', 'الرصاص يرجع للشط', 'البحر ينظف نفسه').

            Here is the factual data calculated by the system for the coordinates ({lat}, {lon}):
            - Was the sea rough/dirty in the past 48h? {result['past_dirty']}
            - Chronological Hourly Factored Scores for Tomorrow (24 hours data array): {str(result['hourly_data'])}

            Analyze the timeline and structure the Arabic markdown report exactly like this:
            بناءً على الحسابات الرياضية الصارمة لسكور الصيد ساعة بساعة ومقارنتها بالـ 48 ساعة الماضية، التقييم التقني يمنح القرار لـ [Deduce the exact coastal city or region name based on coordinates].
            إليك تحليل "الداتا" العلمي ساعة بساعة لتجنب الفساد وضمان الصيد الفعلي:

            ## 1. تحليل التغير الحركي وسكور الصيد ساعة بساعة
            * [Scan the hourly data provided. Clearly highlight the exact hours where the fishing score peaks (Golden Hours) and the hours where the score drops. Explain why according to wind speed, wave filter, and state if and when 'البحر ينظف نفسه'].

            ## 2. معادلة تيار الحمل وثبات الرصاص في الشط
            * [Explain to the angler during which specific hour blocks the lead will remain anchored in the foam belt and when it will roll back to shore due to the computed drift status].

            ## 3. النوافذ البيولوجية ونشاط السمك (Écume)
            * [Predict target fish activity like Seabream, Bass, or White Seabream based on the computed score peaks and white foam belt timeline].

            ------------------------------
            ## 🎯 القرار النهائي والحاسم لرحلتك (تأكيد أو إلغاء قطعي تفصيلي):
            [Provide a definitive, military-grade, and realistic decision for tomorrow's trip based on the scores. E.g., if scores are low for specific hours, issue a sharp warning to avoid that temporal window. Give a clear final judgment on whether to go or change the spot].

            * تكتيك الصيد المصيري: [Specify exact lead type and weight in grams, optimal casting distance, and the absolute tactical baits for the hours with the highest scores].
            """
            
            try:
                response = model.generate_content(prompt)
                st.markdown("---")
                st.subheader("📊 التقرير الفني النهائي المعتمد على سكور الصيد الفيزيائي:")
                st.markdown(response.text)
            except Exception as e:
                st.error(f"❌ حدث خطأ أثناء صياغة التقرير اللغوي: {e}")
