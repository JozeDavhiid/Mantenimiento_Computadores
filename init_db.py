# Script opcional para inicializar la base de datos localmente
import sqlite3
DB_NAME = 'mantenimiento.db'
conn = sqlite3.connect(DB_NAME)
c = conn.cursor()
c.execute('''CREATE TABLE IF NOT EXISTS mantenimiento (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
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
c.execute('''CREATE TABLE IF NOT EXISTS tecnicos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                usuario TEXT UNIQUE,
                nombre TEXT,
                contrasena TEXT
            )''')
c.execute("SELECT * FROM tecnicos WHERE usuario='admin'")
if not c.fetchone():
    c.execute("INSERT INTO tecnicos (usuario, nombre, contrasena) VALUES (?, ?, ?)",
              ('admin', 'Administrador', '1234'))
conn.commit()
conn.close()
print("Base de datos inicializada:", DB_NAME)