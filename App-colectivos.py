import streamlit as st
import geopandas as gpd
import pandas as pd
from shapely.geometry import Polygon, MultiLineString
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

# --- FUNCIONES DE SEGURIDAD EXTREMA ---
def limpiar_linea(geom):
    """ Extrae de forma segura solo líneas con 2 o más puntos, aislando errores. """
    try:
        if geom is None or geom.is_empty:
            return None
        if geom.geom_type == 'LineString':
            return geom if len(geom.coords) >= 2 else None
        elif geom.geom_type == 'MultiLineString':
            lineas = [line for line in geom.geoms if len(line.coords) >= 2]
            return MultiLineString(lineas) if lineas else None
        elif geom.geom_type == 'GeometryCollection':
            lineas = []
            for g in geom.geoms:
                if g.geom_type == 'LineString' and len(g.coords) >= 2:
                    lineas.append(g)
                elif g.geom_type == 'MultiLineString':
                    lineas.extend([line for line in g.geoms if len(line.coords) >= 2])
            return MultiLineString(lineas) if lineas else None
        return None
    except Exception:
        return None

def cortar_linea_segura(geom, area):
    """ Corta una línea contra el polígono de forma aislada. Si la matemática falla, no tira abajo la app. """
    try:
        if geom is None: return None
        corte = geom.intersection(area)
        return limpiar_linea(corte)
    except Exception:
        return None

def reparar_poligono(geom):
    """ Sanea polígonos corruptos para que el corte no falle. """
    try:
        if geom is None or geom.is_empty: return None
        if geom.geom_type in ['Polygon', 'MultiPolygon']:
            res = geom.buffer(0)
            return res if not res.is_empty else None
        return None
    except Exception:
        return None

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

if st.button("🚀 Analizar Recorridos", type="primary"):
    if kml_radios and kml_colectivos and coords_text:
        with st.spinner("Modo Antifallos Activado: Limpiando geometrías corruptas línea por línea..."):
            try:
                # 1. Crear el polígono con las coordenadas
                coords = [tuple(map(float, line.split(','))) for line in coords_text.strip().split('\n')]
                poly = Polygon(coords)
                gdf_poly = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:4326")
                
                # 2. Leer el KML de Radios
                with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp_r:
                    tmp_r.write(kml_radios.getvalue())
                    ruta_r = tmp_r.name
                
                capas_r = fiona.listlayers(ruta_r)
                mapas_r = [gpd.read_file(ruta_r, driver='KML', layer=capa) for capa in capas_r if "Region" not in capa]
                gdf_radios = pd.concat(mapas_r, ignore_index=True)
                os.remove(ruta_r)
                
                # Saneamos los polígonos del radio censal de forma segura
                gdf_radios['geometry'] = gdf_radios.geometry.apply(reparar_poligono)
                gdf_radios = gdf_radios.dropna(subset=['geometry']).set_geometry('geometry')

                col_desc = next((col for col in gdf_radios.columns if col.lower() == 'description'), None)
                if col_desc:
                    gdf_radios['Radio_ID'] = gdf_radios[col_desc].astype(str).str.extract(r'LINK:\s*(\d+)')
                else:
                    gdf_radios['Radio_ID'] = "Radio Censal"

                # Filtrar qué radios caen dentro de las coordenadas
                radios_en_zona = gpd.clip(gdf_radios, gdf_poly)
                
                if radios_en_zona.empty:
                    st.warning("Los radios censales no intersectan con las coordenadas ingresadas. Revisá las coordenadas.")
                    st.stop()
                
                # 3. Leer todos los KMLs de Colectivos y LIMPIAR FILA POR FILA
                gdfs_lineas = []
                for f_col in kml_colectivos:
                    with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp_l:
                        tmp_l.write(f_col.getvalue())
                        ruta_l = tmp_l.name
                    
                    capas_l = fiona.listlayers(ruta_l)
                    for capa in capas_l:
                        try:
                            gdf_temp = gpd.read_file(ruta_l, driver='KML', layer=capa)
                            # Aislamos las geometrías rotas antes de pasarlas a Geopandas
                            gdf_temp['geometry'] = gdf_temp.geometry.apply(limpiar_linea)
                            gdf_temp = gdf_temp.dropna(subset=['geometry']).set_geometry('geometry')
                            
                            if not gdf_temp.empty:
                                gdfs_lineas.append(gdf_temp)
                        except Exception:
                            continue # Si la capa entera está irrecuperable, la ignoramos y seguimos
                    os.remove(ruta_l)
                
                if not gdfs_lineas:
                    st.error("Todas las líneas subidas estaban vacías o corruptas. No hay datos espaciales recuperables.")
                    st.stop()

                # Unir todas las líneas validadas
                gdf_todas_lineas = pd.concat(gdfs_lineas, ignore_index=True)
                
                # 4. Cortar los colectivos contra los radios (FILA POR FILA, anti-colapso)
                try:
                    area_radios = radios_en_zona.geometry.unary_union.buffer(0)
                except Exception:
                    area_radios = poly # Si los radios están corruptos, recortamos usando el marco general
                
                lineas_recortadas = gdf_todas_lineas.copy()
                lineas_recortadas['geometry'] = lineas_recortadas.geometry.apply(lambda x: cortar_linea_segura(x, area_radios))
                lineas_recortadas = lineas_recortadas.dropna(subset=['geometry']).set_geometry('geometry')

                # 5. Extraer nombres para el reporte
                col_nombre = 'Name' if 'Name' in lineas_recortadas.columns else lineas_recortadas.columns[0]
                nombres_unicos = lineas_recortadas[col_nombre].dropna().unique().tolist()
                nombres_unicos.sort()
                
                # --- MOSTRAR RESULTADOS ---
                st.success("✅ ¡Procesamiento exitoso y blindado contra errores de MyMaps!")
                
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
                st.error(f"Hubo un error crítico: {e}")
    else:
        st.warning("⚠️ Por favor, subí el KML de radios, al menos un KML de colectivos y verificá las coordenadas.")
