# --- EDUCACIÓN: Porcentajes sobre la suma de niveles ---
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

# --- OCUPACIÓN: Porcentajes sobre la población económicamente activa/inactiva ---
if 'Ocupado' in df_totales.columns:
    base_ocupacion = (df_totales['Ocupado'].values[0] + 
                      df_totales['Desocupado'].values[0] + 
                      df_totales['Inactivo'].values[0])
    
    if base_ocupacion > 0:
        df_totales['Ocupado %'] = (df_totales['Ocupado'] / base_ocupacion * 100).round(2).astype(str).str.replace('.', ',') + '%'
        df_totales['Desocupado %'] = (df_totales['Desocupado'] / base_ocupacion * 100).round(2).astype(str).str.replace('.', ',') + '%'
        df_totales['Inactivo %'] = (df_totales['Inactivo'] / base_ocupacion * 100).round(2).astype(str).str.replace('.', ',') + '%'
