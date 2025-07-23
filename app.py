# app.py - El "Gerente" de la tienda (Versión Final para Producción)

import flask
import mercadopago
import os # ✅ ¡LA LÍNEA QUE FALTABA! El manual para el archivador.

# Creamos la oficina trasera (el servidor)
app = flask.Flask(__name__, static_folder='.', static_url_path='')

# El SDK ahora lee la llave secreta desde el hosting (Render), no desde el código
sdk = mercadopago.SDK(os.environ.get("MERCADOPAGO_TOKEN"))

# Esta es la puerta de la oficina trasera, donde el "vendedor" (JS) trae las órdenes.
@app.route("/create_preference", methods=["POST"])
def create_preference():
    try:
        # El gerente recibe la nota del vendedor con los datos del plan elegido
        data = flask.request.get_json()
        
        # Prepara la orden de pago para enviársela al banco
        preference_data = {
            "items": [
                {
                    "title": data["title"],
                    "quantity": int(data["quantity"]),
                    "unit_price": float(data["price"]),
                    "currency_id": "CLP"
                }
            ],
            # Usamos URLs públicas que sabemos que funcionan
            "back_urls": {
                "success": "https://www.google.com/search?q=pago_exitoso",
                "failure": "https://www.google.com/search?q=pago_fallido",
                "pending": "https://www.google.com/search?q=pago_pendiente"
            },
            "auto_return": "approved", # Vuelve a la tienda automáticamente si el pago se aprueba
        }
        
        # El gerente llama al banco y crea la orden de pago
        preference_response = sdk.preference().create(preference_data)
        preference = preference_response["response"]
        
        # El gerente le devuelve el "número de ticket" (el ID) al vendedor
        return flask.jsonify({"id": preference["id"]})

    except Exception as e:
        # Si algo falla, la red de seguridad lo atrapa
        print(f"Ocurrió un error: {e}")
        # Y le avisa al navegador que hubo un problema en la oficina
        return flask.jsonify({"error": str(e)}), 500


# Ruta para servir la página principal de la tienda (index.html)
@app.route("/")
def index():
    return flask.send_from_directory('.', 'index.html')

# Le decimos al gerente que empiece a trabajar
if __name__ == "__main__":
    app.run(port=5000, debug=True)
