# app.py (completo)
import os
import re
import secrets
from io import BytesIO
from datetime import datetime, timedelta, date
from functools import wraps

# Flask
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file

# PostgreSQL (psycopg3)
import psycopg
from psycopg.rows import dict_row
from psycopg import errors as psycopg_errors

# Archivos Excel
import openpyxl

# PDF (ReportLab)
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib.units import inch
from reportlab.lib import colors

# Envío de correos (SendGrid)
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
    conn = psycopg.connect(DB_URL, autocommit=False, row_factory=dict_row)
    return conn

# -----------------------
# Inicializar DB (asegura tablas/columnas)
# -----------------------
def init_db():
    """Inicializa la base de datos (crea tablas y restricciones si no existen, pero sin insertar datos base)."""
    conn = get_db_connection()
    c = conn.cursor()

    # Crear tabla de empresas (si no existe)
    c.execute("""
        CREATE TABLE IF NOT EXISTS empresas (
            id SERIAL PRIMARY KEY,
            nombre VARCHAR(100) UNIQUE NOT NULL
        );
    """)

    # Crear tabla de ciclos
    c.execute("""
        CREATE TABLE IF NOT EXISTS ciclos (
            id SERIAL PRIMARY KEY,
            nombre VARCHAR(100) NOT NULL,
            trimestre INT,
            anio INT,
            fecha_inicio DATE,
            fecha_cierre DATE,
            observaciones TEXT,
            activo BOOLEAN DEFAULT FALSE,
            empresa_id INT REFERENCES empresas(id) ON DELETE CASCADE
        );
    """)

    # Crear restricción única (nombre + empresa_id)
    c.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint WHERE conname = 'unique_nombre_empresa'
            ) THEN
                ALTER TABLE ciclos ADD CONSTRAINT unique_nombre_empresa UNIQUE (nombre, empresa_id);
            END IF;
        END $$;
    """)

    # Crear tabla de técnicos si no existe
    c.execute("""
        CREATE TABLE IF NOT EXISTS tecnicos (
            id SERIAL PRIMARY KEY,
            usuario VARCHAR(50) UNIQUE NOT NULL,
            nombre VARCHAR(100) NOT NULL,
            correo VARCHAR(100) UNIQUE NOT NULL,
            contrasena VARCHAR(100) NOT NULL,
            rol VARCHAR(20) DEFAULT 'tecnico'
        );
    """)

    # Crear tabla de mantenimientos si no existe
    c.execute("""
        CREATE TABLE IF NOT EXISTS mantenimiento (
            id SERIAL PRIMARY KEY,
            sede VARCHAR(100),
            fecha DATE,
            area VARCHAR(100),
            tecnico VARCHAR(100),
            nombre_maquina VARCHAR(100),
            usuario VARCHAR(100),
            tipo_equipo VARCHAR(100),
            marca VARCHAR(100),
            modelo VARCHAR(100),
            serial VARCHAR(100),
            sistema_operativo VARCHAR(100),
            office VARCHAR(100),
            antivirus VARCHAR(100),
            compresor VARCHAR(100),
            control_remoto VARCHAR(100),
            activo_fijo VARCHAR(100),
            observaciones TEXT,
            cerrado BOOLEAN DEFAULT FALSE,
            ciclo_id INT REFERENCES ciclos(id) ON DELETE SET NULL,
            empresa_id INT REFERENCES empresas(id) ON DELETE SET NULL
        );
    """)

    # Tabla de recuperación de contraseñas
    c.execute("""
        CREATE TABLE IF NOT EXISTS password_resets (
            id SERIAL PRIMARY KEY,
            usuario VARCHAR(50) REFERENCES tecnicos(usuario) ON DELETE CASCADE,
            token VARCHAR(255) UNIQUE NOT NULL,
            expires_at TIMESTAMP NOT NULL
        );
    """)

    conn.commit()
    conn.close()
    print("✅ Base de datos inicializada correctamente (sin empresa base).")

# Ejecutar init al iniciar la app
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
# Helpers relacionados a empresas/ciclos
# -----------------------
def get_active_cycle(conn=None, empresa_id=None):
    """Devuelve el ciclo activo (dict) o None — tiene en cuenta empresa_id si se pasa."""
    close_conn = False
    if conn is None:
        conn = get_db_connection()
        close_conn = True
    c = conn.cursor()
    if empresa_id:
        c.execute("SELECT * FROM ciclos WHERE activo=TRUE AND empresa_id=%s ORDER BY id DESC LIMIT 1", (empresa_id,))
    else:
        c.execute("SELECT * FROM ciclos WHERE activo=TRUE ORDER BY id DESC LIMIT 1")
    ciclo = c.fetchone()
    if close_conn:
        conn.close()
    return ciclo

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
    conn = get_db_connection()
    c = conn.cursor()

    # 🔹 Obtener listado de empresas para mostrar en el select
    c.execute("SELECT id, nombre FROM empresas ORDER BY nombre ASC")
    empresas = c.fetchall()

    if request.method == 'POST':
        usuario = request.form['usuario'].strip()
        contrasena = request.form['contrasena'].strip()
        empresa_id = request.form.get('empresa_id')

        # Validar datos
        if not usuario or not contrasena or not empresa_id:
            flash("Debes completar todos los campos, incluyendo la empresa.", "warning")
            conn.close()
            return render_template("login.html", empresas=empresas)

        # Buscar usuario
        c.execute("SELECT usuario, nombre, correo, contrasena, rol FROM tecnicos WHERE usuario=%s", (usuario,))
        row = c.fetchone()

        if row and row['contrasena'] == contrasena:
            # Guardar datos de sesión
            session['usuario'] = row['usuario']
            session['nombre'] = row['nombre']
            session['rol'] = row.get('rol', 'tecnico')
            session['empresa_id'] = int(empresa_id)  # 🔹 Guardamos empresa actual

            # Obtener nombre de empresa para mostrar en mensajes o panel
            c.execute("SELECT nombre FROM empresas WHERE id=%s", (empresa_id,))
            empresa = c.fetchone()
            session['empresa_nombre'] = empresa['nombre'] if empresa else 'Sin empresa'

            conn.close()
            return redirect(url_for('principal'))

        conn.close()
        flash('Usuario o contraseña incorrectos', 'danger')
        return render_template('login.html', empresas=empresas)

    conn.close()
    return render_template('login.html', empresas=empresas)

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
    expires_at_dt = datetime.fromisoformat(expires_at) if isinstance(expires_at, str) else expires_at

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
# ADMINISTRACIÓN DE CICLOS (solo admin)
# -----------------------
@app.route('/admin_ciclos', methods=['GET', 'POST'])
@admin_required
def admin_ciclos():
    conn = get_db_connection()
    c = conn.cursor()

    # 🔹 Obtener lista de empresas
    c.execute("SELECT id, nombre FROM empresas ORDER BY nombre")
    empresas = c.fetchall()

    # 🔹 Empresa seleccionada (por GET o POST)
    empresa_seleccionada = request.args.get('empresa_id') or request.form.get('empresa_id')
    empresa_seleccionada = int(empresa_seleccionada) if empresa_seleccionada else None

    hoy = date.today().isoformat()

    # ==============================
    # Crear nuevo ciclo
    # ==============================
    if request.method == 'POST' and request.form.get('action') == 'nuevo':
        if not empresa_seleccionada:
            flash('⚠️ Debes seleccionar una empresa antes de crear un ciclo.', 'warning')
            conn.close()
            return redirect(url_for('admin_ciclos'))

        # Cerrar ciclo activo previo de esa empresa
        c.execute("""
            UPDATE ciclos 
            SET activo = FALSE, fecha_cierre = %s 
            WHERE activo = TRUE AND empresa_id = %s
        """, (date.today(), empresa_seleccionada))

        nombre = request.form.get('nombre', f"Ciclo {date.today().strftime('%b %Y')}")
        trimestre = request.form.get('trimestre', 1)
        anio = request.form.get('anio', date.today().year)
        fecha_inicio = request.form.get('fecha_inicio', date.today())
        observaciones = request.form.get('observaciones', '')

        c.execute("""
            INSERT INTO ciclos (nombre, trimestre, anio, fecha_inicio, observaciones, activo, empresa_id)
            VALUES (%s, %s, %s, %s, %s, TRUE, %s)
        """, (nombre, trimestre, anio, fecha_inicio, observaciones, empresa_seleccionada))

        conn.commit()
        conn.close()
        flash('✅ Nuevo ciclo creado correctamente.', 'success')
        return redirect(url_for('admin_ciclos', empresa_id=empresa_seleccionada))

    # ==============================
    # Cerrar ciclo activo
    # ==============================
    if request.method == 'POST' and request.form.get('action') == 'cerrar':
        if not empresa_seleccionada:
            flash('⚠️ Selecciona una empresa para cerrar su ciclo activo.', 'warning')
            conn.close()
            return redirect(url_for('admin_ciclos'))

        c.execute("""
            SELECT id FROM ciclos 
            WHERE activo = TRUE AND empresa_id = %s 
            ORDER BY id DESC LIMIT 1
        """, (empresa_seleccionada,))
        ciclo_activo = c.fetchone()

        if ciclo_activo:
            c.execute("""
                UPDATE ciclos 
                SET activo = FALSE, fecha_cierre = %s 
                WHERE id = %s
            """, (date.today(), ciclo_activo['id']))
            c.execute("""
                UPDATE mantenimiento 
                SET cerrado = TRUE 
                WHERE ciclo_id = %s
            """, (ciclo_activo['id'],))
            conn.commit()
            flash('🔒 Ciclo cerrado exitosamente.', 'info')
        else:
            flash('⚠️ No hay ciclo activo para cerrar en esta empresa.', 'warning')

        conn.close()
        return redirect(url_for('admin_ciclos', empresa_id=empresa_seleccionada))

    # ==============================
    # Mostrar los ciclos de la empresa seleccionada
    # ==============================
    if empresa_seleccionada:
        c.execute("""
            SELECT * FROM ciclos 
            WHERE empresa_id = %s 
            ORDER BY id DESC
        """, (empresa_seleccionada,))
        ciclos = c.fetchall()
    else:
        ciclos = []

    conn.close()

    return render_template(
        'admin_ciclos.html',
        empresas=empresas,
        empresa_seleccionada=empresa_seleccionada,
        ciclos=ciclos,
        hoy=hoy
    )

@app.route('/admin/ciclos/asociar/<int:ciclo_id>', methods=['POST'])
@admin_required
def asociar_mantenimientos_a_ciclo(ciclo_id):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM ciclos WHERE id=%s", (ciclo_id,))
    ciclo = c.fetchone()
    if not ciclo:
        conn.close()
        flash("El ciclo seleccionado no existe.", "danger")
        return redirect(url_for('admin_ciclos'))

    # Sólo asociar mantenimientos que pertenezcan a la misma empresa o que no tengan empresa asignada
    c.execute("SELECT COUNT(*) FROM mantenimiento WHERE ciclo_id IS NULL AND (empresa_id IS NULL OR empresa_id=%s)", (ciclo['empresa_id'],))
    total_sin_ciclo = c.fetchone()['count']
    if total_sin_ciclo == 0:
        conn.close()
        flash("No hay mantenimientos pendientes por asociar para esta empresa.", "info")
        return redirect(url_for('admin_ciclos'))

    c.execute("UPDATE mantenimiento SET ciclo_id=%s, empresa_id=%s WHERE ciclo_id IS NULL AND (empresa_id IS NULL OR empresa_id=%s)",
              (ciclo_id, ciclo['empresa_id'], ciclo['empresa_id']))
    conn.commit()
    conn.close()
    flash(f"{total_sin_ciclo} mantenimientos asociados al ciclo '{ciclo['nombre']}'.", "success")
    return redirect(url_for('admin_ciclos'))

# -----------------------
# Resto de rutas (principal, CRUD mantenimiento, export, acta)
# -----------------------
@app.route('/principal', methods=['GET', 'POST'])
@login_required
def principal():
    conn = get_db_connection()
    c = conn.cursor()

    # Obtener todos los ciclos de la empresa de la sesión (si aplica)
    empresa_id_session = session.get('empresa_id')
    c.execute("SELECT * FROM ciclos WHERE empresa_id=%s ORDER BY id DESC", (empresa_id_session,)) if empresa_id_session else c.execute("SELECT * FROM ciclos ORDER BY id DESC")
    ciclos = c.fetchall()

    # Ciclo activo para la empresa de la sesión
    ciclo_activo = get_active_cycle(conn, empresa_id=empresa_id_session)

    # Permitir al admin seleccionar un ciclo para ver (GET param)
    ciclo_id_param = request.args.get('ciclo_id', type=int)
    ciclo_seleccionado = None
    if ciclo_id_param:
        c.execute("SELECT * FROM ciclos WHERE id=%s", (ciclo_id_param,))
        ciclo_seleccionado = c.fetchone()
        # aseguramos que el ciclo seleccionado pertenezca a la misma empresa de la sesión o a ninguna si admin no seleccionó empresa
        if ciclo_seleccionado and empresa_id_session and ciclo_seleccionado.get('empresa_id') != empresa_id_session:
            ciclo_seleccionado = None

    if not ciclo_seleccionado:
        ciclo_seleccionado = ciclo_activo

    # Guardar mantenimiento
    if request.method == 'POST' and request.form.get('action') == 'guardar':
        if not ciclo_activo:
            flash('No hay un ciclo activo. Contacta al administrador.', 'warning')
            conn.close()
            return redirect(url_for('principal'))

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
            request.form.get('observaciones', ''),
            ciclo_activo['id'],
            empresa_id_session
        )
        c.execute('''INSERT INTO mantenimiento
                    (sede, fecha, area, tecnico, nombre_maquina, usuario, tipo_equipo, marca, modelo, serial,
                     sistema_operativo, office, antivirus, compresor, control_remoto, activo_fijo, observaciones, ciclo_id, empresa_id)
                     VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''', datos)
        conn.commit()
        flash('Registro guardado correctamente', 'success')

    # Determinar ciclo para consultas
    ciclo_para_consultar = ciclo_seleccionado['id'] if ciclo_seleccionado else None

    # Últimos registros (filtrados por empresa y ciclo si corresponde)
    if ciclo_para_consultar:
        c.execute("SELECT * FROM mantenimiento WHERE ciclo_id=%s ORDER BY id DESC LIMIT 10", (ciclo_para_consultar,))
    elif empresa_id_session:
        c.execute("SELECT * FROM mantenimiento WHERE empresa_id=%s ORDER BY id DESC LIMIT 10", (empresa_id_session,))
    else:
        c.execute("SELECT * FROM mantenimiento ORDER BY id DESC LIMIT 10")
    registros = c.fetchall()

    # Estadísticas (filtradas)
    def stats_filter_query(where_clause, params):
        c.execute(where_clause, params)
        return c.fetchall()

    if ciclo_para_consultar:
        cid = ciclo_para_consultar
        c.execute("SELECT COUNT(*) AS total FROM mantenimiento WHERE ciclo_id=%s", (cid,))
        total_mantenimientos = c.fetchone()['total']

        c.execute("SELECT COUNT(DISTINCT tecnico) AS total_tecnicos FROM mantenimiento WHERE ciclo_id=%s", (cid,))
        total_tecnicos = c.fetchone()['total_tecnicos']

        mes_actual = date.today().strftime("%Y-%m")
        c.execute("SELECT COUNT(*) AS total_mes FROM mantenimiento WHERE ciclo_id=%s AND fecha LIKE %s", (cid, f"{mes_actual}%"))
        mantenimientos_mes = c.fetchone()['total_mes']

        c.execute("""SELECT tipo_equipo, COUNT(*) AS cantidad 
                     FROM mantenimiento 
                     WHERE ciclo_id=%s
                     GROUP BY tipo_equipo 
                     ORDER BY cantidad DESC LIMIT 1""", (cid,))
        equipo_mas_comun = c.fetchone()
        equipo_mas_comun = equipo_mas_comun['tipo_equipo'] if equipo_mas_comun else 'N/A'

        c.execute("SELECT marca, COUNT(*) FROM mantenimiento WHERE ciclo_id=%s GROUP BY marca ORDER BY COUNT(*) DESC LIMIT 6", (cid,))
        marcas_data = c.fetchall()
        marca_labels = [r['marca'] for r in marcas_data]
        marca_counts = [r['count'] for r in marcas_data]
        marca_mas_comun = marcas_data[0]['marca'] if marcas_data else 'N/A'

        c.execute("SELECT sede, COUNT(*) FROM mantenimiento WHERE ciclo_id=%s GROUP BY sede ORDER BY sede", (cid,))
        sedes_data = c.fetchall()
        sede_labels = [r['sede'] for r in sedes_data]
        sede_counts = [r['count'] for r in sedes_data]

        c.execute("SELECT tipo_equipo, COUNT(*) FROM mantenimiento WHERE ciclo_id=%s GROUP BY tipo_equipo", (cid,))
        equipos_data = c.fetchall()
        equipo_labels = [r['tipo_equipo'] for r in equipos_data]
        equipo_counts = [r['count'] for r in equipos_data]

        c.execute("""SELECT TO_CHAR(TO_DATE(fecha, 'YYYY-MM-DD'), 'Mon') AS mes, COUNT(*) 
                     FROM mantenimiento 
                     WHERE ciclo_id=%s AND fecha IS NOT NULL
                     GROUP BY mes 
                     ORDER BY MIN(fecha)""", (cid,))
        meses_data = c.fetchall()
        meses_labels = [r['mes'] for r in meses_data]
        meses_counts = [r['count'] for r in meses_data]
    elif empresa_id_session:
        eid = empresa_id_session
        c.execute("SELECT COUNT(*) AS total FROM mantenimiento WHERE empresa_id=%s", (eid,))
        total_mantenimientos = c.fetchone()['total']

        c.execute("SELECT COUNT(DISTINCT tecnico) AS total_tecnicos FROM mantenimiento WHERE empresa_id=%s", (eid,))
        total_tecnicos = c.fetchone()['total_tecnicos']

        mes_actual = date.today().strftime("%Y-%m")
        c.execute("SELECT COUNT(*) AS total_mes FROM mantenimiento WHERE empresa_id=%s AND fecha LIKE %s", (eid, f"{mes_actual}%"))
        mantenimientos_mes = c.fetchone()['total_mes']

        c.execute("""SELECT tipo_equipo, COUNT(*) AS cantidad 
                     FROM mantenimiento 
                     WHERE empresa_id=%s
                     GROUP BY tipo_equipo 
                     ORDER BY cantidad DESC LIMIT 1""", (eid,))
        equipo_mas_comun = c.fetchone()
        equipo_mas_comun = equipo_mas_comun['tipo_equipo'] if equipo_mas_comun else 'N/A'

        c.execute("SELECT marca, COUNT(*) FROM mantenimiento WHERE empresa_id=%s GROUP BY marca ORDER BY COUNT(*) DESC LIMIT 6", (eid,))
        marcas_data = c.fetchall()
        marca_labels = [r['marca'] for r in marcas_data]
        marca_counts = [r['count'] for r in marcas_data]
        marca_mas_comun = marcas_data[0]['marca'] if marcas_data else 'N/A'

        c.execute("SELECT sede, COUNT(*) FROM mantenimiento WHERE empresa_id=%s GROUP BY sede ORDER BY sede", (eid,))
        sedes_data = c.fetchall()
        sede_labels = [r['sede'] for r in sedes_data]
        sede_counts = [r['count'] for r in sedes_data]

        c.execute("SELECT tipo_equipo, COUNT(*) FROM mantenimiento WHERE empresa_id=%s GROUP BY tipo_equipo", (eid,))
        equipos_data = c.fetchall()
        equipo_labels = [r['tipo_equipo'] for r in equipos_data]
        equipo_counts = [r['count'] for r in equipos_data]

        c.execute("""SELECT TO_CHAR(TO_DATE(fecha, 'YYYY-MM-DD'), 'Mon') AS mes, COUNT(*) 
                     FROM mantenimiento 
                     WHERE empresa_id=%s AND fecha IS NOT NULL
                     GROUP BY mes 
                     ORDER BY MIN(fecha)""", (eid,))
        meses_data = c.fetchall()
        meses_labels = [r['mes'] for r in meses_data]
        meses_counts = [r['count'] for r in meses_data]
    else:
        # global (sin filtro de empresa)
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
                           ciclos=ciclos,
                           ciclo_activo=ciclo_activo,
                           ciclo_seleccionado=ciclo_seleccionado,
                           total_mantenimientos=total_mantenimientos,
                           total_tecnicos=total_tecnicos,
                           mantenimientos_mes=mantenimientos_mes,
                           equipo_mas_comun=equipo_mas_comun,
                           marca_mas_comun=marca_mas_comun,
                           empresa_nombre=session.get('empresa_nombre'),
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

    # Aplicar filtro por empresa de sesión
    empresa_id_session = session.get('empresa_id')

    query = "SELECT * FROM mantenimiento WHERE 1=1"
    params = []

    if empresa_id_session:
        query += " AND empresa_id=%s"
        params.append(empresa_id_session)

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
                           empresa_nombre=session.get('empresa_nombre'),
                           nombre=session.get('nombre'),
                           total_pages=total_pages)

@app.route('/obtener_registro/<int:rid>')
@login_required
def obtener_registro(rid):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("SELECT * FROM mantenimiento WHERE id=%s", (rid,))
    registro = c.fetchone()

    # comprobar si registro pertenece a ciclo cerrado
    if registro and registro.get('ciclo_id'):
        c.execute("SELECT activo FROM ciclos WHERE id=%s", (registro['ciclo_id'],))
        ciclo = c.fetchone()
        if not ciclo or not ciclo['activo']:
            registro['cerrado'] = True
        else:
            registro['cerrado'] = registro.get('cerrado', False)

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
    c.execute("SELECT ciclo_id, cerrado FROM mantenimiento WHERE id=%s", (rid,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash('Registro no encontrado', 'warning')
        return redirect(url_for('principal'))

    ciclo_id = row.get('ciclo_id')
    if row.get('cerrado'):
        conn.close()
        flash('Este registro pertenece a un ciclo cerrado y no se puede modificar.', 'warning')
        return redirect(url_for('principal'))
    if ciclo_id:
        c.execute("SELECT activo FROM ciclos WHERE id=%s", (ciclo_id,))
        ciclo = c.fetchone()
        if not ciclo or not ciclo['activo']:
            conn.close()
            flash('Este registro pertenece a un ciclo cerrado y no se puede modificar.', 'warning')
            return redirect(url_for('principal'))

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
    c.execute("SELECT ciclo_id, cerrado FROM mantenimiento WHERE id=%s", (rid,))
    row = c.fetchone()
    if not row:
        conn.close()
        flash('Registro no encontrado', 'warning')
        return redirect(url_for('principal'))

    if row.get('cerrado'):
        conn.close()
        flash('No se puede eliminar un registro de un ciclo cerrado.', 'warning')
        return redirect(url_for('principal'))

    if row.get('ciclo_id'):
        c.execute("SELECT activo FROM ciclos WHERE id=%s", (row['ciclo_id'],))
        ciclo = c.fetchone()
        if not ciclo or not ciclo['activo']:
            conn.close()
            flash('No se puede eliminar un registro de un ciclo cerrado.', 'warning')
            return redirect(url_for('principal'))

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

    # Si hay empresa en sesión, exportar solo esa empresa
    empresa_id_session = session.get('empresa_id')
    if empresa_id_session:
        c.execute("SELECT * FROM mantenimiento WHERE empresa_id=%s ORDER BY fecha DESC", (empresa_id_session,))
    else:
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

    # Encabezado profesional (sin logo por ahora)
    c_pdf.setFont("Helvetica-Bold", 16)
    c_pdf.drawString(50, height - 50, "ACTA DE MANTENIMIENTO TÉCNICO")
    c_pdf.setFont("Helvetica", 10)
    c_pdf.drawString(50, height - 70, f"ID: {registro['id']}    Fecha emisión: {date.today().isoformat()}")
    c_pdf.line(50, height - 75, width - 50, height - 75)

    # Datos generales
    y = height - 95
    c_pdf.setFont("Helvetica-Bold", 12)
    c_pdf.drawString(50, y, "I. DATOS GENERALES")
    y -= 18
    c_pdf.setFont("Helvetica", 11)
    c_pdf.drawString(60, y, f"Sede: {registro.get('sede','N/A')}")
    y -= 15
    c_pdf.drawString(60, y, f"Área: {registro.get('area','N/A')}")
    y -= 15
    c_pdf.drawString(60, y, f"Técnico responsable: {registro.get('tecnico','N/A')}")
    y -= 15
    c_pdf.drawString(60, y, f"Fecha del mantenimiento: {registro.get('fecha','N/A')}")

    # Datos del equipo
    y -= 25
    c_pdf.setFont("Helvetica-Bold", 12)
    c_pdf.drawString(50, y, "II. DATOS DEL EQUIPO")
    y -= 18
    c_pdf.setFont("Helvetica", 11)
    equipo_datos = [
        ("Nombre del equipo", registro.get('nombre_maquina')),
        ("Usuario", registro.get('usuario')),
        ("Tipo", registro.get('tipo_equipo')),
        ("Marca", registro.get('marca')),
        ("Modelo", registro.get('modelo')),
        ("Serial", registro.get('serial')),
        ("Activo fijo", registro.get('activo_fijo')),
    ]
    for campo, valor in equipo_datos:
        c_pdf.drawString(60, y, f"{campo}: {valor or 'N/A'}")
        y -= 15
        if y < 100:
            c_pdf.showPage()
            y = height - 100

    # Software
    y -= 15
    c_pdf.setFont("Helvetica-Bold", 12)
    c_pdf.drawString(50, y, "III. SOFTWARE Y HERRAMIENTAS")
    y -= 18
    c_pdf.setFont("Helvetica", 11)
    c_pdf.drawString(60, y, f"Sistema Operativo: {registro.get('sistema_operativo','N/A')}")
    y -= 15
    c_pdf.drawString(60, y, f"Office: {registro.get('office','N/A')}")
    y -= 15
    c_pdf.drawString(60, y, f"Antivirus: {registro.get('antivirus','N/A')}")
    y -= 15
    c_pdf.drawString(60, y, f"Compresor: {registro.get('compresor','N/A')}")
    y -= 15
    c_pdf.drawString(60, y, f"Control Remoto: {registro.get('control_remoto','N/A')}")

    # Observaciones
    y -= 25
    c_pdf.setFont("Helvetica-Bold", 12)
    c_pdf.drawString(50, y, "IV. OBSERVACIONES")
    y -= 18
    c_pdf.setFont("Helvetica", 11)
    texto = registro.get('observaciones') or "Sin observaciones."
    for linea in texto.splitlines():
        c_pdf.drawString(60, y, linea)
        y -= 15
        if y < 100:
            c_pdf.showPage()
            y = height - 100

    # Firmas
    y -= 40
    c_pdf.setFont("Helvetica-Bold", 12)
    c_pdf.drawString(50, y, "V. FIRMAS")
    y -= 60
    c_pdf.line(100, y, 250, y)
    c_pdf.line(350, y, 500, y)
    y -= 12
    c_pdf.setFont("Helvetica", 10)
    c_pdf.drawString(120, y, "Técnico responsable")
    c_pdf.drawString(390, y, "Usuario del equipo")

    # Pie
    c_pdf.setFont("Helvetica-Oblique", 9)
    c_pdf.setFillColor(colors.grey)
    c_pdf.drawString(50, 40, "Sistema de Gestión de Mantenimiento - Informe Técnico Generado Automáticamente")
    c_pdf.setFillColor(colors.black)

    c_pdf.save()
    buffer.seek(0)

    return send_file(buffer, as_attachment=True,
                     download_name=f"Acta_Mantenimiento_{registro['id']}.pdf",
                     mimetype='application/pdf')

# Ver ciclo detalle
@app.route('/ver_ciclo/<int:ciclo_id>')
@admin_required
def ver_ciclo(ciclo_id):
    conn = get_db_connection()
    c = conn.cursor()

    # Obtener ciclo
    c.execute("SELECT * FROM ciclos WHERE id=%s", (ciclo_id,))
    ciclo = c.fetchone()

    if not ciclo:
        conn.close()
        flash('Ciclo no encontrado', 'warning')
        return redirect(url_for('admin_ciclos'))

    # Obtener empresa asociada (si existe)
    empresa = None
    if 'empresa_id' in ciclo and ciclo['empresa_id']:
        c.execute("SELECT * FROM empresas WHERE id=%s", (ciclo['empresa_id'],))
        empresa = c.fetchone()

    # Obtener mantenimientos del ciclo
    c.execute("SELECT * FROM mantenimiento WHERE ciclo_id=%s ORDER BY fecha ASC", (ciclo_id,))
    registros = c.fetchall()

    conn.close()

    return render_template('ver_ciclo.html', ciclo=ciclo, registros=registros, empresa=empresa)

# Editar ciclo (solo admin y solo si está abierto)
@app.route('/editar_ciclo/<int:ciclo_id>', methods=['GET', 'POST'])
@login_required
def editar_ciclo(ciclo_id):
    conn = get_db_connection()
    c = conn.cursor()

    # Obtener datos del ciclo
    c.execute("""
        SELECT c.*, e.nombre AS empresa_nombre
        FROM ciclos c
        LEFT JOIN empresas e ON c.empresa_id = e.id
        WHERE c.id = %s
    """, (ciclo_id,))
    ciclo = c.fetchone()

    if not ciclo:
        flash('Ciclo no encontrado.', 'danger')
        conn.close()
        return redirect(url_for('admin_ciclos'))

    # Verificar si el ciclo está cerrado
    if not ciclo['activo']:
        flash('No se puede editar un ciclo cerrado.', 'warning')
        conn.close()
        return redirect(url_for('admin_ciclos'))

    # Obtener lista de empresas para el selector
    c.execute("SELECT id, nombre FROM empresas ORDER BY nombre")
    empresas = c.fetchall()

    # Si el formulario fue enviado (POST)
    if request.method == 'POST':
        nombre = request.form.get('nombre', '').strip()
        trimestre = request.form.get('trimestre', None)
        anio = request.form.get('anio', None)
        fecha_inicio = request.form.get('fecha_inicio', None)
        fecha_cierre = request.form.get('fecha_cierre', None)
        observaciones = request.form.get('observaciones', '').strip()
        empresa_id = request.form.get('empresa_id')

        # Validaciones mínimas
        if not trimestre or not anio or not fecha_inicio:
            flash('Por favor completa los campos obligatorios.', 'warning')
            conn.close()
            return render_template('editar_ciclo.html', ciclo=ciclo, empresas=empresas)

        # Actualizar ciclo
        c.execute("""
            UPDATE ciclos
            SET nombre=%s, trimestre=%s, anio=%s, fecha_inicio=%s, fecha_cierre=%s,
                observaciones=%s, empresa_id=%s
            WHERE id=%s
        """, (nombre, trimestre, anio, fecha_inicio, fecha_cierre, observaciones, empresa_id, ciclo_id))

        conn.commit()
        conn.close()
        flash('Ciclo actualizado correctamente.', 'success')
        return redirect(url_for('admin_ciclos'))

    conn.close()
    return render_template('editar_ciclo.html', ciclo=ciclo, empresas=empresas)

# -----------------------
# Main
# -----------------------
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)
