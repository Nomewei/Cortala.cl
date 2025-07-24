# app.py - El "Gerente" de la tienda (Versión Final con Webhook)

import flask
import mercadopago
import os
import json # Necesario para manejar la respuesta del webhook
import uuid # Herramienta para crear códigos únicos

# Creamos la oficina trasera (el servidor)
app = flask.Flask(__name__, static_folder='.', static_url_path='')

# El SDK ahora lee la llave secreta desde el hosting (Render), no desde el código
sdk = mercadopago.SDK(os.environ.get("MERCADOPAGO_TOKEN"))

# Puerta principal para crear la orden de pago
@app.route("/create_preference", methods=["POST"])
def create_preference():
    try:
        data = flask.request.get_json()
        host_url = flask.request.host_url
        
        # Creamos una "etiqueta" única para esta orden
        external_reference_id = str(uuid.uuid4())
        
        preference_data = {
            # Adjuntamos nuestra etiqueta única a la orden
            "external_reference": external_reference_id,
            "items": [
                {
                    "title": data["title"],
                    "quantity": int(data["quantity"]),
                    "unit_price": float(data["price"]),
                    "currency_id": "CLP"
                }
            ],
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
    # Recibimos el mensaje
    data = flask.request.get_json()
    
    # Imprimimos el mensaje en los logs de Render para que puedas verlo
    print("========================================================")
    print("MENSAJE RECIBIDO DEL WEBHOOK DE MERCADO PAGO:")
    print(json.dumps(data, indent=4))
    print("========================================================")
    
    # Aquí, en el futuro, podrías añadir lógica como:
    # if data.get("type") == "payment" and data.get("action") == "payment.created":
    #     payment_id = data["data"]["id"]
    #     # Buscar el pago en la base de datos y marcarlo como "pagado"
    #     # Enviar un email de confirmación al cliente
    #     print(f"Pago {payment_id} recibido y procesado.")

    # Le respondemos al mensajero "OK, mensaje recibido"
    return flask.Response(status=200)


# Ruta para servir la página principal de la tienda (index.html)
@app.route("/")
def index():
    return flask.send_from_directory('.', 'index.html')

# Le decimos al gerente que empiece a trabajar
if __name__ == "__main__":
    app.run(port=5000, debug=False) # Debug se pone en False para producción
