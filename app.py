# app.py - El "Gerente" de la tienda (Versión con Emails y Referidos)

import flask
import mercadopago
import os
import json
import uuid
import gspread
from google.oauth2.service_account import Credentials
from cryptography.fernet import Fernet
from datetime import datetime
import pytz # Para manejar zonas horarias
import sendgrid # Importamos la librería de SendGrid
from sendgrid.helpers.mail import Mail # Importamos la clase Mail

# --- CONFIGURACIÓN INICIAL ---

app = flask.Flask(__name__, static_folder='.', static_url_path='')

# 1. SDK DE MERCADO PAGO
mp_token = os.environ.get("MERCADOPAGO_TOKEN")
sdk = mercadopago.SDK(mp_token) if mp_token else None

# 2. ENCRIPTACIÓN
encryption_key = os.environ.get("ENCRYPTION_KEY")
fernet = Fernet(encryption_key.encode()) if encryption_key else None
if fernet:
    print("Sistema de encriptación configurado correctamente.")
else:
    print("ADVERTENCIA: ENCRYPTION_KEY no configurada. La encriptación no funcionará.")

# 3. GOOGLE SHEETS
worksheet = None
try:
    creds_json_str = os.environ.get('GOOGLE_CREDENTIALS_JSON')
    sheet_url = os.environ.get('GOOGLE_SHEET_URL')
    if creds_json_str and sheet_url:
        creds_info = json.loads(creds_json_str)
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds = Credentials.from_service_account_info(creds_info, scopes=scopes)
        gc = gspread.authorize(creds)
        spreadsheet = gc.open_by_url(sheet_url)
        worksheet = spreadsheet.sheet1
        print("Conexión con Google Sheets establecida correctamente.")
        if not worksheet.row_values(1):
            print("La planilla está vacía. Añadiendo encabezados...")
            headers = [
                "ID_Venta", "Fecha_Solicitud", "Hora_Solicitud", "Nombre_Cliente", "Apellido_Cliente",
                "Plan_Comprado", "Contactos_A_Proteger", "Estado_Gestion",
                "Fecha_Limite_Gestion", "Progreso_Gestion", "Alerta_Vencimiento", "ID_Pago_MP",
                "Respaldo_Terminos_Condiciones", "Referido_Por"
            ]
            worksheet.append_row(headers, value_input_option='USER_ENTERED')
            print("Encabezados añadidos correctamente.")
    else:
        print("ERROR CRÍTICO: Faltan variables de entorno para Google Sheets.")
except Exception as e:
    print(f"ERROR CRÍTICO inesperado al configurar Google Sheets: {e}")

# 4. ALMACÉN TEMPORAL DE ÓRDENES
pending_orders = {}


# --- FUNCIONES AUXILIARES ---

def encrypt_data(data):
    if not fernet: return "ENCRYPTION_KEY_NOT_SET"
    return fernet.encrypt(json.dumps(data).encode('utf-8')).decode('utf-8')

def decrypt_data(encrypted_data):
    if not fernet: return None
    try:
        return json.loads(fernet.decrypt(encrypted_data.encode('utf-8')).decode('utf-8'))
    except Exception:
        return None

# ✅ IA-UPDATE: Función para enviar el email de confirmación.
def send_confirmation_email(customer_email, data):
    # ¡IMPORTANTE! Debes configurar estas variables.
    sendgrid_api_key = os.environ.get("SENDGRID_API_KEY")
    sender_email = "contacto@cortala.cl" # El email desde el que enviarás. Debe estar verificado en SendGrid.

    if not sendgrid_api_key:
        print("ADVERTENCIA: SENDGRID_API_KEY no configurada. No se enviará el email.")
        return

    message = Mail(
        from_email=sender_email,
        to_emails=customer_email,
        subject='✅ Confirmación de tu solicitud en Córtala.cl | Próximos Pasos',
        html_content=flask.render_template('confirmation_email.html', data=data)
    )
    try:
        sg = sendgrid.SendGridAPIClient(sendgrid_api_key)
        response = sg.send(message)
        print(f"Email de confirmación enviado a {customer_email}. Estado: {response.status_code}")
    except Exception as e:
        print(f"ERROR al enviar email: {e}")


# --- RUTAS DE LA APLICACIÓN (ENDPOINTS) ---

@app.route("/create_preference", methods=["POST"])
def create_preference():
    try:
        data = flask.request.get_json()
        external_reference_id = str(uuid.uuid4())
        
        contacts_to_protect = data.get("contacts_to_protect")
        if contacts_to_protect:
            pending_orders[external_reference_id] = {
                "contacts": contacts_to_protect,
                "payer_firstname": data.get("payer_firstname"),
                "payer_lastname": data.get("payer_lastname"),
                "price": data.get("price"),
                "referral_code_used": data.get("referral_code") # Guardamos el código de referido usado.
            }
        else:
            return flask.jsonify({"error": "No se proporcionaron contactos."}), 400

        preference_data = {
            "external_reference": external_reference_id,
            "items": [{"title": data["title"], "quantity": 1, "unit_price": float(data["price"]), "currency_id": "CLP"}],
            "payer": {"first_name": data["payer_firstname"], "last_name": data["payer_lastname"]},
            "back_urls": {"success": f"{flask.request.host_url}?status=success"},
            "auto_return": "approved",
            "notification_url": f"{flask.request.host_url}webhook"
        }
        
        preference_response = sdk.preference().create(preference_data)
        preference = preference_response["response"]
        return flask.jsonify({"init_point": preference["init_point"]})
    except Exception as e:
        print(f"Error en /create_preference: {e}")
        return flask.jsonify({"error": str(e)}), 500


@app.route("/webhook", methods=["POST"])
def receive_webhook():
    data = flask.request.get_json()
    if data and data.get("type") == "payment":
        payment_id = data["data"]["id"]
        try:
            payment_info = sdk.payment().get(payment_id)["response"]
            if payment_info and payment_info.get("status") == "approved":
                external_ref = payment_info.get("external_reference")
                order_data = pending_orders.pop(external_ref, {})
                
                # Recopilamos toda la información
                first_name = order_data.get("payer_firstname", payment_info.get("payer", {}).get("first_name", ""))
                last_name = order_data.get("payer_lastname", payment_info.get("payer", {}).get("last_name", ""))
                customer_email = payment_info.get("payer", {}).get("email", "")
                rut = "No informado"
                if payment_info.get("payer", {}).get("identification"):
                    rut = f"{payment_info['payer']['identification'].get('type')}: {payment_info['payer']['identification'].get('number')}"
                
                now_in_chile = datetime.now(pytz.timezone('Chile/Continental'))
                request_date = now_in_chile.strftime("%d/%m/%Y")
                request_time = now_in_chile.strftime("%H:%M:%S")
                plan_name = payment_info["additional_info"]["items"][0].get("title", "")
                
                # Generamos el código de referido para el nuevo cliente.
                referral_code = f"REF-{external_ref[:6].upper()}"

                # Guardamos la información completa para el respaldo y el email.
                email_data = {
                    "date": request_date, "time": request_time, "first_name": first_name,
                    "last_name": last_name, "rut": rut, "plan": plan_name,
                    "price": order_data.get("price", 0), "payment_id": payment_id,
                    "referral_code": referral_code,
                    "backup_url": f'{flask.request.host_url}respaldo/{external_ref}'
                }
                pending_orders[f"backup_{external_ref}"] = email_data

                # Preparamos la fila para la planilla
                new_row = [
                    external_ref, request_date, request_time, first_name, last_name, plan_name,
                    encrypt_data(order_data.get("contacts", [])), "Pendiente",
                    f'=INDIRECT("B"&ROW())+7',
                    f'=SPARKLINE(MAX(0, MIN(10, TODAY()-INDIRECT("B"&ROW()))), {{"charttype","bar"; "max",10; "color1", IF(TODAY()-INDIRECT("B"&ROW())<=6, "green", IF(TODAY()-INDIRECT("B"&ROW())<=9, "yellow", "red"))}})',
                    f'=IF(AND(TODAY()>INDIRECT("I"&ROW()), INDIRECT("H"&ROW())="Pendiente"), "VENCIDO", "OK")',
                    payment_id,
                    email_data["backup_url"],
                    order_data.get("referral_code_used", "N/A")
                ]

                if worksheet:
                    worksheet.append_row(new_row, value_input_option='USER_ENTERED')
                    print(f"Venta {external_ref} añadida a Google Sheets.")
                
                if customer_email:
                    send_confirmation_email(customer_email, email_data)

        except Exception as e:
            print(f"Error procesando webhook para pago {payment_id}: {e}")
            return flask.Response(status=500)
    return flask.Response(status=200)


# --- RUTAS PARA HERRAMIENTAS INTERNAS ---

@app.route("/desencriptar", methods=["GET", "POST"])
def decrypt_page():
    if flask.request.method == "POST":
        data_to_decrypt = flask.request.form.get("data")
        decrypted_data = decrypt_data(data_to_decrypt)
        result_string = "\n".join(decrypted_data) if decrypted_data else "Error al desencriptar."
        return flask.render_template_string('<h2>Resultado:</h2><pre>{{result}}</pre><a href="/desencriptar">Desencriptar otro</a>', result=result_string)
    return flask.send_from_directory('.', 'desencriptar.html')

@app.route("/respaldo/<external_ref>")
def backup_page(external_ref):
    backup_data = pending_orders.get(f"backup_{external_ref}")
    if not backup_data:
        return "Respaldo no encontrado o ya ha sido procesado.", 404
    return flask.render_template('respaldo.html', data=backup_data, ref=external_ref)


# --- RUTA PRINCIPAL ---

@app.route("/")
def index():
    return flask.send_from_directory('.', 'index.html')

if __name__ == "__main__":
    app.run(port=5000, debug=False)
