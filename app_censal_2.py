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
    st.header("📂 Archivos")
    uploaded_csv = st.file_uploader("Subir CSV", type=['csv'])
    uploaded_kml = st.file_uploader("Subir KML", type=['kml'])
    tolerancia = st.slider("Precisión de borde (%)", min_value=1, max_value=100, value=15, 
                           help="Porcentaje mínimo del radio que debe estar adentro del barrio.")

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
                # 🌟 MAPA INTERACTIVO
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
                # 🌟 TABLA Y DESCARGA (Fila Total con lógica de universos válidos)
                # ==========================================
                st.subheader("📋 Tabla de Datos Final")
                
                # 1. Limpiamos la fila TOTAL original congelada (si se coló)
                resultado_tabla = resultado_tabla[resultado_tabla['Completo'] != 'TOTAL']

                # 2. Sumamos todas las columnas numéricas absolutas
                totales = resultado_tabla.sum(numeric_only=True)
                df_totales = pd.DataFrame([totales])
                df_totales['Completo'] = 'TOTAL' 

                # --- 3. CÁLCULO ESTRICTO CLOACAS (Suma de partes) ---
                if 'Red de cloaca' in df_totales.columns and 'Red de cloaca %' in resultado_tabla.columns:
                    total_cloaca_casos = df_totales['Red de cloaca'].values[0]
                    # Reconstruimos la base real de cada fila para que no dé el 5,37% sino el exacto
                    pct_individual = resultado_tabla['Red de cloaca %'].astype(str).str.replace(',', '.').str.replace('%', '').astype(float) / 100
                    base_real_por_fila = resultado_tabla['Red de cloaca'] / pct_individual
                    suma_bases_reales = base_real_por_fila.sum()
                    
                    if suma_bases_reales > 0:
                        porcentaje_real_total = (total_cloaca_casos / suma_bases_reales) * 100
                        df_totales['Red de cloaca %'] = f"{porcentaje_real_total:.2f}%".replace('.', ',')

                # --- 4. EDUCACIÓN: Porcentajes sobre la suma de niveles ---
                col_jardin = 'Jardín maternal, guardería, centro de cuidado, salas de 0 a 5, jardín de infantes o preescolar'
                if col_jardin in df_totales.columns:
                    base_edu = (df_totales[col_jardin].values[0] + 
                                df_totales['Primario'].values[0] + 
                                df_totales['Secundario'].values[0] + 
                                df_totales['Terciario no universitario'].values[0] + 
                                df_totales['Universitario de grado'].values[0] + 
                                df_totales['Posgrado (especialización, maestría o doctorado)'].values[0])
                    
                    if base_edu > 0:
                        df_totales['_22'] = (df_totales[col_jardin] / base_edu * 100).round(2).astype(str).str.replace('.', ',') + '%'
                        df_totales['Porcentaje_23'] = (df_totales['Primario'] / base_edu * 100).round(2).astype(str).str.replace('.', ',') + '%'
                        df_totales['Porcentaje_24'] = (df_totales['Secundario'] / base_edu * 100).round(2).astype(str).str.replace('.', ',') + '%'
                        df_totales['Porcentaje_25'] = (df_totales['Terciario no universitario'] / base_edu * 100).round(2).astype(str).str.replace('.', ',') + '%'
                        df_totales['Porcentaje_26'] = (df_totales['Universitario de grado'] / base_edu * 100).round(2).astype(str).str.replace('.', ',') + '%'
                        df_totales['Posgrado %'] = (df_totales['Posgrado (especialización, maestría o doctorado)'] / base_edu * 100).round(2).astype(str).str.replace('.', ',') + '%'

                # --- 5. OCUPACIÓN: Porcentajes sobre la población activa/inactiva ---
                if 'Ocupado' in df_totales.columns:
                    base_ocupacion = (df_totales['Ocupado'].values[0] + 
                                      df_totales['Desocupado'].values[0] + 
                                      df_totales['Inactivo'].values[0])
                    
                    if base_ocupacion > 0:
                        df_totales['Ocupado %'] = (df_totales['Ocupado'] / base_ocupacion * 100).round(2).astype(str).str.replace('.', ',') + '%'
                        df_totales['Desocupado %'] = (df_totales['Desocupado'] / base_ocupacion * 100).round(2).astype(str).str.replace('.', ',') + '%'
                        df_totales['Inactivo %'] = (df_totales['Inactivo'] / base_ocupacion * 100).round(2).astype(str).str.replace('.', ',') + '%'

                # --- 6. Resto de los porcentajes estándar ---
                cols_viviendas = ['Agua de red', 'Gas natural', 'Tiene internet', 'No tiene internet', 'Propia', 'Alquilada', 'Cedida por trabajo', 'Prestada', 'Otra situacion']
                for col in cols_viviendas:
                    if col in df_totales.columns and 'Viviendas' in df_totales.columns:
                        v_tot = df_totales['Viviendas'].values[0]
                        if v_tot > 0:
                            df_totales[col + ' %'] = (df_totales[col] / v_tot * 100).round(2).astype(str).str.replace('.', ',') + '%'

                if 'Propia' in df_totales.columns:
                    prop_tot = df_totales['Propia'].values[0]
                    if prop_tot > 0:
                        df_totales['Escritura %'] = (df_totales['Escritura'] / prop_tot * 100).round(2).astype(str).str.replace('.', ',') + '%'
                        df_totales['Boleto de compra-venta %'] = (df_totales['Boleto de compra-venta'] / prop_tot * 100).round(2).astype(str).str.replace('.', ',') + '%'
                        df_totales['Otra documentacion %'] = (df_totales['Otra documentación'] / prop_tot * 100).round(2).astype(str).str.replace('.', ',') + '%'
                        df_totales['No tiene documentacion %'] = (df_totales['No tiene documentación'] / prop_tot * 100).round(2).astype(str).str.replace('.', ',') + '%'

                if 'Población' in df_totales.columns:
                    pob_tot = df_totales['Población'].values[0]
                    if pob_tot > 0:
                        cols_poblacion = {
                            'Obra social o prepaga (incluye pami)': 'Obra social %',
                            'Programas o planes estatales': 'Programas o planes estatales %',
                            'No tiene ni obra social, ni prepaga, ni plan de salud': 'No tiene ni obra social, ni prepaga, ni plan de salud %',
                            'Cobra jubilación': 'Porcentaje_15',
                            'No cobra jubilación': 'Porcentaje_16',
                            'Mujer': 'Porcentaje_17',
                            'Varon': 'Porcentaje_18',
                            'Hasta 14 años': 'Porcentaje_19',
                            '15 a 64 años': 'Porcentaje_20',
                            '65 o más': 'Porcentaje_21'
                        }
                        for col, nombre_pct in cols_poblacion.items():
                            if col in df_totales.columns:
                                df_totales[nombre_pct] = (df_totales[col] / pob_tot * 100).round(2).astype(str).str.replace('.', ',') + '%'

                # --- 7. Unimos todo y mandamos a la pantalla ---
                df_final = pd.concat([resultado_tabla, df_totales], ignore_index=True)

                st.dataframe(df_final)
                
                buffer = io.BytesIO()
                df_final.to_excel(buffer, index=False)
                st.download_button("💾 Descargar Excel Limpio", data=buffer.getvalue(), file_name="Resultado_Censal_Filtrado.xlsx")
                
            except Exception as e:
                st.error(f"Hubo un problema al procesar: {e}")
            finally:
                if os.path.exists(ruta_temp_kml):
                    os.remove(ruta_temp_kml)
    else:
        st.warning("Por favor, subí los dos archivos en la barra lateral y pegá las coordenadas.")
