import os
import time
import shutil
import pyodbc
import re
from datetime import datetime, date
from azure.core.credentials import AzureKeyCredential
from azure.ai.documentintelligence import DocumentIntelligenceClient
from azure.ai.documentintelligence.models import AnalyzeResult

# CONEXIÓN AL MODELO Y AL RECURSO
ENDPOINT = "EL ENDPOINT DE DOCUMENT INTELLIGENCE"
KEY = "LA KEY DEL RECURSO"
MODEL_ID = "NOMBRE DEL MODELO CREADO EN DI STUDIO" 

# RUTAS DE TU PC
CARPETA_ENTRADA = r"RUTA A LAS FACTURAS QUE HAY QUE PROCESAR" 
CARPETA_PROCESADOS = r"RUTA A CARPETA PARA ALMACENAR FACTURAS PROCESADAS" 

# CONEXION A LA BBDD
DB_SERVER = 'NOMBRE DEL SERVIDOR DE LA BBDD'
DB_DATABASE = 'NOMBRE DE LA BBDD'
DB_USER = 'USUARIO'
DB_PASS = 'CONTRASEÑA'
DRIVER = 'DRIVER'


# DATOS POR DEFECTO
CORREO_ALUMNO = "CORREO PARA QUE APAREZCA QUIEN LO SUBE A LA BBDD"

#PARSEO

def limpiar_decimal(valor):
    """Convierte '1.200,50 €' -> 1200.50"""
    if not valor: return None
    v = str(valor).replace("€", "").replace("kW", "").replace("kWh", "").strip()
    v = v.replace(".", "").replace(",", ".")
    try:
        return float(v)
    except:
        return None

def limpiar_int(valor):
    """Convierte '29 días' -> 29"""
    if not valor: return None
    v = str(valor).split(',')[0].split('.')[0]
    v = re.sub(r'[^\d-]', '', v)
    try:
        return int(v)
    except:
        return None

def normalizar_fecha(valor_azure):
    """
    CRÍTICO: Convierte '17 de junio de 2025' o '17/06/2025' a objeto Date real.
    Si Azure devuelve un objeto date, lo usamos. Si devuelve texto, lo traducimos.
    """
    if not valor_azure:
        return datetime.now().date() # Si no hay fecha pone la actual
    if isinstance(valor_azure, date):
        return valor_azure

    texto = str(valor_azure).lower().strip()
    
    # TRADUCCIÓN DE FECHAS PARA RESPETAR EL FORMATO
    meses = {
        'enero': '01', 'febrero': '02', 'marzo': '03', 'abril': '04',
        'mayo': '05', 'junio': '06', 'julio': '07', 'agosto': '08',
        'septiembre': '09', 'octubre': '10', 'noviembre': '11', 'diciembre': '12'
    }

    for mes_nombre, mes_num in meses.items():
        if mes_nombre in texto:
            texto = texto.replace(mes_nombre, mes_num).replace(" de ", "/")
    
    formatos = ["%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%y"]
    
    for fmt in formatos:
        try:
            return datetime.strptime(texto, fmt).date()
        except ValueError:
            continue
            
    print(f"⚠️ Alerta: No pude entender la fecha '{valor_azure}'. Usando fecha de hoy.")
    return datetime.now().date()

def get_val(campos, key, tipo='str'):
    """Busca el campo en Azure y lo limpia según el tipo"""
    field = campos.get(key, {})
    if not field: return None
    
    contenido = field.get("content") # Texto tal cual aparece en el PDF
    valor_real = field.get("value")  # Valor interpretado por Azure 

    if tipo == 'decimal': return limpiar_decimal(contenido)

    if tipo == 'int': return limpiar_int(contenido)

    if tipo == 'date': 
        raw = valor_real if valor_real else contenido
        return normalizar_fecha(raw)
        
    return contenido # Por defecto devolvemos string

#PROCESAMIENTO

def procesar_factura(ruta_archivo):
    nombre_fichero = os.path.basename(ruta_archivo)
    print(f"--> 🧠 Analizando: {nombre_fichero}...")
    
    client = DocumentIntelligenceClient(endpoint=ENDPOINT, credential=AzureKeyCredential(KEY))

    with open(ruta_archivo, "rb") as f:
        poller = client.begin_analyze_document(
            model_id=MODEL_ID, body=f, content_type="application/pdf"
        )
    
    result = poller.result()

    if not result.documents:
        print("❌ Azure no detectó nada en este documento.")
        return False

    campos = result.documents[0].fields

    # MAPEO AZURE
    d = {
        # CAMPOS OBLIGATORIOS (NO NULL)
        "CorreoAlumno": CORREO_ALUMNO,
        "Nombrefichero": nombre_fichero,
        "NumFactura": get_val(campos, "NumeroFactura"),
        "FechaFactura": get_val(campos, "FechaFactura", 'date'),
        "Cliente": get_val(campos, "Cliente_Nombre"),
        "NIF_cliente": get_val(campos, "Cliente_NIF"),
        "Comercializadora": get_val(campos, "Comercializadora_Nombre"),
        "NIF_comercializadora": get_val(campos, "Comercializadora_NIF"),
        "Direccion": get_val(campos, "Cliente_Direccion"), 
        "BaseImponible": get_val(campos, "BaseImponible", 'decimal'),

        # CAMPOS OPCIONALES
        "Poblacion": get_val(campos, "Cliente_Poblacion"),
        "Provincia": get_val(campos, "Cliente_Provincia"),
        "CP": (get_val(campos, "Cliente_CP") or "")[:5],
        "Tarifa": (get_val(campos, "Tarifa") or "")[:10],       
        "DiasFactura": get_val(campos, "DiasFactura", 'int'),
        "TipoFactura": (get_val(campos, "TipoFactura") or "")[:10],
        "CUPS": get_val(campos, "CUPS"),
        "Contrato": get_val(campos, "Contrato"),

        # POTENCIAS
        "Pot_P1": get_val(campos, "Potencia_Contratada_P1", 'decimal'),
        "Pot_P2": get_val(campos, "Potencia_Contratada_P2", 'decimal'),
        "Pot_P3": get_val(campos, "Potencia_Contratada_P3", 'decimal'),
        "Pot_P4": get_val(campos, "Potencia_Contratada_P4", 'decimal'),
        "Pot_P5": get_val(campos, "Potencia_Contratada_P5", 'decimal'),
        "Pot_P6": get_val(campos, "Potencia_Contratada_P6", 'decimal'),

        # PRECIOS POTENCIA
        "Pre_Pot_P1": get_val(campos, "Precio_Potencia_P1", 'decimal'),
        "Pre_Pot_P2": get_val(campos, "Precio_Potencia_P2", 'decimal'),
        "Pre_Pot_P3": get_val(campos, "Precio_Potencia_P3", 'decimal'),
        "Pre_Pot_P4": get_val(campos, "Precio_Potencia_P4", 'decimal'),
        "Pre_Pot_P5": get_val(campos, "Precio_Potencia_P5", 'decimal'),
        "Pre_Pot_P6": get_val(campos, "Precio_Potencia_P6", 'decimal'),

        # PRECIOS ENERGÍA
        "Pre_E1": get_val(campos, "Precio_Energia_P1", 'decimal'),
        "Pre_E2": get_val(campos, "Precio_Energia_P2", 'decimal'),
        "Pre_E3": get_val(campos, "Precio_Energia_P3", 'decimal'),
        "Pre_E4": get_val(campos, "Precio_Energia_P4", 'decimal'),
        "Pre_E5": get_val(campos, "Precio_Energia_P5", 'decimal'),
        "Pre_E6": get_val(campos, "Precio_Energia_P6", 'decimal'),

        # CONSUMOS
        "Con_P1": get_val(campos, "Consumo_KWh_P1", 'int'),
        "Con_P2": get_val(campos, "Consumo_KWh_P2", 'int'),
        "Con_P3": get_val(campos, "Consumo_KWh_P3", 'int'),
        "Con_P4": get_val(campos, "Consumo_KWh_P4", 'int'),
        "Con_P5": get_val(campos, "Consumo_KWh_P5", 'int'),
        "Con_P6": get_val(campos, "Consumo_KWh_P6", 'int'),
    }

    # REVISIÓN DE SEGURIDAD PARA 'NO NULL'
    # Si por algún motivo falló la detección de estos campos, ponemos un valor tonto para que SQL no rechace la factura entera.
    if not d["NumFactura"]: d["NumFactura"] = "DESCONOCIDO-" + str(int(time.time()))
    if not d["Cliente"]: d["Cliente"] = "Cliente Desconocido"
    if not d["NIF_cliente"]: d["NIF_cliente"] = "00000000X"
    if not d["Comercializadora"]: d["Comercializadora"] = "Generica"
    if not d["NIF_comercializadora"]: d["NIF_comercializadora"] = "00000000X"
    if not d["Direccion"]: d["Direccion"] = "Direccion Desconocida"

    #INSERCIÓN SQL
    conn_str = f"DRIVER={DRIVER};SERVER={DB_SERVER};DATABASE={DB_DATABASE};UID={DB_USER};PWD={DB_PASS}"
    
    try:
        conn = pyodbc.connect(conn_str)
        cursor = conn.cursor()

        # Query basada en los label de Document Intelligence
        sql = """
        INSERT INTO [dbo].[Factura] (
            [CorreoAlumno], [Nombrefichero], [NumFactura], [FechaFactura], 
            [Cliente], [NIF cliente], [Comercializadora], [NIF comercializadora],
            [Diercción cliente], [Población cliente], [Provincia cliente], [CP cliente],
            [Tarifa], [Días factura], [Base imponible], [TipoFactura], [CUPS], [Contrato],
            
            [Potencia contratada kW P1], [Potencia contratada kW P2], [Potencia contratada kW P3], 
            [Potencia contratada kW P4], [Potencia contratada kW P5], [Potencia contratada kW P6],
            
            [Precio P1 kW/día], [Precio P2 kW/día], [Precio P3 kW/día], 
            [Precio P4 kW/día], [Precio P5 kW/día], [Precio P6 kW/día],
            
            [Precio E1 kWh], [Precio E2 kWh], [Precio E3 kWh], 
            [Precio E4 kWn], [Precio E5 kWh], [Precio E6 kWh],
            
            [Consumo P1 kWh], [Consumo P2 kWh], [Consumo P3 kWh], 
            [Consumo P4 kWh], [Consumo P5 kWh], [Consumo P6 kWh]
        ) VALUES (
            ?, ?, ?, ?, 
            ?, ?, ?, ?,
            ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?,
            
            ?, ?, ?, 
            ?, ?, ?,
            
            ?, ?, ?, 
            ?, ?, ?,
            
            ?, ?, ?, 
            ?, ?, ?,
            
            ?, ?, ?, 
            ?, ?, ?
        )
        """
        
        params = (
            d["CorreoAlumno"], d["Nombrefichero"], d["NumFactura"], d["FechaFactura"],
            d["Cliente"], d["NIF_cliente"], d["Comercializadora"], d["NIF_comercializadora"],
            d["Direccion"], d["Poblacion"], d["Provincia"], d["CP"],
            d["Tarifa"], d["DiasFactura"], d["BaseImponible"], d["TipoFactura"], d["CUPS"], d["Contrato"],
            
            d["Pot_P1"], d["Pot_P2"], d["Pot_P3"], d["Pot_P4"], d["Pot_P5"], d["Pot_P6"],
            d["Pre_Pot_P1"], d["Pre_Pot_P2"], d["Pre_Pot_P3"], d["Pre_Pot_P4"], d["Pre_Pot_P5"], d["Pre_Pot_P6"],
            d["Pre_E1"], d["Pre_E2"], d["Pre_E3"], d["Pre_E4"], d["Pre_E5"], d["Pre_E6"],
            d["Con_P1"], d["Con_P2"], d["Con_P3"], d["Con_P4"], d["Con_P5"], d["Con_P6"]
        )

        cursor.execute(sql, params)
        conn.commit()
        print(f"✅ ¡ÉXITO! Guardado en BD: {d['NumFactura']} ({d['FechaFactura']})")
        cursor.close()
        conn.close()
        return True

    except Exception as e:
        print(f"❌ Error SQL FATAL: {e}")
        return False

#BUCLE PARA PROCESAR FACTURAS
def main():
    if not os.path.exists(CARPETA_PROCESADOS):
        os.makedirs(CARPETA_PROCESADOS)

    print("Lectura de facturas:")
    print(f"📂 Entrada: {CARPETA_ENTRADA}")

    while True:
        archivos = [f for f in os.listdir(CARPETA_ENTRADA) if f.lower().endswith(".pdf")]
        
        for archivo in archivos:
            ruta_completa = os.path.join(CARPETA_ENTRADA, archivo)
            
            try:
                if procesar_factura(ruta_completa):
                    destino = os.path.join(CARPETA_PROCESADOS, archivo)
                    # Gestión de duplicados en procesados
                    if os.path.exists(destino):
                        nombre, ext = os.path.splitext(archivo)
                        destino = os.path.join(CARPETA_PROCESADOS, f"{nombre}_{int(time.time())}{ext}")
                    
                    shutil.move(ruta_completa, destino)
                    print("📁 Archivo archivado correctamente.\n")
            except Exception as e:
                print(f"⚠️ Error general con {archivo}: {e}")
        
        time.sleep(3)

if __name__ == "__main__":
    main()