import os
import re
import secrets
from datetime import datetime, timedelta, date
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file

# psycopg3
import psycopg
from psycopg.rows import dict_row
from psycopg import errors as psycopg_errors

import openpyxl
from io import BytesIO
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

# SendGrid
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

# -----------------------
# Configuración / SendGrid desde variables de entorno
# -----------------------
DB_URL = os.environ.get('DATABASE_URL')
if not DB_URL:
    raise ValueError("Debes configurar DATABASE_URL como variable de entorno con la URL de PostgreSQL de Render")

SECRET_KEY = os.environ.get('SECRET_KEY', 'clave_secreta_local')
SENDGRID_API_KEY = os.environ.get('SENDGRID_API_KEY')   # <-- tu API key de SendGrid
SENDGRID_FROM = os.environ.get('SENDGRID_FROM') or os.environ.get('SMTP_FROM')  # correo remitente

app = Flask(__name__)
app.secret_key = SECRET_KEY


# -----------------------
# Función conexión DB (psycopg3) - devuelve conexión con row_factory dict_row
# -----------------------
def get_db_connection():
    # psycopg.connect soporta URL de conexión PostgreSQL
    # usamos row_factory=dict_row para que fetchone/fetchall devuelvan dicts
    conn = psycopg.connect(DB_URL, autocommit=False, row_factory=dict_row)
    return conn


# -----------------------
# Inicializar DB (asegura columnas/tabla reset)
# -----------------------
def init_db():
    conn = get_db_connection()
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
    # Tabla tecnicos (añadimos columna correo si no existe y rol)
    c.execute('''CREATE TABLE IF NOT EXISTS tecnicos (
                    id SERIAL PRIMARY KEY,
                    usuario TEXT UNIQUE,
                    nombre TEXT,
                    correo TEXT UNIQUE,
                    contrasena TEXT,
                    rol TEXT DEFAULT 'tecnico'
                )''')
    # tabla para tokens de recuperación
    c.execute('''CREATE TABLE IF NOT EXISTS password_resets (
                    id SERIAL PRIMARY KEY,
                    usuario TEXT,
                    token TEXT UNIQUE,
                    expires_at TIMESTAMP
                )''')
    # Usuario admin por defecto (si no existe)
    c.execute("SELECT * FROM tecnicos WHERE usuario='admin'")
    if not c.fetchone():
        # contraseña en texto plano por compatibilidad (puedes cambiarla luego)
        c.execute("INSERT INTO tecnicos (usuario, nombre, correo, contrasena, rol) VALUES (%s,%s,%s,%s,%s)",
                  ('admin', 'Administrador', 'admin@example.com', '1234', 'admin'))
    conn.commit()
    conn.close()


with app.app_context():
    init_db()


# -----------------------
# Decoradores utilitarios
# -----------------------
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'usuario' not in session:
            flash('Debes iniciar sesión', 'warning')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'usuario' not in session or session.get('rol') != 'admin':
            flash('Acceso denegado: solo administradores', 'danger')
            return redirect(url_for('principal') if 'usuario' in session else url_for('login'))
        return f(*args, **kwargs)
    return decorated


# -----------------------
# Util: enviar correo mediante SendGrid API
# -----------------------
def send_email(to_email: str, subject: str, body: str, html_content: str = None):
    """
    Envía correo usando la API de SendGrid.
    Requiere la variable de entorno SENDGRID_API_KEY y SENDGRID_FROM.
    Si html_content se pasa, se enviará contenido HTML además del plain text.
    """
    if not SENDGRID_API_KEY or not SENDGRID_FROM:
        app.logger.error("SendGrid no está configurado (falta SENDGRID_API_KEY o SENDGRID_FROM).")
        raise RuntimeError("SendGrid no configurado")

    message = Mail(
        from_email=SENDGRID_FROM,
        to_emails=to_email,
        subject=subject,
        plain_text_content=body
    )
    if html_content:
        message.html = html_content

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        resp = sg.send(message)
        app.logger.info(f"SendGrid response: {resp.status_code}")
        return resp.status_code
    except Exception:
        app.logger.exception("Error enviando correo con SendGrid")
        raise


# -----------------------
# Rutas principales
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

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT usuario, nombre, correo, contrasena, rol FROM tecnicos WHERE usuario=%s", (usuario,))
        row = c.fetchone()
        conn.close()

        # COMPARACIÓN EN TEXTO PLANO (según petición)
        if row and row['contrasena'] == contrasena:
            session['usuario'] = row['usuario']
            session['nombre'] = row['nombre']
            session['rol'] = row.get('rol', 'tecnico') if isinstance(row, dict) else 'tecnico'
            flash(f'Bienvenido {row["nombre"]}', 'success')
            return redirect(url_for('principal'))
        flash('Usuario o contraseña incorrectos', 'danger')
    return render_template('login.html')


@app.route('/registro', methods=['GET', 'POST'])
@admin_required
def registro():
    if request.method == 'POST':
        usuario = request.form['usuario'].strip()
        nombre = request.form['nombre'].strip()
        correo = request.form['correo'].strip()
        contrasena = request.form['contrasena'].strip()
        rol = request.form.get('rol', 'tecnico').strip()

        # validaciones
        if not usuario or not nombre or not correo or not contrasena:
            flash('Complete todos los campos', 'warning')
            return redirect(url_for('registro'))

        patron_correo = r'^[^@]+@[^@]+\.[^@]+$'
        if not re.match(patron_correo, correo):
            flash('Formato de correo inválido', 'warning')
            return redirect(url_for('registro'))

        conn = get_db_connection()
        c = conn.cursor()
        try:
            c.execute("""INSERT INTO tecnicos (usuario, nombre, correo, contrasena, rol)
                         VALUES (%s, %s, %s, %s, %s)""",
                      (usuario, nombre, correo, contrasena, rol))
            conn.commit()
            flash('Técnico registrado correctamente', 'success')
            return redirect(url_for('principal'))
        except psycopg_errors.UniqueViolation:
            conn.rollback()
            flash('El usuario o correo ya existe', 'warning')
        except Exception:
            conn.rollback()
            app.logger.exception("Error registrando técnico")
            flash('Error al registrar técnico', 'danger')
        finally:
            conn.close()
    return render_template('registro.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))


# -----------------------
# Recuperación por correo (SendGrid)
# -----------------------
@app.route('/recuperar', methods=['GET', 'POST'])
def recuperar():
    if request.method == 'POST':
        usuario = request.form['usuario'].strip()
        if not usuario:
            flash('Ingresa tu usuario', 'warning')
            return redirect(url_for('recuperar'))

        conn = get_db_connection()
        c = conn.cursor()
        c.execute("SELECT correo FROM tecnicos WHERE usuario=%s", (usuario,))
        row = c.fetchone()
        if not row:
            conn.close()
            flash('Usuario no encontrado', 'danger')
            return redirect(url_for('recuperar'))

        correo = row['correo']
        token = secrets.token_urlsafe(32)
        expires_at = datetime.utcnow() + timedelta(hours=1)
        try:
            c.execute("INSERT INTO password_resets (usuario, token, expires_at) VALUES (%s,%s,%s)",
                      (usuario, token, expires_at))
            conn.commit()
        except Exception:
            conn.rollback()
            app.logger.exception("Error guardando token de recuperación")
            flash('Error interno, intenta de nuevo', 'danger')
            conn.close()
            return redirect(url_for('recuperar'))
        conn.close()

        base = request.host_url.rstrip('/')
        link = f"{base}{url_for('recuperar_confirm')}?token={token}"

        subject = "Recuperación de contraseña - Mantenimiento"
        body = f"""Hola {usuario},

Se solicitó restablecer la contraseña de tu cuenta. Haz clic en el enlace a continuación para crear una nueva contraseña.
El enlace expira en 1 hora.

{link}

Si no solicitaste este cambio, ignora este correo.

Saludos,
Admin - Sistema de Mantenimiento
"""
        # Opcional: HTML más bonito
        html_body = f"""
        <p>Hola <b>{usuario}</b>,</p>
        <p>Se solicitó restablecer la contraseña de tu cuenta. Haz clic en el siguiente enlace para crear una nueva contraseña (expira en 1 hora):</p>
        <p><a href="{link}">{link}</a></p>
        <p>Si no solicitaste este cambio, ignora este correo.</p>
        <p>Saludos,<br>Admin - Sistema de Mantenimiento</p>
        """

        try:
            send_email(correo, subject, body, html_content=html_body)
            flash('Se ha enviado un correo con las instrucciones. Revisa tu bandeja.', 'info')
        except Exception:
            app.logger.exception("Error enviando correo de recuperación")
            flash('No se pudo enviar el correo. Consulta la configuración de SendGrid.', 'danger')
        return redirect(url_for('login'))

    return render_template('recuperar.html')


@app.route('/recuperar/confirm', methods=['GET', 'POST'])
def recuperar_confirm():
    token = request.args.get('token') or request.form.get('token')
    if not token:
        flash('Token inválido', 'danger')
        return redirect(url_for('recuperar'))

    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT usuario, expires_at FROM password_resets WHERE token=%s", (token,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash('Token inválido o ya usado', 'danger')
        return redirect(url_for('recuperar'))

    expires_at = row['expires_at']
    if isinstance(expires_at, str):
        expires_at_dt = datetime.fromisoformat(expires_at)
    else:
        expires_at_dt = expires_at

    if datetime.utcnow() > expires_at_dt:
        c.execute("DELETE FROM password_resets WHERE token=%s", (token,))
        conn.commit()
        conn.close()
        flash('Token expirado. Solicita recuperar de nuevo.', 'warning')
        return redirect(url_for('recuperar'))

    if request.method == 'POST':
        nueva = request.form['nueva_contrasena'].strip()
        confirmar = request.form['confirmar_contrasena'].strip()
        if not nueva or not confirmar:
            flash('Complete ambos campos', 'warning')
            return redirect(url_for('recuperar_confirm') + f"?token={token}")
        if nueva != confirmar:
            flash('Las contraseñas no coinciden', 'warning')
            return redirect(url_for('recuperar_confirm') + f"?token={token}")

        usuario = row['usuario']
        try:
            c.execute("UPDATE tecnicos SET contrasena=%s WHERE usuario=%s", (nueva, usuario))
            c.execute("DELETE FROM password_resets WHERE token=%s", (token,))
            conn.commit()
        except Exception:
            conn.rollback()
            app.logger.exception("Error actualizando contraseña")
            flash('Error interno, intenta de nuevo', 'danger')
            conn.close()
            return redirect(url_for('recuperar'))
        conn.close()
        flash('Contraseña actualizada correctamente ✅', 'success')
        return redirect(url_for('login'))

    conn.close()
    return render_template('recuperar_confirm.html', token=token)


# -----------------------
# Resto de rutas (principal, CRUD mantenimiento, export, acta)
# -----------------------
@app.route('/principal', methods=['GET', 'POST'])
@login_required
def principal():
    conn = get_db_connection()
    c = conn.cursor()

    if request.method == 'POST' and request.form.get('action') == 'guardar':
        datos = (
            request.form.get('sede', ''),
            request.form.get('fecha', date.today().isoformat()),
            request.form.get('area', ''),
            session.get('nombre', ''),
            request.form.get('nombre_maquina', '').upper(),
            request.form.get('usuario_equipo', ''),
            request.form.get('tipo_equipo', ''),
            request.form.get('marca', '').upper(),
            request.form.get('modelo', '').upper(),
            request.form.get('serial', '').upper(),
            request.form.get('so', ''),
            request.form.get('office', ''),
            request.form.get('antivirus', ''),
            request.form.get('compresor', ''),
            request.form.get('control_remoto', ''),
            request.form.get('activo_fijo', ''),
            request.form.get('observaciones', '')
        )
        c.execute('''INSERT INTO mantenimiento
                    (sede, fecha, area, tecnico, nombre_maquina, usuario, tipo_equipo, marca, modelo, serial,
                     sistema_operativo, office, antivirus, compresor, control_remoto, activo_fijo, observaciones)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''', datos)
        conn.commit()
        flash('Registro guardado correctamente', 'success')

    # Últimos registros
    c.execute("SELECT * FROM mantenimiento ORDER BY id DESC LIMIT 10")
    registros = c.fetchall()

    # Dashboard
    c.execute("SELECT COUNT(*) AS total FROM mantenimiento")
    total_mantenimientos = c.fetchone()['total']

    c.execute("SELECT COUNT(DISTINCT tecnico) AS total_tecnicos FROM mantenimiento")
    total_tecnicos = c.fetchone()['total_tecnicos']

    mes_actual = date.today().strftime("%Y-%m")
    c.execute("SELECT COUNT(*) AS total_mes FROM mantenimiento WHERE fecha LIKE %s", (f"{mes_actual}%",))
    mantenimientos_mes = c.fetchone()['total_mes']

    c.execute("""SELECT tipo_equipo, COUNT(*) AS cantidad 
                 FROM mantenimiento 
                 GROUP BY tipo_equipo 
                 ORDER BY cantidad DESC LIMIT 1""")
    equipo_mas_comun = c.fetchone()
    equipo_mas_comun = equipo_mas_comun['tipo_equipo'] if equipo_mas_comun else 'N/A'

    c.execute("SELECT marca, COUNT(*) FROM mantenimiento GROUP BY marca ORDER BY COUNT(*) DESC LIMIT 6")
    marcas_data = c.fetchall()
    marca_labels = [r['marca'] for r in marcas_data]
    marca_counts = [r['count'] for r in marcas_data]
    marca_mas_comun = marcas_data[0]['marca'] if marcas_data else 'N/A'

    c.execute("SELECT sede, COUNT(*) FROM mantenimiento GROUP BY sede ORDER BY sede")
    sedes_data = c.fetchall()
    sede_labels = [r['sede'] for r in sedes_data]
    sede_counts = [r['count'] for r in sedes_data]

    c.execute("SELECT tipo_equipo, COUNT(*) FROM mantenimiento GROUP BY tipo_equipo")
    equipos_data = c.fetchall()
    equipo_labels = [r['tipo_equipo'] for r in equipos_data]
    equipo_counts = [r['count'] for r in equipos_data]

    c.execute("""SELECT TO_CHAR(TO_DATE(fecha, 'YYYY-MM-DD'), 'Mon') AS mes, COUNT(*) 
                 FROM mantenimiento 
                 WHERE fecha IS NOT NULL
                 GROUP BY mes 
                 ORDER BY MIN(fecha)""")
    meses_data = c.fetchall()
    meses_labels = [r['mes'] for r in meses_data]
    meses_counts = [r['count'] for r in meses_data]

    conn.close()

    return render_template('principal.html',
                       registros=registros,
                       nombre=session.get('nombre'),
                       rol=session.get('rol'),
                       hoy=date.today().isoformat(),
                       total_mantenimientos=total_mantenimientos,
                       total_tecnicos=total_tecnicos,
                       mantenimientos_mes=mantenimientos_mes,
                       equipo_mas_comun=equipo_mas_comun,
                       marca_mas_comun=marca_mas_comun,
                       sede_labels=sede_labels,
                       sede_counts=sede_counts,
                       equipo_labels=equipo_labels,
                       equipo_counts=equipo_counts,
                       marca_labels=marca_labels,
                       marca_counts=marca_counts,
                       meses_labels=meses_labels,
                       meses_counts=meses_counts)


@app.route('/consultar_registro')
@login_required
def consultar():
    search = request.args.get('q', '').strip()
    sede_filter = request.args.get('sede', 'Todas')
    page = int(request.args.get('page', 1))
    per_page = 20
    offset = (page - 1) * per_page

    conn = get_db_connection()
    c = conn.cursor()

    query = "SELECT * FROM mantenimiento WHERE 1=1"
    params = []

    if search:
        like = f"%{search}%"
        query += """ AND (
            sede ILIKE %s OR area ILIKE %s OR tecnico ILIKE %s OR nombre_maquina ILIKE %s OR
            usuario ILIKE %s OR tipo_equipo ILIKE %s OR marca ILIKE %s OR modelo ILIKE %s OR
            serial ILIKE %s OR observaciones ILIKE %s
        )"""
        params += [like] * 10

    if sede_filter and sede_filter != 'Todas':
        query += " AND sede = %s"
        params.append(sede_filter)

    count_query = f"SELECT COUNT(*) FROM ({query}) AS subquery"
    c.execute(count_query, params)
    total = c.fetchone()['count']
    total_pages = (total + per_page - 1) // per_page

    query += " ORDER BY fecha ASC LIMIT %s OFFSET %s"
    params += [per_page, offset]
    c.execute(query, params)
    registros = c.fetchall()
    conn.close()

    sedes = ["Todas", "Nivel Central", "Barranquilla", "Soledad", "Santa Marta",
             "El Banco", "Monteria", "Sincelejo", "Valledupar",
             "El Carmen de Bolivar", "Magangue"]

    return render_template('consultar.html',
                           registros=registros,
                           search=search,
                           sede_filter=sede_filter,
                           sedes=sedes,
                           page=page,
                           total_pages=total_pages)


@app.route('/obtener_registro/<int:rid>')
@login_required
def obtener_registro(rid):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM mantenimiento WHERE id=%s", (rid,))
    registro = c.fetchone()
    conn.close()

    if not registro:
        flash('Registro no encontrado', 'warning')
        return redirect(url_for('principal'))

    return render_template('editar.html', registro=registro)


@app.route('/actualizar/<int:rid>', methods=['POST'])
@login_required
def actualizar_registro(rid):
    conn = get_db_connection()
    c = conn.cursor()
    campos = [
        'sede', 'fecha', 'area', 'nombre_maquina', 'usuario_equipo', 'tipo_equipo',
        'marca', 'modelo', 'serial', 'so', 'office', 'antivirus',
        'compresor', 'control_remoto', 'activo_fijo', 'observaciones'
    ]
    valores = [request.form.get(campo, '') for campo in campos]

    c.execute('''UPDATE mantenimiento SET
                 sede=%s, fecha=%s, area=%s, nombre_maquina=%s, usuario=%s, tipo_equipo=%s, 
                 marca=%s, modelo=%s, serial=%s, sistema_operativo=%s, office=%s, antivirus=%s,
                 compresor=%s, control_remoto=%s, activo_fijo=%s, observaciones=%s
                 WHERE id=%s''', (*valores, rid))
    conn.commit()
    conn.close()

    flash('✅ Registro actualizado correctamente', 'success')
    return redirect(url_for('principal'))


@app.route('/eliminar/<int:rid>', methods=['POST'])
@admin_required
def eliminar(rid):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM mantenimiento WHERE id=%s", (rid,))
    conn.commit()
    conn.close()
    flash('Registro eliminado', 'info')
    return redirect(url_for('principal'))


@app.route('/exportar')
@admin_required
def exportar():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM mantenimiento ORDER BY fecha DESC")
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

    return send_file(bio, as_attachment=True,
                     download_name='Mantenimiento.xlsx',
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')


@app.route('/acta/<int:rid>')
@login_required
def acta_pdf(rid):
    conn = get_db_connection()
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

    # Encabezado más profesional
    c_pdf.setFont("Helvetica-Bold", 16)
    c_pdf.drawString(50, height - 50, "ACTA DE MANTENIMIENTO")
    c_pdf.setFont("Helvetica", 10)
    c_pdf.drawString(50, height - 70, f"ID: {registro['id']}    Fecha generación: {date.today().isoformat()}")
    c_pdf.line(50, height - 75, width - 50, height - 75)

    y = height - 95
    c_pdf.setFont("Helvetica", 12)

    for k, v in registro.items():
        texto = f"{k.replace('_',' ').title()}: {v}"
        # rompemos en líneas de 100 caracteres para evitar desbordes
        for linea in [texto[i:i+100] for i in range(0, len(texto), 100)]:
            c_pdf.drawString(50, y, linea)
            y -= 15
            if y < 50:
                c_pdf.showPage()
                # reproducir encabezado reducido en nueva página
                c_pdf.setFont("Helvetica-Bold", 14)
                c_pdf.drawString(50, height - 40, "ACTA DE MANTENIMIENTO (continuación)")
                c_pdf.setFont("Helvetica", 12)
                y = height - 70

    c_pdf.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f"Acta_Registro_{registro['id']}.pdf",
                     mimetype='application/pdf')


# -----------------------
# Main
# -----------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
