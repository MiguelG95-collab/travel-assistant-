
import math
import sqlite3
from datetime import datetime
from io import BytesIO

import pandas as pd
import requests
import streamlit as st
from timezonefinder import TimezoneFinder
from zoneinfo import ZoneInfo
import folium
from streamlit_folium import st_folium

APP_TITLE = "Asistente de Destinos para Agencia de Viajes"
USER_AGENT = "AgenciaViajesLocal/1.0 (uso interno; contacto: configurar en app.py)"
OVERPASS_URLS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
DB_PATH = "agencia_viajes.db"

st.set_page_config(page_title=APP_TITLE, page_icon="✈️", layout="wide")

st.markdown("""
<style>
.block-container {padding-top: 1.2rem; padding-bottom: 3rem;}
[data-testid="stMetricValue"] {font-size: 1.45rem;}
.small-note {color:#666; font-size:.85rem;}
</style>
""", unsafe_allow_html=True)


def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS favoritos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ciudad TEXT NOT NULL,
            pais TEXT,
            categoria TEXT NOT NULL,
            nombre TEXT NOT NULL,
            telefono TEXT,
            web TEXT,
            direccion TEXT,
            notas TEXT,
            creado_en TEXT NOT NULL
        )
    """)
    con.commit()
    con.close()


@st.cache_data(ttl=86400, show_spinner=False)
def geocode_city(query: str):
    url = "https://geocoding-api.open-meteo.com/v1/search"
    params = {"name": query, "count": 10, "language": "es", "format": "json"}
    r = requests.get(url, params=params, timeout=15, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.json().get("results", [])


@st.cache_data(ttl=1800, show_spinner=False)
def get_weather(lat: float, lon: float, timezone: str):
    url = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max",
        "timezone": timezone,
        "forecast_days": 5,
    }
    r = requests.get(url, params=params, timeout=15, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    return r.json()


def weather_label(code):
    labels = {
        0: "Despejado", 1: "Mayormente despejado", 2: "Parcialmente nublado",
        3: "Nublado", 45: "Niebla", 48: "Niebla con escarcha",
        51: "Llovizna ligera", 53: "Llovizna", 55: "Llovizna intensa",
        61: "Lluvia ligera", 63: "Lluvia", 65: "Lluvia intensa",
        71: "Nieve ligera", 73: "Nieve", 75: "Nieve intensa",
        80: "Chubascos ligeros", 81: "Chubascos", 82: "Chubascos fuertes",
        95: "Tormenta", 96: "Tormenta con granizo", 99: "Tormenta fuerte con granizo",
    }
    return labels.get(code, "Condición variable")


def overpass_query(lat, lon, radius):
    return f"""
    [out:json][timeout:35];
    (
      nwr(around:{radius},{lat},{lon})["tourism"~"hotel|hostel|guest_house|apartment|motel"];
      nwr(around:{radius},{lat},{lon})["amenity"~"restaurant|cafe|fast_food|bar"];
      nwr(around:{radius},{lat},{lon})["tourism"~"attraction|museum|gallery|viewpoint|zoo|theme_park"];
      nwr(around:{radius},{lat},{lon})["historic"];
      nwr(around:{radius},{lat},{lon})["public_transport"~"station|stop_position|platform"];
      nwr(around:{radius},{lat},{lon})["railway"~"station|subway_entrance|tram_stop"];
      nwr(around:{radius},{lat},{lon})["amenity"="bus_station"];
      nwr(around:{radius},{lat},{lon})["aeroway"="aerodrome"];
    );
    out center tags;
    """


@st.cache_data(ttl=3600, show_spinner=False)
def get_pois(lat: float, lon: float, radius: int):
    query = overpass_query(lat, lon, radius)
    last_error = None
    for endpoint in OVERPASS_URLS:
        try:
            r = requests.post(
                endpoint,
                data={"data": query},
                timeout=50,
                headers={"User-Agent": USER_AGENT},
            )
            r.raise_for_status()
            return r.json().get("elements", [])
        except Exception as exc:
            last_error = exc
    raise RuntimeError(f"No fue posible consultar OpenStreetMap: {last_error}")


def haversine(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp/2)**2 + math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(a))


def normalize_phone(tags):
    return tags.get("contact:phone") or tags.get("phone") or tags.get("contact:mobile") or ""


def normalize_web(tags):
    return tags.get("contact:website") or tags.get("website") or tags.get("url") or ""


def address(tags):
    parts = [
        tags.get("addr:street", ""),
        tags.get("addr:housenumber", ""),
        tags.get("addr:suburb", ""),
        tags.get("addr:city", ""),
    ]
    return " ".join([p for p in parts if p]).strip()


def parse_stars(tags):
    raw = tags.get("stars") or tags.get("hotel:stars") or ""
    try:
        return int(float(str(raw).replace(",", ".")))
    except Exception:
        return None


def osm_to_df(elements, center_lat, center_lon):
    rows = []
    for e in elements:
        tags = e.get("tags", {})
        lat = e.get("lat") or e.get("center", {}).get("lat")
        lon = e.get("lon") or e.get("center", {}).get("lon")
        if lat is None or lon is None:
            continue
        name = tags.get("name") or tags.get("brand") or "Sin nombre registrado"
        tourism = tags.get("tourism", "")
        amenity = tags.get("amenity", "")
        railway = tags.get("railway", "")
        public_transport = tags.get("public_transport", "")
        historic = tags.get("historic", "")
        aeroway = tags.get("aeroway", "")
        if tourism in {"hotel", "hostel", "guest_house", "apartment", "motel"}:
            category = "Hoteles"
            subtype = tourism
        elif amenity in {"restaurant", "cafe", "fast_food", "bar"}:
            category = "Restaurantes"
            subtype = amenity
        elif tourism in {"attraction", "museum", "gallery", "viewpoint", "zoo", "theme_park"} or historic:
            category = "Lugares para visitar"
            subtype = tourism or historic
        elif railway or public_transport or amenity == "bus_station" or aeroway == "aerodrome":
            category = "Transporte"
            subtype = railway or public_transport or amenity or aeroway
        else:
            continue
        rows.append({
            "Categoría": category,
            "Nombre": name,
            "Tipo": subtype.replace("_", " ").title(),
            "Estrellas": parse_stars(tags),
            "Cocina": tags.get("cuisine", "").replace(";", ", "),
            "Teléfono": normalize_phone(tags),
            "Sitio web": normalize_web(tags),
            "Dirección": address(tags),
            "Horario": tags.get("opening_hours", ""),
            "Distancia km": round(haversine(center_lat, center_lon, lat, lon), 2),
            "Latitud": lat,
            "Longitud": lon,
            "Mapa": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}",
        })
    if not rows:
        return pd.DataFrame(columns=[
            "Categoría","Nombre","Tipo","Estrellas","Cocina","Teléfono",
            "Sitio web","Dirección","Horario","Distancia km","Latitud","Longitud","Mapa"
        ])
    df = pd.DataFrame(rows)
    return df.drop_duplicates(subset=["Categoría", "Nombre", "Latitud", "Longitud"]).sort_values("Distancia km")


def show_table(df, columns):
    if df.empty:
        st.info("No se encontraron datos etiquetados en OpenStreetMap para esta zona.")
        return
    st.dataframe(
        df[columns],
        use_container_width=True,
        hide_index=True,
        column_config={
            "Sitio web": st.column_config.LinkColumn("Sitio web", display_text="Abrir"),
            "Mapa": st.column_config.LinkColumn("Mapa", display_text="Ver mapa"),
            "Distancia km": st.column_config.NumberColumn("Distancia km", format="%.2f"),
        },
    )


def save_favorite(city, country, category, row):
    con = sqlite3.connect(DB_PATH)
    con.execute(
        """INSERT INTO favoritos
        (ciudad,pais,categoria,nombre,telefono,web,direccion,notas,creado_en)
        VALUES (?,?,?,?,?,?,?,?,?)""",
        (
            city, country, category, row.get("Nombre",""), row.get("Teléfono",""),
            row.get("Sitio web",""), row.get("Dirección",""), "",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    con.commit()
    con.close()


def favorites_df():
    con = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM favoritos ORDER BY creado_en DESC", con)
    con.close()
    return df


def city_time(timezone):
    now = datetime.now(ZoneInfo(timezone))
    mexico = datetime.now(ZoneInfo("America/Mexico_City"))
    offset_hours = (now.utcoffset() - mexico.utcoffset()).total_seconds() / 3600
    sign = "+" if offset_hours >= 0 else ""
    return now, f"{sign}{offset_hours:g} h vs. Ciudad de México"


init_db()

st.title("✈️ Asistente de Destinos")
st.caption("Busca una ciudad y reúne hoteles, restaurantes, atractivos, transporte, clima, horarios y distancias en una sola pantalla.")

with st.sidebar:
    st.header("Configuración")
    radius_km = st.slider("Radio de búsqueda", 2, 20, 8, 1)
    max_rows = st.slider("Máximo de resultados por sección", 10, 100, 40, 10)
    st.markdown("---")
    st.subheader("Mis favoritos")
    fav = favorites_df()
    st.metric("Registros guardados", len(fav))
    if not fav.empty:
        st.download_button(
            "Descargar favoritos CSV",
            fav.to_csv(index=False).encode("utf-8-sig"),
            "favoritos_agencia.csv",
            "text/csv",
            use_container_width=True,
        )

query = st.text_input("Ciudad o destino", placeholder="Ejemplo: Madrid, España")
search = st.button("Buscar destino", type="primary", use_container_width=True)

if search and query.strip():
    with st.spinner("Buscando ciudad..."):
        try:
            matches = geocode_city(query.strip())
        except Exception as exc:
            st.error(f"No se pudo buscar la ciudad: {exc}")
            st.stop()
    if not matches:
        st.warning("No encontré esa ciudad. Prueba agregando el país, por ejemplo: Madrid, España.")
        st.stop()
    st.session_state["matches"] = matches

matches = st.session_state.get("matches", [])
if matches:
    options = {}
    for m in matches:
        label = ", ".join(filter(None, [
            m.get("name"), m.get("admin1"), m.get("country")
        ]))
        options[label] = m
    selected_label = st.selectbox("Selecciona la ubicación correcta", list(options.keys()))
    location = options[selected_label]
    lat, lon = float(location["latitude"]), float(location["longitude"])
    city = location.get("name", selected_label)
    country = location.get("country", "")
    timezone = location.get("timezone") or TimezoneFinder().timezone_at(lat=lat, lng=lon) or "UTC"

    now, difference = city_time(timezone)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Hora local", now.strftime("%H:%M"))
    c2.metric("Fecha local", now.strftime("%d/%m/%Y"))
    c3.metric("Diferencia horaria", difference)
    c4.metric("Zona horaria", timezone)

    try:
        weather = get_weather(lat, lon, timezone)
        current = weather.get("current", {})
        w1, w2, w3, w4 = st.columns(4)
        w1.metric("Temperatura", f'{current.get("temperature_2m", "—")} °C')
        w2.metric("Sensación", f'{current.get("apparent_temperature", "—")} °C')
        w3.metric("Clima", weather_label(current.get("weather_code")))
        w4.metric("Viento", f'{current.get("wind_speed_10m", "—")} km/h')
    except Exception as exc:
        st.warning(f"No se pudo cargar el clima: {exc}")

    with st.spinner("Consultando hoteles, restaurantes, atractivos y transporte..."):
        try:
            elements = get_pois(lat, lon, radius_km * 1000)
            df = osm_to_df(elements, lat, lon)
        except Exception as exc:
            st.error(str(exc))
            df = pd.DataFrame()

    st.caption(
        "Los resultados provienen de OpenStreetMap. Teléfonos, estrellas y horarios aparecen cuando el establecimiento los tiene registrados."
    )

    tab_hotels, tab_food, tab_sights, tab_transport, tab_map, tab_report, tab_saved = st.tabs([
        "🏨 Hoteles", "🍽️ Restaurantes", "📍 Qué visitar",
        "🚇 Transporte", "🗺️ Mapa", "📄 Exportar", "⭐ Guardados"
    ])

    with tab_hotels:
        hotels = df[df["Categoría"] == "Hoteles"].copy() if not df.empty else pd.DataFrame()
        if not hotels.empty:
            star_filter = st.multiselect(
                "Filtrar por estrellas",
                [3, 4, 5, "Sin clasificación"],
                default=[3, 4, 5, "Sin clasificación"],
            )
            mask = hotels["Estrellas"].apply(
                lambda x: ("Sin clasificación" in star_filter and pd.isna(x)) or
                          (not pd.isna(x) and int(x) in star_filter)
            )
            hotels = hotels[mask].head(max_rows)
        show_table(hotels, ["Nombre","Tipo","Estrellas","Teléfono","Sitio web","Dirección","Distancia km","Mapa"] if not hotels.empty else [])
        if not hotels.empty:
            chosen = st.selectbox("Guardar hotel en favoritos", hotels["Nombre"].tolist(), key="fav_hotel")
            if st.button("⭐ Guardar hotel", key="save_hotel"):
                row = hotels[hotels["Nombre"] == chosen].iloc[0].to_dict()
                save_favorite(city, country, "Hotel", row)
                st.success("Hotel guardado.")

    with tab_food:
        food = df[df["Categoría"] == "Restaurantes"].head(max_rows).copy() if not df.empty else pd.DataFrame()
        show_table(food, ["Nombre","Tipo","Cocina","Teléfono","Horario","Sitio web","Dirección","Distancia km","Mapa"] if not food.empty else [])
        if not food.empty:
            chosen = st.selectbox("Guardar restaurante en favoritos", food["Nombre"].tolist(), key="fav_food")
            if st.button("⭐ Guardar restaurante", key="save_food"):
                row = food[food["Nombre"] == chosen].iloc[0].to_dict()
                save_favorite(city, country, "Restaurante", row)
                st.success("Restaurante guardado.")

    with tab_sights:
        sights = df[df["Categoría"] == "Lugares para visitar"].head(max_rows).copy() if not df.empty else pd.DataFrame()
        show_table(sights, ["Nombre","Tipo","Dirección","Distancia km","Sitio web","Mapa"] if not sights.empty else [])
        if not sights.empty:
            chosen = st.selectbox("Guardar lugar en favoritos", sights["Nombre"].tolist(), key="fav_sight")
            if st.button("⭐ Guardar lugar", key="save_sight"):
                row = sights[sights["Nombre"] == chosen].iloc[0].to_dict()
                save_favorite(city, country, "Atracción", row)
                st.success("Lugar guardado.")

    with tab_transport:
        transport = df[df["Categoría"] == "Transporte"].head(max_rows).copy() if not df.empty else pd.DataFrame()
        show_table(transport, ["Nombre","Tipo","Dirección","Distancia km","Mapa"] if not transport.empty else [])
        st.markdown("#### Enlaces rápidos oficiales o de búsqueda")
        q_encoded = requests.utils.quote(f"transporte público oficial {city} {country}")
        airport_encoded = requests.utils.quote(f"aeropuerto {city} transporte al centro")
        st.markdown(
            f"- [Buscar transporte público oficial](https://www.google.com/search?q={q_encoded})\n"
            f"- [Buscar traslado aeropuerto–centro](https://www.google.com/search?q={airport_encoded})"
        )

    with tab_map:
        m = folium.Map(location=[lat, lon], zoom_start=13, control_scale=True)
        folium.Marker([lat, lon], tooltip=f"Centro de {city}", icon=folium.Icon(color="red")).add_to(m)
        if not df.empty:
            icon_map = {
                "Hoteles": ("bed", "blue"),
                "Restaurantes": ("cutlery", "green"),
                "Lugares para visitar": ("camera", "purple"),
                "Transporte": ("bus", "orange"),
            }
            for _, row in df.head(250).iterrows():
                icon, color = icon_map.get(row["Categoría"], ("info-sign", "gray"))
                popup = f"<b>{row['Nombre']}</b><br>{row['Categoría']}<br>{row['Distancia km']} km"
                folium.Marker(
                    [row["Latitud"], row["Longitud"]],
                    tooltip=row["Nombre"],
                    popup=popup,
                    icon=folium.Icon(color=color, icon=icon, prefix="glyphicon"),
                ).add_to(m)
        st_folium(m, width=None, height=620, use_container_width=True)

    with tab_report:
        st.subheader(f"Ficha rápida: {city}, {country}")
        export_df = df.drop(columns=["Latitud","Longitud"], errors="ignore").head(300) if not df.empty else pd.DataFrame()
        st.download_button(
            "Descargar resultados en CSV",
            export_df.to_csv(index=False).encode("utf-8-sig"),
            f"{city}_resultados.csv".replace(" ", "_"),
            "text/csv",
            use_container_width=True,
        )
        summary = f"""DESTINO: {city}, {country}
Hora local: {now.strftime('%H:%M')} | Diferencia: {difference}
Zona horaria: {timezone}
Centro aproximado: {lat:.5f}, {lon:.5f}

RESULTADOS:
Hoteles: {len(df[df['Categoría']=='Hoteles']) if not df.empty else 0}
Restaurantes: {len(df[df['Categoría']=='Restaurantes']) if not df.empty else 0}
Lugares para visitar: {len(df[df['Categoría']=='Lugares para visitar']) if not df.empty else 0}
Puntos de transporte: {len(df[df['Categoría']=='Transporte']) if not df.empty else 0}
"""
        st.text_area("Resumen para copiar", summary, height=220)
        st.download_button(
            "Descargar resumen TXT",
            summary.encode("utf-8"),
            f"{city}_resumen.txt".replace(" ", "_"),
            "text/plain",
            use_container_width=True,
        )

    with tab_saved:
        fav = favorites_df()
        city_fav = fav[fav["ciudad"] == city] if not fav.empty else fav
        if city_fav.empty:
            st.info("Todavía no has guardado recomendaciones para esta ciudad.")
        else:
            st.dataframe(city_fav, use_container_width=True, hide_index=True)
else:
    st.info("Escribe una ciudad arriba y presiona **Buscar destino**.")
    st.markdown("""
    **Ejemplos:** Madrid, París, Tokio, Nueva York, Cancún, Buenos Aires o Roma.

    Esta primera versión usa fuentes abiertas. Para precios y disponibilidad en tiempo real de hoteles,
    reservas directas y datos comerciales más completos, después se puede conectar Google Places,
    Amadeus u otro proveedor contratado por tu agencia.
    """)
