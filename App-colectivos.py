import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon
from shapely.validation import make_valid
import fiona
import tempfile
import os
import folium
from streamlit_folium import st_folium
import warnings

# Configuraciones iniciales
warnings.filterwarnings("ignore")
fiona.drvsupport.supported_drivers['KML'] = 'rw'

st.set_page_config(page_title="Análisis de Colectivos", layout="wide")
st.title("🚌 Analizador de Colectivos y Radios Censales")
st.write("Esta herramienta cruza los radios censales de tu zona con los recorridos de colectivos.")

# --- BARRA LATERAL ---
with st.sidebar:
    st.header("📂 Subir Archivos")
    st.write("1. Tu mapa de radios censales:")
    kml_radios = st.file_uploader("KML de Radios Censales", type=['kml'])
    
    st.write("2. Tus mapas de MyMaps:")
    kml_colectivos = st.file_uploader("KMLs de Colectivos", type=['kml'], accept_multiple_files=True)

# --- CUERPO PRINCIPAL ---
coords_text = st.text_area("📍 Coordenadas de la zona a analizar (Longitud, Latitud):", 
                           value="-58.560232, -34.685615\n-58.548214, -34.678274\n-58.529075, -34.692251\n-58.541693, -34.699731\n-58.560232, -34.685615", 
                           height=150)

# Filtro de seguridad anti-errores para las líneas
def tiene_puntos_suficientes(geom):
    try:
        if geom.geom_type == 'LineString':
            return len(geom.coords) >= 2
        elif geom.geom_type == 'MultiLineString':
            return all(len(line.coords) >= 2 for line in geom.geoms)
        return False
    except:
        return False

if st.button("🚀 Analizar Recorridos", type="primary"):
    if kml_radios and kml_colectivos and coords_text:
        with st.spinner("Cruzando datos espaciales con limpieza de seguridad..."):
            try:
                # 1. Crear el polígono con las coordenadas (limpio y validado)
                coords = [tuple(map(float, line.split(','))) for line in coords_text.strip().split('\n')]
                poly = Polygon(coords)
                poly = make_valid(poly) # Fuerza a reparar figuras cruzadas (moños)
                gdf_poly = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:4326")
                
                # 2. Leer el KML de Radios
                with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp_r:
                    tmp_r.write(kml_radios.getvalue())
                    ruta_r = tmp_r.name
                
                capas_r = fiona.listlayers(ruta_r)
                mapas_r = [gpd.read_file(ruta_r, driver='KML', layer=capa) for capa in capas_r if "Region" not in capa]
                gdf_radios = pd.concat(mapas_r, ignore_index=True)
                
                # Sanear radios para evitar colapsos
                gdf_radios['geometry'] = gdf_radios.geometry.apply(make_valid)
                gdf_radios = gdf_radios[~gdf_radios.is_empty]
                os.remove(ruta_r)

                col_desc = next((col for col in gdf_radios.columns if col.lower() == 'description'), None)
                if col_desc:
                    gdf_radios['Radio_ID'] = gdf_radios[col_desc].astype(str).str.extract(r'LINK:\s*(\d+)')
                else:
                    gdf_radios['Radio_ID'] = "Radio Censal"

                # Radios que tocan la zona
                radios_en_zona = gpd.clip(gdf_radios, gdf_poly)
                
                # 3. Leer todos los KMLs de Colectivos
                gdfs_lineas = []
                for f_col in kml_colectivos:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp_l:
                        tmp_l.write(f_col.getvalue())
                        ruta_l = tmp_l.name
                    
                    capas_l = fiona.listlayers(ruta_l)
                    for capa in capas_l:
                        gdf_temp = gpd.read_file(ruta_l, driver='KML', layer=capa)
                        gdfs_lineas.append(gdf_temp)
                    os.remove(ruta_l)
                
                # 4. Unir, limpiar y reparar las líneas
                gdf_todas_lineas = pd.concat(gdfs_lineas, ignore_index=True)
                gdf_todas_lineas['geometry'] = gdf_todas_lineas.geometry.apply(make_valid)
                gdf_todas_lineas = gdf_todas_lineas.explode(index_parts=False)
                gdf_todas_lineas = gdf_todas_lineas[gdf_todas_lineas.geom_type.isin(['LineString', 'MultiLineString'])]
                
                # 5. Cortar las líneas de manera súper segura (usando la caja general del barrio)
                lineas_recortadas = gpd.clip(gdf_todas_lineas, gdf_poly)
                
                # 6. LIMPIEZA EXTREMA (Acá eliminamos el error de 1 punto)
                lineas_recortadas = lineas_recortadas.explode(index_parts=False)
                lineas_recortadas = lineas_recortadas[lineas_recortadas.geom_type.isin(['LineString', 'MultiLineString'])]
                lineas_recortadas = lineas_recortadas[~lineas_recortadas.is_empty]
                
                # Aplicamos nuestra regla de oro: Si tiene menos de 2 puntos, a la basura.
                lineas_recortadas = lineas_recortadas[lineas_recortadas.geometry.apply(tiene_puntos_suficientes)]

                # 7. Extraer nombres para el reporte
                if not lineas_recortadas.empty:
                    col_nombre = 'Name' if 'Name' in lineas_recortadas.columns else lineas_recortadas.columns[0]
                    nombres_unicos = lineas_recortadas[col_nombre].dropna().unique().tolist()
                    nombres_unicos.sort()
                else:
                    nombres_unicos = []
                
                # --- MOSTRAR RESULTADOS ---
                st.success("✅ ¡Procesamiento exitoso!")
                
                st.subheader("📋 Detalle de Líneas de Colectivo")
                if nombres_unicos:
                    texto_lineas = ", ".join(map(str, nombres_unicos))
                    st.info(f"Las líneas de transporte que atraviesan los radios censales de esta zona son:\n\n**{texto_lineas}**")
                else:
                    st.warning("Ninguna de las líneas subidas pasa por adentro de esta zona.")
                
                st.subheader("🗺️ Mapa de Radios y Recorridos")
                centro_lat = poly.centroid.y
                centro_lon = poly.centroid.x
                m = folium.Map(location=[centro_lat, centro_lon], zoom_start=14)
                
                # Dibujar borde de zona
                folium.Polygon(locations=[(lat, lon) for lon, lat in coords], 
                               color='black', weight=3, fill=False, tooltip="Límite de la Zona").add_to(m)
                
                # Dibujar Radios
                if not radios_en_zona.empty:
                    folium.GeoJson(
                        radios_en_zona[['Radio_ID', 'geometry']].to_json(),
                        name="Radios Censales",
                        style_function=lambda x: {'fillColor': 'blue', 'color': 'blue', 'weight': 1, 'fillOpacity': 0.3},
                        tooltip=folium.GeoJsonTooltip(fields=['Radio_ID'], aliases=['Radio Censal:'])
                    ).add_to(m)
                
                # Dibujar Colectivos
                if not lineas_recortadas.empty:
                    folium.GeoJson(
                        lineas_recortadas[[col_nombre, 'geometry']].to_json(),
                        name="Líneas de Colectivo",
                        style_function=lambda x: {'color': 'red', 'weight': 4},
                        tooltip=folium.GeoJsonTooltip(fields=[col_nombre], aliases=['Línea:'])
                    ).add_to(m)
                
                st_folium(m, width=1000, height=500, returned_objects=[])
                
            except Exception as e:
                st.error(f"Hubo un error inesperado al procesar: {e}")
    else:
        st.warning("⚠️ Por favor, subí el KML de radios, al menos un KML de colectivos y verificá las coordenadas.")
