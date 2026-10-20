from flask import Flask, jsonify, request
import os
import certifi
import pytds
import threading
import ssl
import re
import html
import json
import urllib.request
import urllib.error

product_lock = threading.Lock()
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


app = Flask(__name__)

#python3 -c "import pyodbc; print(pyodbc.drivers())"
#python3 -m pip show pyodbc
#python3 -m pip install pyodbc

# Database connection
def getConection():
    conn = pytds.connect(
        server = os.environ["DB_SERVER"],
        database = os.environ["DB_NAME"],
        user = os.environ["DB_USER"],
        password = os.environ["DB_PASSW"],
        port = 1433,
        cafile = certifi.where(),
        validate_host = True,
        row_strategy = pytds.namedtuple_row_strategy
    )
    return conn

@app.route('/test-db/', methods=['GET'])
def test_db():
    try:
        conn = getConection()
        cursor = conn.cursor()

        cursor.execute("SELECT DB_NAME()")
        database = cursor.fetchone()[0]
        conn.close()

        return jsonify(
            {
                "mensaje": "Conexión exitosa a la base de datos",
                "database": database
            }
        ), 200
    
    except Exception as e:
        return jsonify(
            {
                "mensaje": "Error al conectar a la base de datos",
                "error": str(e)
            }
        ), 500

### Usar view pr
@app.route('/api/products', methods=['GET'])
def get_products():
    try:
        conn = getConection()
        cursor = conn.cursor()

        cursor.execute("""SELECT id, name, price, stock FROM products_vw""")

        product = []
        for row in cursor.fetchall():
            product.append({
                "id": row.id,
                "name": row.name,
                "price": float(row.price),
                "stock": row.stock
            })
        cursor.close()
        conn.close()

        return jsonify(product), 200

    except Exception as e:
        return jsonify(
            {
                "mensaje": "Error al obtener los productos",
                "error": str(e)
            }
        ), 500
        
@app.route('/api/products/lock', methods=['GET'])
def get_product(id):
    try:
        conn = getConection()
        cursor = conn.cursor()

        cursor.execute("""SELECT id, name, price, stock FROM products_vw WHERE id = ?""", (id,))
        row = cursor.fetchone()

        if row:
            product = {
                "id": row.id,
                "name": row.name,
                "price": float(row.price),
                "stock": row.stock
            }
            cursor.close()
            conn.close()
            return jsonify(product), 200
        else:
            cursor.close()
            conn.close()
            return jsonify({"mensaje": "Producto no encontrado"}), 404

    except Exception as e:
        return jsonify(
            {
                "mensaje": "Error al obtener el producto",
                "error": str(e)
            }
        ), 500

### -- sp
@app.route('/api/products', methods=['POST'])
def create_product():
    try:
        data = request.get_json()
        if not data:
            return jsonify(
                {
                    "mensaje": "Datos de producto no proporcionados"
                }
            ), 400

        name = data.get('name')
        price = data.get('price')
        stock = data.get('stock')

        if not name or price is None or stock is None:
            return jsonify(
                {
                    "mensaje": "Faltan campos requeridos: name, price, stock"
                }
            ), 400

        conn = getConection()
        cursor = conn.cursor()

        cursor.execute(
            "EXEC products_insert_sp ?, ?, ?", (name, price, stock)
        )
        conn.commit()
        cursor.close()
        conn.close()

        return jsonify(
            {"mensaje": "Producto creado exitosamente"}
        ), 201
    
    except Exception as e:
        return jsonify(
            {
                "mensaje": "Error al procesar la solicitud",
                "error": str(e)
            }
        ), 500


################ update
### sin controles

@app.route("/api/products/lock", methods=["PUT"])
def update_lock():
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                "mensaje": "Datos de producto no proporcionados"
            }), 400
        with product_lock:
            print("entra el bloqueo")
            conn = getConection()
            cursor = conn.cursor()
            cursor.execute("UPDATE products SET name = ?, price = ?, stock = ? WHERE id = ?",
                           (data["name"], data["price"], data["stock"], data["id"]))
            if cursor.rowcount == 0:
                conn.rollback()
                cursor.close()
                conn.close()
                return jsonify({
                    "mensaje": "Producto no encontrado"
                }), 404
            conn.commit()
            cursor.close()
            conn.close()
            
            print("Salida del bloqueo")
            return jsonify({
                "mensaje": "Todo Ok"
            }), 200
    except Exception as e:
        return jsonify({
            "mensaje": "Error al actualizar el producto con bloqueo",
            "error": str(e)
        }), 500

@app.route("/api/products/version", methods=["PUT"])
def update_version():
    try:
        data = request.get_json()
        if not data:
            return jsonify({"msg": "Datos incompletos del producto"}), 400

        if data.get("version") is None:
            return jsonify({"msg": "Falta el campo 'version'"}), 400

        conn = getConection()
        cursor = conn.cursor()

        cursor.execute("UPDATE products SET name=?, price=?, stock=?, version=version+1 WHERE id=? AND version=?", 
                       (data.get("name"), data.get("price"), data.get("stock"), data.get("id"), data.get("version")))

        if cursor.rowcount == 0:
            cursor.execute("SELECT version FROM products WHERE id=?", (data.get("id"),))
            row = cursor.fetchone()
            conn.rollback()
            cursor.close()
            conn.close()
            if row:
                producto_actual = {
                    "id": data.get("id"),
                    "version": row.version
                }
                return jsonify({
                    "msg": "Versión incorrecta",
                    "error": producto_actual
                }), 409
            else:
                return jsonify({"msg": "Producto no encontrado o versión incorrecta"}), 404
            
        conn.commit()
        cursor.close()
        conn.close()
        return jsonify({"msg": "Producto actualizado exitosamente"}), 200
        
    except Exception as e:
        return jsonify({
            "msg": "Error al actualizar el producto con control de versión",
            "error": str(e)
        }), 500

################ correo

def build_report_html(products):
    total_stock = sum(p["stock"] for p in products)
    rows = ""
    for i, p in enumerate(products):
        bg = "#f8fafc" if i % 2 else "#ffffff"
        rows += (
            f'<tr style="background:{bg}">'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e2e8f0">{p["id"]}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e2e8f0">{html.escape(str(p["name"]))}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;text-align:right">${p["price"]:,.2f}</td>'
            f'<td style="padding:10px 12px;border-bottom:1px solid #e2e8f0;text-align:right">{p["stock"]}</td>'
            f'</tr>'
        )

    return f"""<!DOCTYPE html>
<html><body style="margin:0;padding:24px;background:#f1f5f9;font-family:Arial,Helvetica,sans-serif;color:#0f172a">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:640px;margin:0 auto;background:#ffffff;border-radius:12px;overflow:hidden">
    <tr><td style="background:#2563eb;padding:24px 28px;color:#ffffff">
      <div style="font-size:13px;opacity:.85">Reporte de inventario</div>
      <div style="font-size:24px;font-weight:bold;margin-top:4px">Listado de productos</div>
    </td></tr>
    <tr><td style="padding:24px 28px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>
        <td style="width:50%;padding-right:8px"><div style="background:#eff6ff;border-radius:8px;padding:16px;text-align:center">
          <div style="font-size:28px;font-weight:bold;color:#2563eb">{len(products)}</div>
          <div style="font-size:12px;color:#475569">Productos</div></div></td>
        <td style="width:50%;padding-left:8px"><div style="background:#f0fdf4;border-radius:8px;padding:16px;text-align:center">
          <div style="font-size:28px;font-weight:bold;color:#16a34a">{total_stock}</div>
          <div style="font-size:12px;color:#475569">Unidades en stock</div></div></td>
      </tr></table>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="margin-top:24px;font-size:14px;border-collapse:collapse">
        <tr style="background:#0f172a;color:#ffffff">
          <th style="padding:10px 12px;text-align:left">ID</th>
          <th style="padding:10px 12px;text-align:left">Producto</th>
          <th style="padding:10px 12px;text-align:right">Precio</th>
          <th style="padding:10px 12px;text-align:right">Stock</th>
        </tr>
        {rows}
      </table>
    </td></tr>
    <tr><td style="padding:16px 28px;background:#f8fafc;font-size:12px;color:#64748b;text-align:center">
      Generado automáticamente desde la API de productos
    </td></tr>
  </table>
</body></html>"""

def build_report_text(products):
    lines = [f"Total de productos: {len(products)}", ""]
    for p in products:
        lines.append(f'{p["id"]} - {p["name"]} - ${p["price"]:,.2f} - stock: {p["stock"]}')
    return "\n".join(lines)

def send_email(to, subject, text, html_body):
    # Render Free bloquea SMTP, se envía por la API HTTP de Resend
    payload = json.dumps({
        "from": os.environ.get("MAIL_FROM", "Reportes <onboarding@resend.dev>"),
        "to": [to],
        "subject": subject,
        "text": text,
        "html": html_body
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=payload,
        method="POST",
        headers={
            "Authorization": f"Bearer {os.environ['RESEND_API_KEY']}",
            "Content-Type": "application/json",
            "User-Agent": "products-api/1.0"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=20, context=ssl.create_default_context(cafile=certifi.where())) as res:
            return json.loads(res.read())
    except urllib.error.HTTPError as e:
        raise Exception(f"Resend {e.code}: {e.read().decode('utf-8', 'ignore')}")

@app.route('/api/products/report', methods=['POST'])
def send_products_report():
    try:
        data = request.get_json(silent=True) or {}
        email = data.get('email') or os.environ.get("REPORT_TO")

        if not email or not EMAIL_RE.match(email):
            return jsonify(
                {
                    "mensaje": "Correo destino no proporcionado o inválido: email"
                }
            ), 400

        conn = getConection()
        cursor = conn.cursor()

        cursor.execute("""SELECT id, name, price, stock FROM products_vw""")

        products = []
        for row in cursor.fetchall():
            products.append({
                "id": row.id,
                "name": row.name,
                "price": float(row.price),
                "stock": row.stock
            })
        cursor.close()
        conn.close()

        send_email(
            email,
            f"Reporte de productos ({len(products)})",
            build_report_text(products),
            build_report_html(products)
        )

        return jsonify(
            {
                "mensaje": "Correo enviado exitosamente",
                "email": email,
                "total_productos": len(products)
            }
        ), 200

    except Exception as e:
        return jsonify(
            {
                "mensaje": "Error al enviar el correo",
                "error": str(e)
            }
        ), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)