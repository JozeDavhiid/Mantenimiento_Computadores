import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import psycopg2
from psycopg2.extras import RealDictCursor
from io import BytesIO
from datetime import date
import openpyxl
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from io import BytesIO
import textwrap

# -----------------------
# Configuración
# -----------------------
DB_URL = os.environ.get('DATABASE_URL')
if not DB_URL:
    raise ValueError("Debes configurar DATABASE_URL como variable de entorno con la URL de PostgreSQL de Render")

SECRET_KEY = os.environ.get('SECRET_KEY', 'cambiala_por_una_secreta_en_render')

app = Flask(__name__)
app.secret_key = SECRET_KEY

# -----------------------
# Funciones DB
# -----------------------
def get_db():
    conn = psycopg2.connect(DB_URL, cursor_factory=RealDictCursor)
    return conn

def init_db():
    conn = get_db()
    c = conn.cursor()
    # Tabla mantenimiento
    c.execute('''CREATE TABLE IF NOT EXISTS mantenimiento (
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
                )''')
    # Tabla tecnicos
    c.execute('''CREATE TABLE IF NOT EXISTS tecnicos (
                    id SERIAL PRIMARY KEY,
                    usuario TEXT UNIQUE,
                    nombre TEXT,
                    contrasena TEXT
                )''')
    # Insert default admin
    c.execute("SELECT * FROM tecnicos WHERE usuario='admin'")
    if not c.fetchone():
        c.execute("INSERT INTO tecnicos (usuario, nombre, contrasena) VALUES (%s, %s, %s)",
                  ('admin', 'Administrador', '1234'))
    conn.commit()
    conn.close()

with app.app_context():
    init_db()

# -----------------------
# Rutas
# -----------------------
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
            c.execute("INSERT INTO tecnicos (usuario, nombre, contrasena) VALUES (%s, %s, %s)",
                      (usuario, nombre, contrasena))
            conn.commit()
            flash('Técnico registrado correctamente', 'success')
            return redirect(url_for('login'))
        except psycopg2.IntegrityError:
            conn.rollback()
            flash('El usuario ya existe', 'warning')
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

    # Insertar registro
    if request.method == 'POST' and request.form.get('action') == 'guardar':
        datos = (
            request.form.get('sede',''),
            request.form.get('fecha', date.today().isoformat()),
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
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''', datos)
        conn.commit()
        flash('Registro guardado', 'success')

    # Búsqueda y filtros
    search = request.args.get('q','').strip()
    sede_filter = request.args.get('sede','Todas')
    query = "SELECT * FROM mantenimiento WHERE 1=1"
    params = []
    if search:
        like = f"%{search}%"
        query += """ AND (sede ILIKE %s OR area ILIKE %s OR tecnico ILIKE %s OR nombre_maquina ILIKE %s 
                     OR usuario ILIKE %s OR tipo_equipo ILIKE %s OR marca ILIKE %s OR modelo ILIKE %s 
                     OR serial ILIKE %s OR sistema_operativo ILIKE %s OR office ILIKE %s OR antivirus ILIKE %s 
                     OR compresor ILIKE %s OR control_remoto ILIKE %s OR activo_fijo ILIKE %s OR observaciones ILIKE %s)"""
        params += [like]*16
    if sede_filter and sede_filter != 'Todas':
        query += " AND sede = %s"
        params.append(sede_filter)
    query += " ORDER BY id DESC"
    c.execute(query, params)
    registros = c.fetchall()

    sedes = ["Todas","Nivel Central","Barranquilla","Soledad","Santa Marta","El Banco",
             "Monteria","Sincelejo","Valledupar","El Carmen de Bolivar","Magangue"]

    conn.close()
    return render_template('principal.html', registros=registros, sedes=sedes,
                           search=search, sede_filter=sede_filter, nombre=session.get('nombre'),
                           hoy=date.today().isoformat())

@app.route('/editar/<int:id>', methods=['GET', 'POST'])
def editar_registro(id):
    if 'nombre' not in session:
        return redirect(url_for('login'))

    conn = get_db_connection()
    cur = conn.cursor()

    if request.method == 'POST':
        fecha = request.form['fecha']
        nombre_maquina = request.form['nombre_maquina']
        marca = request.form['marca']
        modelo = request.form['modelo']
        serial = request.form['serial']
        sede_id = request.form['sede']
        observaciones = request.form['observaciones']

        cur.execute("""
            UPDATE registros
            SET fecha = %s, nombre_maquina = %s, marca = %s, modelo = %s,
                serial = %s, sede_id = %s, observaciones = %s
            WHERE id = %s
        """, (fecha, nombre_maquina, marca, modelo, serial, sede_id, observaciones, id))
        conn.commit()

        cur.close()
        conn.close()

        flash("Registro actualizado correctamente", "success")
        return redirect(url_for('consultar'))

    # Método GET: obtener datos actuales del registro
    cur.execute("""
        SELECT id, fecha, nombre_maquina, marca, modelo, serial, sede_id, observaciones
        FROM registros WHERE id = %s
    """, (id,))
    registro = cur.fetchone()

    cur.execute("SELECT id, nombre FROM sedes ORDER BY nombre")
    sedes = cur.fetchall()

    cur.close()
    conn.close()

    return render_template('editar.html', registro=registro, sedes=sedes)

@app.route('/eliminar/<int:rid>', methods=['POST'])
def eliminar(rid):
    if 'usuario' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    c.execute("DELETE FROM mantenimiento WHERE id=%s", (rid,))
    conn.commit()
    conn.close()
    flash('Registro eliminado', 'info')
    return redirect(url_for('principal'))

@app.route('/consultar/exportar')
def exportar_consulta():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM mantenimiento")
    registros = c.fetchall()
    conn.close()

    if not registros:
        flash('No hay registros para exportar', 'warning')
        return redirect(url_for('consultar'))

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Mantenimiento"
    encabezados = list(registros[0].keys())
    ws.append(encabezados)
    for row in registros:
        ws.append(list(row.values()))
    bio = BytesIO()
    wb.save(bio)
    bio.seek(0)

    return send_file(bio, as_attachment=True, download_name='Mantenimiento_Consulta.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/acta/<int:rid>')
def generar_acta(rid):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM mantenimiento WHERE id=%s", (rid,))
    registro = c.fetchone()
    conn.close()

    if not registro:
        flash('Registro no encontrado', 'warning')
        return redirect(url_for('principal'))

    buffer = BytesIO()
    c_pdf = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    # Margenes y posiciones
    x_margin = 50
    y = height - 50
    line_height = 18
    box_padding = 5
    c_pdf.setFont("Helvetica-Bold", 16)

    # Título
    c_pdf.drawCentredString(width/2, y, f"Acta de Mantenimiento - Registro ID: {registro['id']}")
    y -= 40
    c_pdf.setFont("Helvetica-Bold", 12)

    # Campos a mostrar
    campos = [
        ('Sede', registro['sede']),
        ('Fecha', registro['fecha']),
        ('Área', registro['area']),
        ('Técnico', registro['tecnico']),
        ('Nombre Máquina', registro['nombre_maquina']),
        ('Usuario', registro['usuario']),
        ('Tipo Equipo', registro['tipo_equipo']),
        ('Marca', registro['marca']),
        ('Modelo', registro['modelo']),
        ('Serial', registro['serial']),
        ('Sistema Operativo', registro['sistema_operativo']),
        ('Office', registro['office']),
        ('Antivirus', registro['antivirus']),
        ('Compresor', registro['compresor']),
        ('Control Remoto', registro['control_remoto']),
        ('Activo Fijo', registro['activo_fijo']),
        ('Observaciones', registro['observaciones'])
    ]

    # Dibujar cada campo en un cuadro
    for titulo, valor in campos:
        if y < 80:  # Nueva página si se acaba el espacio
            c_pdf.showPage()
            y = height - 50
            c_pdf.setFont("Helvetica-Bold", 12)

        # Título del campo
        c_pdf.setFont("Helvetica-Bold", 12)
        c_pdf.drawString(x_margin, y, titulo + ":")
        y -= line_height

        # Valor del campo, ajustando líneas largas
        c_pdf.setFont("Helvetica", 12)
        for line in textwrap.wrap(str(valor), width=90):
            c_pdf.drawString(x_margin + 15, y, line)
            y -= line_height

        # Línea separadora
        c_pdf.setStrokeColor(colors.grey)
        c_pdf.line(x_margin, y + box_padding, width - x_margin, y + box_padding)
        y -= 10

    c_pdf.showPage()
    c_pdf.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"Acta_Registro_{registro['id']}.pdf",
        mimetype='application/pdf'
    )

@app.route('/consultar')
def consultar():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()

    # Búsqueda y filtro (igual que principal)
    search = request.args.get('q','').strip()
    sede_filter = request.args.get('sede','Todas')
    query = "SELECT * FROM mantenimiento WHERE 1=1"
    params = []
    if search:
        like = f"%{search}%"
        query += """ AND (sede ILIKE %s OR area ILIKE %s OR tecnico ILIKE %s OR nombre_maquina ILIKE %s 
                     OR usuario ILIKE %s OR tipo_equipo ILIKE %s OR marca ILIKE %s OR modelo ILIKE %s 
                     OR serial ILIKE %s OR sistema_operativo ILIKE %s OR office ILIKE %s OR antivirus ILIKE %s 
                     OR compresor ILIKE %s OR control_remoto ILIKE %s OR activo_fijo ILIKE %s OR observaciones ILIKE %s)"""
        params += [like]*16
    if sede_filter and sede_filter != 'Todas':
        query += " AND sede = %s"
        params.append(sede_filter)
    query += " ORDER BY id DESC"
    c.execute(query, params)
    registros = c.fetchall()
    conn.close()

    sedes = ["Todas","Nivel Central","Barranquilla","Soledad","Santa Marta","El Banco",
             "Monteria","Sincelejo","Valledupar","El Carmen de Bolivar","Magangue"]

    return render_template('consultar.html', registros=registros, sedes=sedes,
                           search=search, sede_filter=sede_filter, nombre=session.get('nombre'))

# -----------------------
# Main
# -----------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
