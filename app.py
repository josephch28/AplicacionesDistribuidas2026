from flask import Flask, jsonify, request
import os
import certifi
import pytds
import threading

product_lock = threading.Lock()


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

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)