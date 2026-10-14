import os
from datetime import datetime
from dotenv import load_dotenv
from google.adk.agents.llm_agent import Agent

# Cargar variables de entorno tanto de la raíz como de la carpeta del agente
load_dotenv(os.path.join(os.path.dirname(__file__), '.env'))
load_dotenv()

def leer_archivo_local(ruta_archivo: str) -> str:
    """Lee el contenido de un archivo de código local dada su ruta completa o relativa."""
    try:
        with open(ruta_archivo, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error al leer el archivo {ruta_archivo}: {str(e)}"

def listar_archivos_proyecto(ruta_directorio: str) -> str:
    """Lista los archivos de código dentro de una carpeta, ignorando carpetas pesadas como node_modules o .git."""
    ignorar = {'.git', 'node_modules', '__pycache__', '.next', 'dist', 'build', '.adk', 'venv'}
    archivos_encontrados = []
    try:
        for raiz, dirs, archivos in os.walk(ruta_directorio):
            dirs[:] = [d for d in dirs if d not in ignorar]
            for archivo in archivos:
                if not archivo.startswith('.'):
                    archivos_encontrados.append(os.path.join(raiz, archivo))
        return "\n".join(archivos_encontrados) if archivos_encontrados else "No se encontraron archivos."
    except Exception as e:
        return f"Error al explorar el directorio {ruta_directorio}: {str(e)}"

def guardar_reporte_md(ruta_directorio_proyecto: str, contenido: str) -> str:
    """Guarda el informe de auditoría en un archivo Markdown (.md) dentro del directorio del proyecto con formato aud_<nombre_proyecto>_aaaammdd_hhmmss.md."""
    try:
        # Limpiar la ruta y extraer automáticamente el nombre de la carpeta del proyecto
        ruta_limpia = os.path.normpath(ruta_directorio_proyecto)
        if os.path.isfile(ruta_limpia):
            ruta_limpia = os.path.dirname(ruta_limpia)
            
        nombre_proyecto = os.path.basename(ruta_limpia)
        
        # Generar fecha y hora actual en formato aaaammdd_hhmmss
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Construir el nombre final del archivo
        nombre_archivo = f"aud_{nombre_proyecto}_{timestamp}.md"
        ruta_completa = os.path.join(ruta_limpia, nombre_archivo)
        
        with open(ruta_completa, 'w', encoding='utf-8') as f:
            f.write(contenido)
            
        return f"Reporte guardado exitosamente en: {ruta_completa}"
    except Exception as e:
        return f"Error al guardar el reporte: {str(e)}"

root_agent = Agent(
    model='gemini-4-argon',
    name='code_auditor_agent',
    description='Auditor técnico de código enfocado en seguridad, rendimiento y buenas prácticas.',
    instruction='''Eres un Ingeniero de Software Senior y Auditor de Código estricto pero constructivo.

FLUJO DE TRABAJO OBLIGATORIO (NO TE SALTES NINGÚN PASO):
Paso 1: Usa `listar_archivos_proyecto` para ver los archivos de la carpeta indicada.
Paso 2: Usa `leer_archivo_local` para leer los archivos principales de código.
Paso 3 (OBLIGATORIO): ANTES de dar tu respuesta final al usuario, DEBES invocar la herramienta `guardar_reporte_md` pasándole la `ruta_directorio_proyecto` y el informe completo en `contenido`. Está prohibido terminar el turno sin haber ejecutado `guardar_reporte_md`.
Paso 4: Muestra el informe en el chat e indícale al usuario la ruta exacta del archivo .md que acabas de crear.

Analiza siempre bajo estos 4 pilares:
1. Seguridad (credenciales expuestas, inyecciones, validación de datos, permisos).
2. Rendimiento y Escalabilidad (cuellos de botella, consultas innecesarias, manejo de memoria o asincronía).
3. Buenas Prácticas y Limpieza (legibilidad, modularidad, manejo de errores try/catch, tipado).
4. Bugs potenciales o casos borde no contemplados.

Formato del informe:
- **Resumen Ejecutivo**: Estado general del código en 2 líneas.
- **Hallazgos**: Clasificados por severidad ([CRÍTICO], [MEDIO], [MEJORA]).
- **Código Refactorizado**: Muestra exactamente cómo debe quedar el bloque corregido.''',
    tools=[leer_archivo_local, listar_archivos_proyecto, guardar_reporte_md]
)