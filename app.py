# app.py - El "Gerente" de la tienda (Versión con Automatización y Encriptación)

import flask
import mercadopago
import os
import json
import uuid
import gspread
# ✅ IA-UPDATE: Re-importamos Credentials para un control de autenticación más explícito.
from google.oauth2.service_account import Credentials
from cryptography.fernet import Fernet
from datetime import datetime
import pytz # Para manejar zonas horarias

# --- CONFIGURACIÓN INICIAL ---

# Creamos la oficina trasera (el servidor)
app = flask.Flask(__name__, static_folder='.', static_url_path='')

# 1. SDK DE MERCADO PAGO
mp_token = os.environ.get("MERCADOPAGO_TOKEN")
if not mp_token:
    print("ERROR: La variable de entorno MERCADOPAGO_TOKEN no está configurada.")
sdk = mercadopago.SDK(mp_token)

# 2. ENCRIPTACIÓN
encryption_key = os.environ.get("ENCRYPTION_KEY")
fernet = None
if not encryption_key:
    print("ADVERTENCIA: La variable de entorno ENCRYPTION_KEY no está configurada. La encriptación no será segura.")
    fernet = Fernet(Fernet.generate_key()) 
else:
    fernet = Fernet(encryption_key.encode())
    print("Sistema de encriptación configurado correctamente.")

# 3. GOOGLE SHEETS
worksheet = None # Inicializamos worksheet como None
try:
    creds_json_str = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    sheet_url = os.environ.get('GOOGLE_SHEET_URL')

    if not creds_json_str or not sheet_url:
        if not creds_json_str:
            print("ERROR CRÍTICO: La variable de entorno GOOGLE_CREDENTIALS_JSON no está configurada.")
        if not sheet_url:
            print("ERROR CRÍTICO: La variable de entorno GOOGLE_SHEET_URL no está configurada.")
    else:
        creds_info = json.loads(creds_json_str)
        
        # ✅ IA-UPDATE: Simplificamos los scopes al mínimo necesario.
        # A veces, permisos demasiado amplios pueden causar conflictos.
        scopes = [
            'https://www.googleapis.com/auth/spreadsheets'
        ]
        
        # Creamos el objeto de credenciales con los scopes definidos.
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        
        # Autorizamos gspread con estas credenciales explícitas.
        gc = gspread.authorize(creds)
        
        print("Autorización con Google completada. Abriendo planilla por URL...")
        spreadsheet = gc.open_by_url(sheet_url)
        
        worksheet = spreadsheet.sheet1
        print("Conexión con Google Sheets establecida correctamente.")

except gspread.exceptions.SpreadsheetNotFound:
    print("ERROR CRÍTICO: No se encontró la planilla. Verifica que la URL en GOOGLE_SHEET_URL es correcta y que la planilla está compartida con el email del robot.")
except gspread.exceptions.APIError as e:
    print(f"ERROR CRÍTICO de API de Google: {e}")
except Exception as e:
    print(f"ERROR CRÍTICO inesperado al configurar Google Sheets: {e}")


# 4. ALMACÉN TEMPORAL DE ÓRDENES
pending_orders = {}


# --- FUNCIONES AUXILIARES ---

def encrypt_data(data):
    """Encripta una lista de contactos."""
    if not fernet:
        print("ERROR: El sistema de encriptación no está inicializado.")
        return None
    data_string = json.dumps(data)
    encrypted_data = fernet.encrypt(data_string.encode('utf-8'))
    return encrypted_data.decode('utf-8')

def decrypt_data(encrypted_data):
    """Desencripta los contactos (función para uso futuro)."""
    if not fernet:
        print("ERROR: El sistema de encriptación no está inicializado.")
        return None
    decrypted_data_bytes = fernet.decrypt(encrypted_data.encode('utf-8'))
    data_string = decrypted_data_bytes.decode('utf-8')
    return json.loads(data_string)


# --- RUTAS DE LA APLICACIÓN (ENDPOINTS) ---

@app.route("/create_preference", methods=["POST"])
def create_preference():
    try:
        data = flask.request.get_json()
        host_url = flask.request.host_url
        external_reference_id = str(uuid.uuid4())
        
        contacts_to_protect = data.get("contacts_to_protect")
        if contacts_to_protect:
            pending_orders[external_reference_id] = contacts_to_protect
            print(f"Orden pendiente creada: {external_reference_id} con {len(contacts_to_protect)} contactos.")
        else:
            return flask.jsonify({"error": "No se proporcionaron contactos para proteger."}), 400

        item_id = "plan-" + data["title"].lower().replace(" ", "-").replace("(", "").replace(")", "")

        preference_data = {
            "external_reference": external_reference_id,
            "items": [
                {
                    "id": item_id,
                    "title": data["title"],
                    "quantity": int(data["quantity"]),
                    "unit_price": float(data["price"]),
                    "currency_id": "CLP",
                    "category_id": "services",
                    "description": "Servicio de gestión para inscripción en No Molestar del SERNAC."
                }
            ],
            "payer": {
                "first_name": data["payer_firstname"],
                "last_name": data["payer_lastname"]
            },
            "back_urls": {
                "success": f"{host_url}?status=success&ref={external_reference_id}",
                "failure": f"{host_url}?status=failure",
                "pending": f"{host_url}?status=pending"
            },
            "auto_return": "approved",
            "notification_url": f"{host_url}webhook"
        }
        
        preference_response = sdk.preference().create(preference_data)
        preference = preference_response["response"]
        
        return flask.jsonify({"id": preference["id"]})

    except Exception as e:
        print(f"Ocurrió un error en /create_preference: {e}")
        return flask.jsonify({"error": str(e)}), 500


@app.route("/webhook", methods=["POST"])
def receive_webhook():
    data = flask.request.get_json()
    print("========================================================")
    print("MENSAJE RECIBIDO DEL WEBHOOK DE MERCADO PAGO:")
    print(json.dumps(data, indent=4))
    
    if data and data.get("type") == "payment":
        payment_id = data["data"]["id"]
        
        try:
            payment_info_response = sdk.payment().get(payment_id)
            payment_info = payment_info_response.get("response")

            if payment_info and payment_info.get("status") == "approved":
                print(f"Pago {payment_id} APROBADO. Procesando...")

                external_ref = payment_info.get("external_reference")
                
                contacts = pending_orders.pop(external_ref, None)
                
                if not contacts:
                    print(f"ADVERTENCIA: No se encontraron contactos pendientes para la referencia {external_ref}. La orden podría ya haber sido procesada o la app se reinició.")
                    return flask.Response(status=200)

                encrypted_contacts = encrypt_data(contacts)

                chile_tz = pytz.timezone('Chile/Continental')
                request_date = datetime.now(chile_tz).strftime("%d/%m/%Y %H:%M:%S")

                new_row = [
                    external_ref, # ID_Venta
                    request_date, # Fecha_Solicitud
                    payment_info["payer"].get("first_name", ""), # Nombre_Cliente
                    payment_info["payer"].get("last_name", ""), # Apellido_Cliente
                    payment_info["additional_info"]["items"][0].get("title", ""), # Plan_Comprado
                    encrypted_contacts, # Contactos_A_Proteger (ENCRIPTADOS)
                    "Pendiente", # Estado_Gestion
                    f'=INDIRECT("B"&ROW())+7', # Fecha_Limite_Gestion (Fórmula)
                    f'=IF(AND(TODAY()>INDIRECT("H"&ROW()), INDIRECT("G"&ROW())="Pendiente"), "VENCIDO", "OK")', # Alerta_Vencimiento (Fórmula)
                    payment_id, # ID_Pago_MP
                ]

                if worksheet:
                    worksheet.append_row(new_row, value_input_option='USER_ENTERED')
                    print(f"Venta {external_ref} añadida a Google Sheets.")
                else:
                    print("ERROR: No se pudo escribir en Google Sheets porque la conexión falló al iniciar la app.")

            else:
                print(f"Pago {payment_id} no fue aprobado (estado: {payment_info.get('status')}). No se hace nada.")

        except Exception as e:
            print(f"ERROR procesando el webhook para el pago {payment_id}: {e}")
            return flask.Response(status=500)

    print("========================================================")
    return flask.Response(status=200)


@app.route("/")
def index():
    return flask.send_from_directory('.', 'index.html')

if __name__ == "__main__":
    app.run(port=5000, debug=False)
