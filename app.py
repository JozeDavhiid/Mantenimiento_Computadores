import os
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file
import psycopg2
from psycopg2.extras import RealDictCursor
import openpyxl
from io import BytesIO
from datetime import date
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

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
            request.form.get('nombre_maquina','').upper(),
            request.form.get('usuario_equipo',''),
            request.form.get('tipo_equipo',''),
            request.form.get('marca','').upper(),
            request.form.get('modelo','').upper(),
            request.form.get('serial','').upper(),
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
        flash('Registro guardado correctamente', 'success')

    # Búsqueda y filtros
    search = request.args.get('q','').strip()
    sede_filter = request.args.get('sede','Todas')
    query = "SELECT * FROM mantenimiento WHERE 1=1"
    params = []
    if search:
        like = f"%{search}%"
        query += """ AND (sede ILIKE %s OR area ILIKE %s OR tecnico ILIKE %s OR nombre_maquina ILIKE %s 
                     OR usuario ILIKE %s OR tipo_equipo ILIKE %s OR marca ILIKE %s OR modelo ILIKE %s 
                     OR serial ILIKE %s OR observaciones ILIKE %s)"""
        params += [like]*10
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

@app.route('/obtener_registro/<int:rid>')
def obtener_registro(rid):
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

    return render_template('editar.html', registro=registro)

@app.route('/actualizar/<int:rid>', methods=['POST'])
def actualizar_registro(rid):
    if 'usuario' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    c.execute('''UPDATE mantenimiento SET
                 sede=%s,
                 fecha=%s,
                 area=%s,
                 tecnico=%s,
                 nombre_maquina=%s,
                 usuario=%s,
                 tipo_equipo=%s,
                 marca=%s,
                 modelo=%s,
                 serial=%s,
                 sistema_operativo=%s,
                 office=%s,
                 antivirus=%s,
                 compresor=%s,
                 control_remoto=%s,
                 activo_fijo=%s,
                 observaciones=%s
                 WHERE id=%s''',
              (
                  request.form.get('sede'),
                  request.form.get('fecha'),
                  request.form.get('area'),
                  request.form.get('tecnico'),
                  request.form.get('nombre_maquina', '').upper(),
                  request.form.get('usuario_equipo'),
                  request.form.get('tipo_equipo'),
                  request.form.get('marca', '').upper(),
                  request.form.get('modelo', '').upper(),
                  request.form.get('serial', '').upper(),
                  request.form.get('so'),
                  request.form.get('office'),
                  request.form.get('antivirus'),
                  request.form.get('compresor'),
                  request.form.get('control_remoto'),
                  request.form.get('activo_fijo'),
                  request.form.get('observaciones'),
                  rid
              ))
    conn.commit()
    conn.close()

    flash('Registro actualizado correctamente', 'success')
    return redirect(url_for('principal'))

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

@app.route('/exportar')
def exportar():
    if 'usuario' not in session:
        return redirect(url_for('login'))
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM mantenimiento")
    registros = c.fetchall()
    conn.close()

    if not registros:
        flash('No hay registros para exportar', 'warning')
        return redirect(url_for('principal'))

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

    return send_file(bio, as_attachment=True, download_name='Mantenimiento.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')

@app.route('/acta/<int:rid>')
def acta_pdf(rid):
    conn = get_db_connection()
    registro = conn.execute('SELECT * FROM registros WHERE id = %s', (rid,)).fetchone()
    conn.close()

    if not registro:
        return "Registro no encontrado", 404

    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4)
    elements = []

    styles = getSampleStyleSheet()
    elements.append(Paragraph("<b>ACTA DE MANTENIMIENTO</b>", styles["Title"]))
    elements.append(Spacer(1, 12))

    data = [
        ['Campo', 'Valor'],
        ('Sede', registro['sede']),
        ('Fecha', str(registro['fecha'])),
        ('Encargado', registro['encargado']),
        ('Nombre', registro['nombre']),
        ('Cargo', registro['cargo']),
        ('Serial', registro['serial']),
        ('Procesador', registro['procesador']),
        ('Disco Duro', registro['disco_duro']),
        ('RAM', registro['ram']),
        ('Sistema Operativo', registro['sistema_operativo']),
        ('Tareas Realizadas', registro['tareas']),
        ('Estado', registro['estado']),
        ('Observaciones', registro['observaciones']),
    ]

    table = Table(data, colWidths=[150, 350])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
        ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ]))
    elements.append(table)

    doc.build(elements)
    pdf = buffer.getvalue()
    buffer.close()

    return Response(pdf, mimetype='application/pdf',
                    headers={'Content-Disposition': f'inline; filename=acta_{rid}.pdf'})

@app.route('/consultar')
def consultar():
    if 'usuario' not in session:
        return redirect(url_for('login'))

    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT * FROM mantenimiento ORDER BY id DESC")
    registros = c.fetchall()
    conn.close()

    return render_template('consultar.html', registros=registros)

# -----------------------
# Main
# -----------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
