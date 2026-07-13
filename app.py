
import math
import sqlite3
from datetime import datetime, date
from io import BytesIO
from zoneinfo import ZoneInfo

import folium
import pandas as pd
import requests
import streamlit as st
from streamlit_folium import st_folium

st.set_page_config(page_title="Travel Assistant CRM", page_icon="✈️", layout="wide")

DB = "travel_assistant.db"
UA = "TravelAssistantCRM/1.0"
OVERPASS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

st.markdown("""
<style>
.block-container {padding-top:1rem; padding-bottom:3rem;}
[data-testid="stMetricValue"] {font-size:1.35rem;}
.card {
    border:1px solid rgba(128,128,128,.25);
    padding:16px;
    border-radius:14px;
    margin-bottom:10px;
}
</style>
""", unsafe_allow_html=True)

def conn():
    return sqlite3.connect(DB, check_same_thread=False)

def init_db():
    con = conn()
    con.executescript("""
    CREATE TABLE IF NOT EXISTS clientes(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        telefono TEXT,
        email TEXT,
        destino_interes TEXT,
        fecha_salida TEXT,
        fecha_regreso TEXT,
        presupuesto REAL,
        estado TEXT,
        adultos INTEGER DEFAULT 1,
        menores INTEGER DEFAULT 0,
        preferencias TEXT,
        notas TEXT,
        creado_en TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS cotizaciones(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        cliente_id INTEGER,
        cliente_nombre TEXT,
        destino TEXT NOT NULL,
        adultos INTEGER DEFAULT 1,
        menores INTEGER DEFAULT 0,
        noches INTEGER DEFAULT 1,
        hotel TEXT,
        vuelo TEXT,
        actividades TEXT,
        transporte TEXT,
        total REAL DEFAULT 0,
        moneda TEXT DEFAULT 'MXN',
        estado TEXT DEFAULT 'Borrador',
        notas TEXT,
        creado_en TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS proveedores(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        nombre TEXT NOT NULL,
        categoria TEXT,
        ciudad TEXT,
        pais TEXT,
        telefono TEXT,
        email TEXT,
        sitio_web TEXT,
        contacto TEXT,
        notas TEXT,
        creado_en TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS favoritos(
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ciudad TEXT,
        pais TEXT,
        categoria TEXT,
        nombre TEXT,
        telefono TEXT,
        sitio_web TEXT,
        direccion TEXT,
        notas TEXT,
        creado_en TEXT NOT NULL
    );
    """)
    con.commit()
    con.close()

def query_df(sql, params=()):
    con = conn()
    df = pd.read_sql_query(sql, con, params=params)
    con.close()
    return df

def execute(sql, params=()):
    con = conn()
    con.execute(sql, params)
    con.commit()
    con.close()

init_db()

@st.cache_data(ttl=86400, show_spinner=False)
def geocode(name):
    r = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": name, "count": 8, "language": "es", "format": "json"},
        headers={"User-Agent": UA}, timeout=20
    )
    r.raise_for_status()
    return r.json().get("results", [])

@st.cache_data(ttl=1800, show_spinner=False)
def weather(lat, lon, tz):
    r = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": lat, "longitude": lon, "timezone": tz,
            "current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m"
        },
        headers={"User-Agent": UA}, timeout=20
    )
    r.raise_for_status()
    return r.json().get("current", {})

def condition(code):
    return {
        0:"Despejado",1:"Mayormente despejado",2:"Parcialmente nublado",3:"Nublado",
        45:"Niebla",51:"Llovizna",61:"Lluvia ligera",63:"Lluvia",65:"Lluvia intensa",
        71:"Nieve ligera",73:"Nieve",80:"Chubascos",81:"Chubascos",
        95:"Tormenta",96:"Tormenta con granizo"
    }.get(code, "Variable")

def haversine(a,b,c,d):
    r=6371
    p1,p2=math.radians(a),math.radians(c)
    dp,dl=math.radians(c-a),math.radians(d-b)
    x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(x))

@st.cache_data(ttl=3600, show_spinner=False)
def get_pois(lat, lon, radius):
    q=f"""
    [out:json][timeout:40];
    (
      nwr(around:{radius},{lat},{lon})["tourism"~"hotel|hostel|guest_house|apartment|motel"];
      nwr(around:{radius},{lat},{lon})["amenity"~"restaurant|cafe|fast_food|bar"];
      nwr(around:{radius},{lat},{lon})["tourism"~"attraction|museum|gallery|viewpoint|zoo|theme_park"];
      nwr(around:{radius},{lat},{lon})["historic"];
      nwr(around:{radius},{lat},{lon})["railway"~"station|subway_entrance|tram_stop"];
      nwr(around:{radius},{lat},{lon})["amenity"="bus_station"];
      nwr(around:{radius},{lat},{lon})["aeroway"="aerodrome"];
    );
    out center tags;
    """
    last=None
    for endpoint in OVERPASS:
        try:
            r=requests.post(endpoint,data={"data":q},headers={"User-Agent":UA},timeout=60)
            r.raise_for_status()
            return r.json().get("elements",[])
        except Exception as e:
            last=e
    raise RuntimeError(last)

def parse_pois(elements, lat0, lon0):
    rows=[]
    for e in elements:
        t=e.get("tags",{})
        lat=e.get("lat") or e.get("center",{}).get("lat")
        lon=e.get("lon") or e.get("center",{}).get("lon")
        if lat is None or lon is None:
            continue
        tourism=t.get("tourism","")
        amenity=t.get("amenity","")
        railway=t.get("railway","")
        historic=t.get("historic","")
        aeroway=t.get("aeroway","")

        if tourism in {"hotel","hostel","guest_house","apartment","motel"}:
            cat="Hoteles"; typ=tourism
        elif amenity in {"restaurant","cafe","fast_food","bar"}:
            cat="Restaurantes"; typ=amenity
        elif tourism in {"attraction","museum","gallery","viewpoint","zoo","theme_park"} or historic:
            cat="Lugares para visitar"; typ=tourism or historic
        elif railway or amenity=="bus_station" or aeroway=="aerodrome":
            cat="Transporte"; typ=railway or amenity or aeroway
        else:
            continue

        try:
            star=int(float(str(t.get("stars") or t.get("hotel:stars")).replace(",",".")))
        except:
            star=None

        address=" ".join(str(x) for x in [
            t.get("addr:street"), t.get("addr:housenumber"), t.get("addr:city")
        ] if x)

        rows.append({
            "Categoría":cat,
            "Nombre":t.get("name") or t.get("brand") or "Sin nombre registrado",
            "Tipo":typ.replace("_"," ").title(),
            "Estrellas":star,
            "Cocina":t.get("cuisine","").replace(";",", "),
            "Teléfono":t.get("contact:phone") or t.get("phone") or "",
            "Horario":t.get("opening_hours",""),
            "Sitio web":t.get("contact:website") or t.get("website") or "",
            "Dirección":address,
            "Distancia km":round(haversine(lat0,lon0,lat,lon),2),
            "Latitud":lat,
            "Longitud":lon,
            "Mapa":f"https://www.openstreetmap.org/?mlat={lat}&mlon={lon}#map=17/{lat}/{lon}"
        })
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).drop_duplicates().sort_values("Distancia km")

def show_table(df, cols):
    if df.empty:
        st.info("No hay resultados.")
        return
    st.dataframe(
        df[cols], use_container_width=True, hide_index=True,
        column_config={
            "Sitio web":st.column_config.LinkColumn("Sitio web",display_text="Abrir"),
            "Mapa":st.column_config.LinkColumn("Mapa",display_text="Ver"),
            "Distancia km":st.column_config.NumberColumn("Distancia km",format="%.2f"),
            "presupuesto":st.column_config.NumberColumn("Presupuesto",format="$ %.2f"),
            "total":st.column_config.NumberColumn("Total",format="$ %.2f"),
        }
    )

def backup_bytes():
    with open(DB, "rb") as f:
        return f.read()

with st.sidebar:
    st.title("✈️ Travel Assistant")
    page = st.radio(
        "Menú",
        ["Inicio","Destinos","CRM Clientes","Cotizaciones","Proveedores","Favoritos","Respaldo"],
        label_visibility="collapsed"
    )
    st.markdown("---")
    st.caption("Versión gratuita · OpenStreetMap + Open-Meteo")

if page == "Inicio":
    st.title("Panel de la agencia")
    clientes = query_df("SELECT * FROM clientes")
    cotizaciones = query_df("SELECT * FROM cotizaciones")
    proveedores = query_df("SELECT * FROM proveedores")

    c1,c2,c3,c4 = st.columns(4)
    c1.metric("Clientes", len(clientes))
    c2.metric("Cotizaciones", len(cotizaciones))
    c3.metric("Proveedores", len(proveedores))
    c4.metric("Monto cotizado", f"${cotizaciones['total'].sum():,.2f}" if not cotizaciones.empty else "$0.00")

    st.subheader("Seguimientos recientes")
    if clientes.empty:
        st.info("Todavía no hay clientes registrados.")
    else:
        show_table(clientes.sort_values("id", ascending=False).head(10),
                   ["nombre","telefono","destino_interes","fecha_salida","presupuesto","estado"])

    st.subheader("Cotizaciones recientes")
    if cotizaciones.empty:
        st.info("Todavía no hay cotizaciones.")
    else:
        show_table(cotizaciones.sort_values("id", ascending=False).head(10),
                   ["cliente_nombre","destino","adultos","menores","noches","total","estado"])

elif page == "Destinos":
    st.title("Buscador de destinos")
    radius=st.slider("Radio de búsqueda (km)",2,20,8)
    limit=st.slider("Resultados por sección",10,80,30,10)

    q=st.text_input("Ciudad o destino",placeholder="Madrid, España")
    if st.button("Buscar destino",type="primary",use_container_width=True) and q.strip():
        try:
            st.session_state["cities"]=geocode(q.strip())
        except Exception as exc:
            st.error(f"No se pudo buscar la ciudad: {exc}")

    cities=st.session_state.get("cities",[])
    if cities:
        opts={", ".join(filter(None,[c.get("name"),c.get("admin1"),c.get("country")])):c for c in cities}
        label=st.selectbox("Selecciona la ubicación correcta",list(opts))
        c=opts[label]
        lat,lon=float(c["latitude"]),float(c["longitude"])
        tz=c.get("timezone") or "UTC"
        name=c.get("name",label)
        country=c.get("country","")

        local=datetime.now(ZoneInfo(tz))
        mx=datetime.now(ZoneInfo("America/Mexico_City"))
        diff=(local.utcoffset()-mx.utcoffset()).total_seconds()/3600

        a,b,d,e=st.columns(4)
        a.metric("Hora local",local.strftime("%H:%M"))
        b.metric("Fecha",local.strftime("%d/%m/%Y"))
        d.metric("Diferencia con CDMX",f"{diff:+g} h")
        e.metric("Zona horaria",tz)

        try:
            w=weather(lat,lon,tz)
            a,b,d,e=st.columns(4)
            a.metric("Temperatura",f"{w.get('temperature_2m','—')} °C")
            b.metric("Sensación",f"{w.get('apparent_temperature','—')} °C")
            d.metric("Clima",condition(w.get("weather_code")))
            e.metric("Viento",f"{w.get('wind_speed_10m','—')} km/h")
        except Exception as exc:
            st.warning(f"No se pudo cargar el clima: {exc}")

        try:
            with st.spinner("Reuniendo hoteles, restaurantes, atractivos y transporte..."):
                data=parse_pois(get_pois(lat,lon,radius*1000),lat,lon)
        except Exception as exc:
            st.error(f"No fue posible consultar los lugares: {exc}")
            data=pd.DataFrame()

        tabs=st.tabs(["🏨 Hoteles","🍽️ Restaurantes","📍 Visitar","🚇 Transporte","🗺️ Mapa","📥 Exportar"])

        with tabs[0]:
            x=data[data["Categoría"]=="Hoteles"].head(limit) if not data.empty else pd.DataFrame()
            show_table(x,["Nombre","Tipo","Estrellas","Teléfono","Sitio web","Dirección","Distancia km","Mapa"] if not x.empty else [])
            if not x.empty:
                choice=st.selectbox("Guardar hotel",x["Nombre"].tolist(),key="save_hotel")
                if st.button("Guardar en favoritos",key="btn_hotel"):
                    r=x[x["Nombre"]==choice].iloc[0]
                    execute("""INSERT INTO favoritos(ciudad,pais,categoria,nombre,telefono,sitio_web,direccion,notas,creado_en)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (name,country,"Hotel",r["Nombre"],r["Teléfono"],r["Sitio web"],r["Dirección"],"",datetime.now().isoformat()))
                    st.success("Hotel guardado.")

        with tabs[1]:
            x=data[data["Categoría"]=="Restaurantes"].head(limit) if not data.empty else pd.DataFrame()
            show_table(x,["Nombre","Tipo","Cocina","Teléfono","Horario","Sitio web","Dirección","Distancia km","Mapa"] if not x.empty else [])
            if not x.empty:
                choice=st.selectbox("Guardar restaurante",x["Nombre"].tolist(),key="save_rest")
                if st.button("Guardar en favoritos",key="btn_rest"):
                    r=x[x["Nombre"]==choice].iloc[0]
                    execute("""INSERT INTO favoritos(ciudad,pais,categoria,nombre,telefono,sitio_web,direccion,notas,creado_en)
                               VALUES(?,?,?,?,?,?,?,?,?)""",
                            (name,country,"Restaurante",r["Nombre"],r["Teléfono"],r["Sitio web"],r["Dirección"],"",datetime.now().isoformat()))
                    st.success("Restaurante guardado.")

        with tabs[2]:
            x=data[data["Categoría"]=="Lugares para visitar"].head(limit) if not data.empty else pd.DataFrame()
            show_table(x,["Nombre","Tipo","Dirección","Distancia km","Sitio web","Mapa"] if not x.empty else [])

        with tabs[3]:
            x=data[data["Categoría"]=="Transporte"].head(limit) if not data.empty else pd.DataFrame()
            show_table(x,["Nombre","Tipo","Dirección","Distancia km","Mapa"] if not x.empty else [])

        with tabs[4]:
            m=folium.Map(location=[lat,lon],zoom_start=13)
            folium.Marker([lat,lon],tooltip=f"Centro de {name}").add_to(m)
            if not data.empty:
                for _,r in data.head(250).iterrows():
                    folium.Marker(
                        [r["Latitud"],r["Longitud"]],
                        tooltip=r["Nombre"],
                        popup=f"{r['Categoría']} · {r['Distancia km']} km"
                    ).add_to(m)
            st_folium(m,height=600,use_container_width=True)

        with tabs[5]:
            clean=data.drop(columns=["Latitud","Longitud"],errors="ignore") if not data.empty else pd.DataFrame()
            st.download_button(
                "Descargar resultados CSV",
                clean.to_csv(index=False).encode("utf-8-sig"),
                f"{name}_destino.csv".replace(" ","_"),
                "text/csv",
                use_container_width=True
            )
    else:
        st.info("Escribe una ciudad para comenzar.")

elif page == "CRM Clientes":
    st.title("CRM de clientes")
    t1,t2=st.tabs(["Nuevo cliente","Lista de clientes"])

    with t1:
        with st.form("nuevo_cliente",clear_on_submit=True):
            c1,c2=st.columns(2)
            nombre=c1.text_input("Nombre completo *")
            telefono=c2.text_input("Teléfono")
            email=c1.text_input("Correo")
            destino=c2.text_input("Destino de interés")
            salida=c1.date_input("Fecha de salida",value=None)
            regreso=c2.date_input("Fecha de regreso",value=None)
            adultos=c1.number_input("Adultos",1,20,1)
            menores=c2.number_input("Menores",0,20,0)
            presupuesto=c1.number_input("Presupuesto aproximado",0.0,100000000.0,0.0,1000.0)
            estado=c2.selectbox("Estado",["Nuevo","Seguimiento","Cotización","Confirmado","Viajando","Finalizado","Perdido"])
            preferencias=st.text_area("Preferencias")
            notas=st.text_area("Notas")
            ok=st.form_submit_button("Guardar cliente",type="primary",use_container_width=True)
            if ok:
                if not nombre.strip():
                    st.error("El nombre es obligatorio.")
                else:
                    execute("""INSERT INTO clientes(nombre,telefono,email,destino_interes,fecha_salida,fecha_regreso,presupuesto,
                               estado,adultos,menores,preferencias,notas,creado_en)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (nombre,telefono,email,destino,str(salida or ""),str(regreso or ""),presupuesto,
                             estado,adultos,menores,preferencias,notas,datetime.now().isoformat()))
                    st.success("Cliente guardado.")

    with t2:
        df=query_df("SELECT * FROM clientes ORDER BY id DESC")
        if df.empty:
            st.info("No hay clientes.")
        else:
            filtro=st.text_input("Buscar cliente")
            if filtro:
                mask=df.astype(str).apply(lambda col: col.str.contains(filtro,case=False,na=False)).any(axis=1)
                df=df[mask]
            show_table(df,["id","nombre","telefono","email","destino_interes","fecha_salida","presupuesto","estado"])
            st.download_button("Descargar clientes CSV",df.to_csv(index=False).encode("utf-8-sig"),"clientes.csv","text/csv",use_container_width=True)

elif page == "Cotizaciones":
    st.title("Cotizaciones")
    clientes=query_df("SELECT id,nombre FROM clientes ORDER BY nombre")
    cliente_options={"Sin cliente":(None,"")}
    for _,r in clientes.iterrows():
        cliente_options[r["nombre"]]=(int(r["id"]),r["nombre"])

    t1,t2=st.tabs(["Nueva cotización","Historial"])
    with t1:
        with st.form("nueva_cotizacion",clear_on_submit=True):
            cliente_label=st.selectbox("Cliente",list(cliente_options.keys()))
            c1,c2,c3=st.columns(3)
            destino=c1.text_input("Destino *")
            adultos=c2.number_input("Adultos",1,20,2)
            menores=c3.number_input("Menores",0,20,0)
            noches=c1.number_input("Noches",1,60,5)
            moneda=c2.selectbox("Moneda",["MXN","USD","EUR"])
            total=c3.number_input("Total",0.0,100000000.0,0.0,1000.0)
            hotel=st.text_area("Hotel")
            vuelo=st.text_area("Vuelo")
            actividades=st.text_area("Actividades")
            transporte=st.text_area("Transportes")
            estado=st.selectbox("Estado",["Borrador","Enviada","Seguimiento","Aceptada","Rechazada"])
            notas=st.text_area("Notas")
            ok=st.form_submit_button("Guardar cotización",type="primary",use_container_width=True)
            if ok:
                if not destino.strip():
                    st.error("El destino es obligatorio.")
                else:
                    cid,cname=cliente_options[cliente_label]
                    execute("""INSERT INTO cotizaciones(cliente_id,cliente_nombre,destino,adultos,menores,noches,hotel,vuelo,
                               actividades,transporte,total,moneda,estado,notas,creado_en)
                               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                            (cid,cname,destino,adultos,menores,noches,hotel,vuelo,actividades,transporte,total,moneda,estado,notas,datetime.now().isoformat()))
                    st.success("Cotización guardada.")

    with t2:
        df=query_df("SELECT * FROM cotizaciones ORDER BY id DESC")
        if df.empty:
            st.info("No hay cotizaciones.")
        else:
            show_table(df,["id","cliente_nombre","destino","adultos","menores","noches","total","moneda","estado","creado_en"])
            st.download_button("Descargar cotizaciones CSV",df.to_csv(index=False).encode("utf-8-sig"),"cotizaciones.csv","text/csv",use_container_width=True)

elif page == "Proveedores":
    st.title("Proveedores")
    t1,t2=st.tabs(["Nuevo proveedor","Directorio"])
    with t1:
        with st.form("nuevo_proveedor",clear_on_submit=True):
            c1,c2=st.columns(2)
            nombre=c1.text_input("Nombre *")
            categoria=c2.selectbox("Categoría",["Hotel","Transporte","Tour","Restaurante","Seguro","Guía","Otro"])
            ciudad=c1.text_input("Ciudad")
            pais=c2.text_input("País")
            telefono=c1.text_input("Teléfono")
            email=c2.text_input("Correo")
            sitio=c1.text_input("Sitio web")
            contacto=c2.text_input("Persona de contacto")
            notas=st.text_area("Notas")
            ok=st.form_submit_button("Guardar proveedor",type="primary",use_container_width=True)
            if ok:
                if not nombre.strip():
                    st.error("El nombre es obligatorio.")
                else:
                    execute("""INSERT INTO proveedores(nombre,categoria,ciudad,pais,telefono,email,sitio_web,contacto,notas,creado_en)
                               VALUES(?,?,?,?,?,?,?,?,?,?)""",
                            (nombre,categoria,ciudad,pais,telefono,email,sitio,contacto,notas,datetime.now().isoformat()))
                    st.success("Proveedor guardado.")
    with t2:
        df=query_df("SELECT * FROM proveedores ORDER BY id DESC")
        if df.empty:
            st.info("No hay proveedores.")
        else:
            show_table(df,["id","nombre","categoria","ciudad","pais","telefono","email","sitio_web","contacto"])
            st.download_button("Descargar proveedores CSV",df.to_csv(index=False).encode("utf-8-sig"),"proveedores.csv","text/csv",use_container_width=True)

elif page == "Favoritos":
    st.title("Favoritos del buscador")
    df=query_df("SELECT * FROM favoritos ORDER BY id DESC")
    if df.empty:
        st.info("Todavía no has guardado hoteles o restaurantes.")
    else:
        show_table(df,["id","ciudad","pais","categoria","nombre","telefono","sitio_web","direccion","notas"])
        st.download_button("Descargar favoritos CSV",df.to_csv(index=False).encode("utf-8-sig"),"favoritos.csv","text/csv",use_container_width=True)

elif page == "Respaldo":
    st.title("Respaldo de datos")
    st.warning("En alojamiento gratuito, descarga respaldos con frecuencia. El almacenamiento del servidor puede reiniciarse.")
    st.download_button(
        "Descargar base de datos completa",
        backup_bytes(),
        "travel_assistant_backup.db",
        "application/octet-stream",
        use_container_width=True
    )
    st.markdown("También puedes descargar CSV desde cada módulo.")
