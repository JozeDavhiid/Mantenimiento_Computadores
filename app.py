import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import psycopg2
import psycopg2.extras
import openpyxl
from io import BytesIO
from datetime import date
from flask import send_file
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import io

# =====================================
# CONFIGURACIÓN GENERAL
# =====================================
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'clave_super_secreta')

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://mantenimiento_db_g877_user:IdTqz3iR5QxBJcvVc5kcOVXWue435JUV@dpg-d3jup2e3jp1c73akgu5g-a.oregon-postgres.render.com/mantenimiento_db_g877"  # Cambia por la URL real de Render
)

# =====================================
# CONEXIÓN A LA BASE DE DATOS
# =====================================
def get_db():
    conn = psycopg2.connect(DATABASE_URL)
    return conn


def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS mantenimiento (
            id SERIAL PRIMARY KEY,
            sede TEXT,
            fecha TEXT,
            area TEXT,
            tecnico TEXT,
            nombre_maquina TEXT,
            usuario TEXT,
            tipo_equipo TEXT,
            marca TEXT,
            modelo TEXT,
            serial TEXT,
            sistema_operativo TEXT,
            office TEXT,
            antivirus TEXT,
            compresor TEXT,
            control_remoto TEXT,
            activo_fijo TEXT,
            observaciones TEXT
        );
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tecnicos (
            id SERIAL PRIMARY KEY,
            usuario TEXT UNIQUE,
            nombre TEXT,
            contrasena TEXT
        );
    """)
    cur.execute("SELECT * FROM tecnicos WHERE usuario='admin';")
    if not cur.fetchone():
        cur.execute(
            "INSERT INTO tecnicos (usuario, nombre, contrasena) VALUES (%s, %s, %s)",
            ('admin', 'Administrador', '1234')
        )
    conn.commit()
    cur.close()
    conn.close()


# Inicializa la base al iniciar el servidor
with app.app_context():
    init_db()

# =====================================
# RUTAS PRINCIPALES
# =====================================

@app.route('/')
def home():
    if 'usuario' in session:
        return redirect(url_for('principal'))
    return redirect(url_for('login'))

# -------------------------------------
# LOGIN
# -------------------------------------
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario'].strip()
        contrasena = request.form['contrasena'].strip()
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT nombre FROM tecnicos WHERE usuario=%s AND contrasena=%s", (usuario, contrasena))
        row = cur.fetchone()
        conn.close()

        if row:
            session['usuario'] = usuario
            session['nombre'] = row['nombre']
            return redirect(url_for('principal'))
        flash('Usuario o contraseña incorrectos', 'danger')
    return render_template('login.html')

# -------------------------------------
# REGISTRO DE NUEVOS TÉCNICOS
# -------------------------------------
@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        usuario = request.form['usuario'].strip()
        nombre = request.form['nombre'].strip()
        contrasena = request.form['contrasena'].strip()
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute(
                "INSERT INTO tecnicos (usuario, nombre, contrasena) VALUES (%s, %s, %s)",
                (usuario, nombre, contrasena)
            )
            conn.commit()
            flash('Técnico registrado correctamente', 'success')
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            flash('El usuario ya existe', 'warning')
        finally:
            conn.close()
    return render_template('registro.html')

# -------------------------------------
# CERRAR SESIÓN
# -------------------------------------
@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# -------------------------------------
# ACTAS
# -------------------------------------

@app.route('/descargar_acta/<int:id>')
def descargar_acta(id):
    conn = sqlite3.connect("mantenimiento.db")
    c = conn.cursor()
    c.execute("SELECT * FROM mantenimiento WHERE id=?", (id,))
    registro = c.fetchone()
    conn.close()

    if not registro:
        return "Registro no encontrado", 404

    # Crear PDF en memoria
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica", 12)

    p.drawString(200, 750, "ACTA DE MANTENIMIENTO DE EQUIPO")
    p.line(50, 740, 550, 740)

    y = 710
    campos = [
        ("ID", registro[0]),
        ("Sede", registro[1]),
        ("Fecha", registro[2]),
        ("Técnico", registro[3]),
        ("Tipo de equipo", registro[4]),
        ("Sistema operativo", registro[5]),
        ("Office", registro[6]),
        ("Antivirus", registro[7]),
        ("Compresor", registro[8]),
        ("Control remoto", registro[9]),
        ("Observaciones", registro[10])
    ]

    for campo, valor in campos:
        p.drawString(70, y, f"{campo}: {valor}")
        y -= 25

    p.line(50, 100, 550, 100)
    p.drawString(70, 80, "Firma del técnico: ________________________")

    p.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f"acta_mantenimiento_{id}.pdf",
                     mimetype='application/pdf')

# -------------------------------------
# PÁGINA PRINCIPAL
# -------------------------------------
@app.route('/principal', methods=['GET', 'POST'])
def principal():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Insertar nuevo registro
    if request.method == 'POST' and request.form.get('action') == 'guardar':
        datos = (
            request.form.get('sede', ''),
            request.form.get('fecha', date.today().isoformat()),
            request.form.get('area', ''),
            session.get('nombre', ''),
            request.form.get('nombre_maquina', ''),
            request.form.get('usuario_equipo', ''),
            request.form.get('tipo_equipo', ''),
            request.form.get('marca', ''),
            request.form.get('modelo', ''),
            request.form.get('serial', ''),
            request.form.get('so', ''),
            request.form.get('office', ''),
            request.form.get('antivirus', ''),
            request.form.get('compresor', ''),
            request.form.get('control_remoto', ''),
            request.form.get('activo_fijo', ''),
            request.form.get('observaciones', '')
        )
        cur.execute('''INSERT INTO mantenimiento
                    (sede, fecha, area, tecnico, nombre_maquina, usuario, tipo_equipo, marca, modelo, serial,
                     sistema_operativo, office, antivirus, compresor, control_remoto, activo_fijo, observaciones)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''', datos)
        conn.commit()
        flash('Registro guardado correctamente', 'success')

    # Actualizar registro existente
    if request.method == 'POST' and request.form.get('action') == 'actualizar':
        rid = request.form.get('id')
        datos = (
            request.form.get('sede', ''),
            request.form.get('fecha', date.today().isoformat()),
            request.form.get('area', ''),
            request.form.get('tecnico', ''),
            request.form.get('nombre_maquina', ''),
            request.form.get('usuario_equipo', ''),
            request.form.get('tipo_equipo', ''),
            request.form.get('marca', ''),
            request.form.get('modelo', ''),
            request.form.get('serial', ''),
            request.form.get('so', ''),
            request.form.get('office', ''),
            request.form.get('antivirus', ''),
            request.form.get('compresor', ''),
            request.form.get('control_remoto', ''),
            request.form.get('activo_fijo', ''),
            request.form.get('observaciones', ''),
            rid
        )
        cur.execute('''UPDATE mantenimiento SET
                    sede=%s, fecha=%s, area=%s, tecnico=%s, nombre_maquina=%s, usuario=%s,
                    tipo_equipo=%s, marca=%s, modelo=%s, serial=%s, sistema_operativo=%s, office=%s, antivirus=%s,
                    compresor=%s, control_remoto=%s, activo_fijo=%s, observaciones=%s WHERE id=%s''', datos)
        conn.commit()
        flash('Registro actualizado correctamente', 'success')

    # Filtros
    search = request.args.get('q', '').strip()
    sede_filter = request.args.get('sede', 'Todas')
    query = "SELECT * FROM mantenimiento WHERE 1=1"
    params = []
    if search:
        like = f"%{search}%"
        query += " AND (sede ILIKE %s OR area ILIKE %s OR tecnico ILIKE %s OR nombre_maquina ILIKE %s OR usuario ILIKE %s OR tipo_equipo ILIKE %s OR marca ILIKE %s OR modelo ILIKE %s OR serial ILIKE %s OR sistema_operativo ILIKE %s OR office ILIKE %s OR antivirus ILIKE %s OR compresor ILIKE %s OR control_remoto ILIKE %s OR activo_fijo ILIKE %s OR observaciones ILIKE %s)"
        params += [like] * 16
    if sede_filter and sede_filter != 'Todas':
        query += " AND sede = %s"
        params.append(sede_filter)
    query += " ORDER BY id DESC"
    cur.execute(query, params)
    registros = cur.fetchall()
    sedes = ["Todas", "Nivel Central", "Barranquilla", "Soledad", "Santa Marta", "El Banco",
             "Monteria", "Sincelejo", "Valledupar", "El Carmen de Bolivar", "Magangue"]
    conn.close()
    return render_template('principal.html', registros=registros, sedes=sedes, search=search,
                           sede_filter=sede_filter, nombre=session.get('nombre'))

# -------------------------------------
# ELIMINAR REGISTRO
# -------------------------------------
@app.route('/eliminar/<int:rid>', methods=['POST'])
def eliminar(rid):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM mantenimiento WHERE id=%s", (rid,))
    conn.commit()
    conn.close()
    flash('Registro eliminado correctamente', 'info')
    return redirect(url_for('principal'))

# -------------------------------------
# EXPORTAR A EXCEL
# -------------------------------------
@app.route('/exportar')
def exportar():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT * FROM mantenimiento")
    registros = cur.fetchall()
    if not registros:
        flash('No hay registros para exportar', 'warning')
        return redirect(url_for('principal'))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Mantenimiento"
    encabezados = [desc[0] for desc in cur.description]
    ws.append(encabezados)
    for row in registros:
        ws.append(list(row))
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)
    conn.close()
    return send_file(bio, as_attachment=True, download_name='Mantenimiento.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

# =====================================
# EJECUCIÓN LOCAL
# =====================================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
