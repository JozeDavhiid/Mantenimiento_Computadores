import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import psycopg2
from psycopg2.extras import RealDictCursor
from io import BytesIO
from datetime import date
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# ====== CONFIG ======
DB_URL = os.environ.get('DATABASE_URL')
SECRET_KEY = os.environ.get('SECRET_KEY', 'Liam2205@.')

if not DB_URL:
    raise ValueError("Debes configurar DATABASE_URL como variable de entorno con la URL de PostgreSQL de Render")

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ====== DB CONEXIÓN ======
def get_db():
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS tecnicos (
                    id SERIAL PRIMARY KEY,
                    usuario TEXT UNIQUE,
                    nombre TEXT,
                    contrasena TEXT
                )''')
    c.execute('''CREATE TABLE IF NOT EXISTS mantenimiento (
                    id SERIAL PRIMARY KEY,
                    sede TEXT,
                    fecha DATE,
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
                )''')
    # Crear admin por defecto
    c.execute("SELECT * FROM tecnicos WHERE usuario='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO tecnicos (usuario, nombre, contrasena) VALUES (%s,%s,%s)",
                  ('admin', 'Administrador', '1234'))
    conn.commit()
    conn.close()

with app.app_context():
    init_db()

# ====== RUTAS ======
@app.route('/')
def home():
    if 'usuario' in session:
        return redirect(url_for('principal'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        usuario = request.form['usuario'].strip()
        contrasena = request.form['contrasena'].strip()
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT nombre FROM tecnicos WHERE usuario=%s AND contrasena=%s", (usuario, contrasena))
        row = c.fetchone()
        conn.close()
        if row:
            session['usuario'] = usuario
            session['nombre'] = row['nombre']
            return redirect(url_for('principal'))
        flash('Usuario o contraseña incorrectos', 'danger')
    return render_template('login.html')

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        usuario = request.form['usuario'].strip()
        nombre = request.form['nombre'].strip()
        contrasena = request.form['contrasena'].strip()
        conn = get_db()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO tecnicos (usuario,nombre,contrasena) VALUES (%s,%s,%s)",
                      (usuario, nombre, contrasena))
            conn.commit()
            flash('Técnico registrado correctamente', 'success')
            return redirect(url_for('login'))
        except psycopg2.errors.UniqueViolation:
            flash('El usuario ya existe', 'warning')
            conn.rollback()
        finally:
            conn.close()
    return render_template('registro.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/principal', methods=['GET', 'POST'])
def principal():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()

    # ===== Guardar registro =====
    if request.method == 'POST' and request.form.get('action') == 'guardar':
        datos = (
            request.form.get('sede',''),
            request.form.get('fecha', date.today()),
            request.form.get('area',''),
            session.get('nombre',''),
            request.form.get('nombre_maquina',''),
            request.form.get('usuario_equipo',''),
            request.form.get('tipo_equipo',''),
            request.form.get('marca',''),
            request.form.get('modelo',''),
            request.form.get('serial',''),
            request.form.get('so',''),
            request.form.get('office',''),
            request.form.get('antivirus',''),
            request.form.get('compresor',''),
            request.form.get('control_remoto',''),
            request.form.get('activo_fijo',''),
            request.form.get('observaciones','')
        )
        c.execute('''INSERT INTO mantenimiento
                     (sede, fecha, area, tecnico, nombre_maquina, usuario, tipo_equipo, marca, modelo, serial,
                      sistema_operativo, office, antivirus, compresor, control_remoto, activo_fijo, observaciones)
                     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)''', datos)
        conn.commit()
        flash('Registro guardado', 'success')

    # ===== Actualizar registro =====
    if request.method == 'POST' and request.form.get('action') == 'actualizar':
        rid = request.form.get('id')
        datos = (
            request.form.get('sede',''),
            request.form.get('fecha', date.today()),
            request.form.get('area',''),
            request.form.get('tecnico',''),
            request.form.get('nombre_maquina',''),
            request.form.get('usuario_equipo',''),
            request.form.get('tipo_equipo',''),
            request.form.get('marca',''),
            request.form.get('modelo',''),
            request.form.get('serial',''),
            request.form.get('so',''),
            request.form.get('office',''),
            request.form.get('antivirus',''),
            request.form.get('compresor',''),
            request.form.get('control_remoto',''),
            request.form.get('activo_fijo',''),
            request.form.get('observaciones',''),
            rid
        )
        c.execute('''UPDATE mantenimiento SET
                     sede=%s, fecha=%s, area=%s, tecnico=%s, nombre_maquina=%s, usuario=%s,
                     tipo_equipo=%s, marca=%s, modelo=%s, serial=%s, sistema_operativo=%s,
                     office=%s, antivirus=%s, compresor=%s, control_remoto=%s, activo_fijo=%s, observaciones=%s
                     WHERE id=%s''', datos)
        conn.commit()
        flash('Registro actualizado', 'success')

    # ===== Filtrado =====
    search = request.args.get('q','').strip()
    sede_filter = request.args.get('sede','Todas')
    query = "SELECT * FROM mantenimiento WHERE 1=1"
    params = []
    if search:
        like = f"%{search}%"
        query += " AND (sede ILIKE %s OR area ILIKE %s OR tecnico ILIKE %s OR nombre_maquina ILIKE %s OR usuario ILIKE %s OR tipo_equipo ILIKE %s OR marca ILIKE %s OR modelo ILIKE %s OR serial ILIKE %s OR sistema_operativo ILIKE %s OR office ILIKE %s OR antivirus ILIKE %s OR compresor ILIKE %s OR control_remoto ILIKE %s OR activo_fijo ILIKE %s OR observaciones ILIKE %s)"
        params += [like]*16
    if sede_filter and sede_filter != 'Todas':
        query += " AND sede=%s"
        params.append(sede_filter)
    query += " ORDER BY id DESC"
    c.execute(query, params)
    registros = c.fetchall()
    sedes = ["Todas","Nivel Central","Barranquilla","Soledad","Santa Marta","El Banco","Monteria","Sincelejo","Valledupar","El Carmen de Bolivar","Magangue"]
    conn.close()

    return render_template('principal.html', registros=registros, sedes=sedes,
                           search=search, sede_filter=sede_filter, nombre=session.get('nombre'))

# ====== Actas individuales =====
@app.route('/acta/<int:rid>')
def acta(rid):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM mantenimiento WHERE id=%s", (rid,))
    row = c.fetchone()
    conn.close()
    if not row:
        flash('Registro no encontrado', 'warning')
        return redirect(url_for('principal'))

    # Crear PDF
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.setFont("Helvetica", 12)
    y = 750
    for key, value in row.items():
        p.drawString(50, y, f"{key}: {value}")
        y -= 20
    p.showPage()
    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"acta_{rid}.pdf", mimetype='application/pdf')

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
