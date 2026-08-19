import streamlit as st
import pandas as pd
import geopandas as gpd
from shapely.geometry import Polygon
import fiona
import io
import tempfile
import os
import warnings
import folium
from streamlit_folium import st_folium

# Apagamos advertencias internas
warnings.filterwarnings("ignore")

st.set_page_config(page_title="Generador Censal", layout="wide")
st.title("📊 Generador de Datos Censales La Matanza")

# ==========================================
# 🧠 MEMORIA DE LA PÁGINA (Para que no se cierre el mapa)
# ==========================================
if 'mostrar_resultados' not in st.session_state:
    st.session_state['mostrar_resultados'] = False

# --- BARRA LATERAL (Para subir archivos) ---
with st.sidebar:
    st.header("📂 Archivos Base")
    uploaded_csv = st.file_uploader("Subir CSV", type=['csv'])
    uploaded_kml = st.file_uploader("Subir KML Radios", type=['kml'])
    tolerancia = st.slider("Precisión de borde (%)", min_value=1, max_value=100, value=15, 
                           help="Porcentaje mínimo del radio que debe estar adentro del barrio.")
    
    st.header("🚌 Opcional: Colectivos")
    uploaded_colectivos = st.file_uploader("Subir KMLs de Colectivos (MyMaps)", type=['kml'], accept_multiple_files=True)

# --- CUERPO PRINCIPAL ---
coords_text = st.text_area("📍 Pegá tus coordenadas (Longitud, Latitud):", 
                           height=150, 
                           value="-58.582223, -34.730360\n-58.567884, -34.741394\n-58.560564, -34.737408\n-58.576719, -34.725264\n-58.582223, -34.730360")

# Cuando se aprieta el botón, encendemos la memoria
if st.button("🚀 Procesar y Visualizar"):
    st.session_state['mostrar_resultados'] = True

# Si la memoria está encendida, corremos todo el proceso y lo dejamos fijo en pantalla
if st.session_state['mostrar_resultados']:
    if uploaded_csv and uploaded_kml and coords_text:
        with st.spinner('Midiendo áreas, dibujando mapas y procesando...'):
            with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp_kml:
                tmp_kml.write(uploaded_kml.getvalue())
                ruta_temp_kml = tmp_kml.name
                
            try:
                # 1. Lectura de datos
                df = pd.read_csv(uploaded_csv, sep=',', encoding='utf-8-sig')
                fiona.drvsupport.supported_drivers['KML'] = 'rw'
                
                capas = fiona.listlayers(ruta_temp_kml)
                mapas = [gpd.read_file(ruta_temp_kml, driver='KML', layer=capa) for capa in capas if "Region" not in capa]
                mapa = pd.concat(mapas, ignore_index=True)
                mapa['geometry'] = mapa['geometry'].buffer(0)
                
                # 2. Unión de datos
                col_desc = next((col for col in mapa.columns if col.lower() == 'description'), None)
                
                if col_desc is None:
                    st.error(f"Error: No se encontró la columna de descripción en el mapa. Columnas disponibles: {mapa.columns.tolist()}")
                    st.stop()
                    
                mapa['ID_EXTRAIDO'] = mapa[col_desc].astype(str).str.extract(r'LINK:\s*(\d+)')
                df['ID_CSV'] = df['Completo'].astype(str)
                df_final = mapa.merge(df, left_on='ID_EXTRAIDO', right_on='ID_CSV')
                
                # 3. Geometría del barrio
                coords = [tuple(map(float, line.split(','))) for line in coords_text.strip().split('\n')]
                poly = Polygon(coords)
                gdf_poly = gpd.GeoDataFrame(geometry=[poly], crs="EPSG:4326")
                
                # 4. Cálculo estricto de áreas
                df_metric = df_final.to_crs(epsg=3857)
                gdf_poly_metric = gdf_poly.to_crs(epsg=3857)
                
                df_metric['area_original'] = df_metric.geometry.area
                interseccion = gpd.overlay(df_metric, gdf_poly_metric, how='intersection')
                interseccion['area_adentro'] = interseccion.geometry.area
                interseccion['porc_adentro'] = (interseccion['area_adentro'] / interseccion['area_original']) * 100
                
                # 5. Filtrado final
                resultado_geo = interseccion[interseccion['porc_adentro'] >= tolerancia].copy()
                resultado_geo = resultado_geo.to_crs(epsg=4326) 
                
                # 6. Limpieza extrema, orden y numeración
                resultado_tabla = resultado_geo.drop(columns=['geometry'])
                resultado_tabla = resultado_tabla.sort_values(by='Completo')
                
                if 'Completo' in resultado_tabla.columns:
                    idx_completo = resultado_tabla.columns.get_loc('Completo')
                    resultado_tabla = resultado_tabla.iloc[:, idx_completo:]
                
                basura_derecha = ['ID_CSV', 'area_original', 'area_adentro', 'porc_adentro']
                resultado_tabla = resultado_tabla.drop(columns=[col for col in basura_derecha if col in resultado_tabla.columns])
                
                resultado_tabla = resultado_tabla.reset_index(drop=True)
                resultado_tabla.index = resultado_tabla.index + 1
                
                st.success(f"¡Éxito! Se detectaron {len(resultado_tabla)} radios exactos.")
                
                # ==========================================
                # 🌟 MAPA INTERACTIVO 1 (ORIGINAL)
                # ==========================================
                st.subheader("🗺️ Mapa del Barrio y Radios Censales")
                
                centro_lat = poly.centroid.y
                centro_lon = poly.centroid.x
                m = folium.Map(location=[centro_lat, centro_lon], zoom_start=14)
                
                folium.Polygon(locations=[(lat, lon) for lon, lat in coords], 
                               color='red', weight=3, fill=False, tooltip="Límite de tu Barrio").add_to(m)
                
                if not resultado_geo.empty:
                    folium.GeoJson(
                        resultado_geo[['Completo', 'geometry']].to_json(),
                        name="Radios Censales",
                        style_function=lambda x: {'fillColor': 'blue', 'color': 'blue', 'weight': 1, 'fillOpacity': 0.3},
                        tooltip=folium.GeoJsonTooltip(fields=['Completo'], aliases=['Radio Censal:'])
                    ).add_to(m)
                
                st_folium(m, width=1000, height=450, returned_objects=[], key="mapa_matanza")

                # ==========================================
                # 🚌 ANÁLISIS DE COLECTIVOS (NUEVO)
                # ==========================================
                if uploaded_colectivos:
                    st.markdown("---")
                    st.subheader("🚌 Líneas de Colectivo en la Zona")
                    
                    gdfs_lineas = []
                    for f_col in uploaded_colectivos:
                        with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp_l:
                            tmp_l.write(f_col.getvalue())
                            tmp_name_l = tmp_l.name
                        
                        capas_l = fiona.listlayers(tmp_name_l)
                        for capa in capas_l:
                            gdf_temp = gpd.read_file(tmp_name_l, driver='KML', layer=capa)
                            gdfs_lineas.append(gdf_temp)
                        os.remove(tmp_name_l)
                        
                    gdf_todas_lineas = pd.concat(gdfs_lineas, ignore_index=True)
                    gdf_todas_lineas = gdf_todas_lineas.to_crs(epsg=4326)
                    
                    # Recortamos las líneas para que SOLO queden los pedazos que están dentro/sobre los radios
                    lineas_recortadas = gpd.overlay(gdf_todas_lineas, resultado_geo, how='intersection')
                    
                    if not lineas_recortadas.empty:
                        # Extraemos los nombres de las líneas (MyMaps suele guardarlo en 'Name')
                        col_nombre_linea = 'Name' if 'Name' in lineas_recortadas.columns else lineas_recortadas.columns[0]
                        nombres_lineas = lineas_recortadas[col_nombre_linea].dropna().unique().tolist()
                        nombres_texto = ", ".join(map(str, nombres_lineas))
                        
                        st.info(f"**Las líneas que pasan por estos radios censales son:** {nombres_texto}")
                        
                        # Dibujamos el segundo mapa
                        m2 = folium.Map(location=[centro_lat, centro_lon], zoom_start=14)
                        
                        # Fondo: Radios censales
                        folium.GeoJson(
                            resultado_geo[['Completo', 'geometry']].to_json(),
                            name="Radios Censales",
                            style_function=lambda x: {'fillColor': 'gray', 'color': 'gray', 'weight': 1, 'fillOpacity': 0.2}
                        ).add_to(m2)
                        
                        # Frente: Pedacitos de colectivos recortados
                        folium.GeoJson(
                            lineas_recortadas.to_json(),
                            name="Líneas de Colectivo",
                            style_function=lambda x: {'color': 'red', 'weight': 4},
                            tooltip=folium.GeoJsonTooltip(fields=[col_nombre_linea], aliases=['Línea:'])
                        ).add_to(m2)
                        
                        st_folium(m2, width=1000, height=450, returned_objects=[], key="mapa_colectivos")
                    else:
                        st.warning("Las líneas subidas no atraviesan los radios censales de esta zona.")

                # ==========================================
                # 🌟 GRÁFICOS DINÁMICOS
                # ==========================================
                st.subheader("📈 Gráficos Interactivos")
                
                cols_numericas = resultado_tabla.select_dtypes(include=['number']).columns.tolist()
                for col_ignorar in ['Completo', 'Fraccion']:
                    if col_ignorar in cols_numericas:
                        cols_numericas.remove(col_ignorar)

                if cols_numericas and not resultado_tabla.empty:
                    columna_elegida = st.selectbox("Elegí el dato que querés graficar por Radio Censal:", cols_numericas)
                    
                    if columna_elegida:
                        df_grafico = resultado_tabla[['Completo', columna_elegida]].copy()
                        df_grafico['Completo'] = df_grafico['Completo'].astype(str)
                        df_grafico = df_grafico.set_index('Completo')
                        st.bar_chart(df_grafico)
                else:
                    st.info("No hay columnas numéricas para graficar.")

                # ==========================================
                # 🌟 TABLA Y DESCARGA
                # ==========================================
                st.subheader("📋 Tabla de Datos Final")
                st.dataframe(resultado_tabla)
                
                buffer = io.BytesIO()
                resultado_tabla.to_excel(buffer, index=False)
                st.download_button("💾 Descargar Excel Limpio", data=buffer.getvalue(), file_name="Resultado_Censal_Filtrado.xlsx")
                
            except Exception as e:
                st.error(f"Hubo un problema al procesar: {e}")
            finally:
                if os.path.exists(ruta_temp_kml):
                    os.remove(ruta_temp_kml)
    else:
        st.warning("Por favor, subí los dos archivos en la barra lateral y pegá las coordenadas.")
