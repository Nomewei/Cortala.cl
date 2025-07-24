# app.py - El "Gerente" de la tienda (Versión Profesional Mejorada)

import flask
import mercadopago
import os
import json
import uuid 

# Creamos la oficina trasera (el servidor)
app = flask.Flask(__name__, static_folder='.', static_url_path='')

# El SDK ahora lee la llave secreta desde el hosting (Render)
sdk = mercadopago.SDK(os.environ.get("MERCADOPAGO_TOKEN"))

# Puerta principal para crear la orden de pago
@app.route("/create_preference", methods=["POST"])
def create_preference():
    try:
        # El gerente recibe la nota del vendedor con todos los datos
        data = flask.request.get_json()
        host_url = flask.request.host_url
        external_reference_id = str(uuid.uuid4())
        
        # Prepara la orden de pago para enviársela al banco
        preference_data = {
            "external_reference": external_reference_id,
            "items": [
                {
                    "title": data["title"],
                    "quantity": int(data["quantity"]),
                    "unit_price": float(data["price"]),
                    "currency_id": "CLP",
                    # ✅ AÑADIDO: Detalles del producto para mejorar la calidad
                    "category_id": "services", # ID de categoría genérico para servicios
                    "description": "Servicio de gestión para inscripción en No Molestar del SERNAC."
                }
            ],
            # ✅ AÑADIDO: Información del comprador para mejorar la calidad
            "payer": {
                "first_name": data["payer_firstname"],
                "last_name": data["payer_lastname"]
            },
            "back_urls": {
                "success": f"{host_url}",
                "failure": f"{host_url}",
                "pending": f"{host_url}"
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

# La "Puerta del Mensajero" (Webhook)
@app.route("/webhook", methods=["POST"])
def receive_webhook():
    data = flask.request.get_json()
    print("========================================================")
    print("MENSAJE RECIBIDO DEL WEBHOOK DE MERCADO PAGO:")
    print(json.dumps(data, indent=4))
    print("========================================================")
    return flask.Response(status=200)


# Ruta para servir la página principal de la tienda (index.html)
@app.route("/")
def index():
    return flask.send_from_directory('.', 'index.html')

# Le decimos al gerente que empiece a trabajar
if __name__ == "__main__":
    app.run(port=5000, debug=False)
