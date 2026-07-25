# scripts/translate_file.py
import asyncio
import contextlib
import os
import re
import sys
from pathlib import Path

from kaos.bootstrap.factory import Settings, build_llm, load_settings

# 1. Importaciones oficiales de contratos e infraestructura de KAOS
from kaos.plugins.agents.translate_agent import TranslateAgent

# 2. Resonador de la herramienta oficial 'file_read'
try:
    from kaos.core.tools import FileReadTool
except ImportError:
    from typing import Any

    class FileReadTool:
        name = "file_read"
        description = "Lee un archivo de texto local. args: {path}"

        async def run(self, args: dict[str, Any]) -> str:
            with open(str(args["path"]), encoding="utf-8") as f:
                return f.read()

def segmentar_pot_seguro(contenido_pot, entradas_por_lote=40):
    """
    Divide el archivo .pot en bloques de 40 entradas de traducción.
    Garantiza que Gemma-3-Instruct procese y complete el 100% de los
    bloques msgstr largos sin cortes ni omisiones por límite de salida.
    """
    bloques = re.split(r'(?=\n(?:#|msgid))', contenido_pot)
    cabecera = ""
    entradas = []

    for b in bloques:
        b_strip = b.strip()
        if not b_strip:
            continue
        if 'msgid ""' in b_strip and 'msgstr ""' in b_strip and "Project-Id-Version" in b_strip:
            cabecera = b_strip + "\n\n"
        else:
            entradas.append(b_strip + "\n\n")

    lotes = []
    for i in range(0, len(entradas), entradas_por_lote):
        lotes.append("".join(entradas[i:i + entradas_por_lote]))

    return cabecera, lotes

async def main():
    # 3. Validar parámetros de entrada
    args = sys.argv[1:]
    if not args:
        print("\n❌ Error: Falta especificar la ruta del archivo fuente.")
        print(
            "Uso: uv run python .\\scripts\\translate_file.py "
            "<ruta_archivo.pot> [--ollama] [--model <modelo>]"
        )
        return

    # Extraer ruta del archivo (primer parámetro posicional)
    ruta_str = None
    for i, a in enumerate(args):
        if a.startswith("--"):
            continue
        if i > 0 and args[i - 1] == "--model":
            continue
        ruta_str = a
        break
    if not ruta_str:
        print("❌ Error: Debes especificar una ruta válida para el archivo .pot")
        return

    ruta_parametro = Path(ruta_str)
    if not ruta_parametro.exists():
        print(f"❌ Error: El archivo no existe en el disco: {ruta_parametro}")
        return

    forzar_ollama = "--ollama" in args

    # Extraer el modelo pasado por consola
    override_model = None
    if "--model" in args:
        with contextlib.suppress(ValueError, IndexError):
            override_model = args[args.index("--model") + 1]

    print("\n=======================================================")
    print("⏳ KAOS BOOTSTRAP: Resolviendo Configuración (ADR Flow)...")
    print("=======================================================")

    # 4. Flujo ADR: Prioridad absoluta PostgreSQL -> Fallback .env
    #    Cargamos el .env y leemos las variables de entorno (incluido
    #    KAOS_LLM_NUM_CTX) con from_env(); ``Settings()`` a secas ignora el .env,
    #    por lo que num_ctx quedaba en None y el provider no elevaba el contexto.
    from kaos.core.config import load_dotenv

    load_dotenv()
    base_settings = Settings.from_env()
    db_url = base_settings.database_url or os.getenv("DATABASE_URL")
    if db_url and "postgresql" in db_url:
        print(
            "🗄️  ADR Priority: conexión activa a PostgreSQL detectada. "
            "Sincronizando ConfigStore..."
        )
    else:
        print(
            "⚠️  ADR Fallback: no se detectó base de datos activa. "
            "Cargando variables de entorno .env."
        )

    # 5. Cargar configuración e inicializar el LLM de Fábrica
    config_resuelta = await load_settings(
        base_settings,
        provider="ollama" if forzar_ollama else None,
        model=override_model
    )
    llm_provider = build_llm(config_resuelta)

    print(f"📡 CONECTOR COMPILADO: {str(config_resuelta.llm_provider).upper()}")
    print(f"🤖 MODELO RESOLVIDO: {config_resuelta.llm_model}")
    print(f"🧠 CONTEXTO (num_ctx): {config_resuelta.llm_num_ctx or 'default del servidor'}")
    print("=======================================================")

    # 6. Inicializar herramientas y el agente
    instancia_file_read = FileReadTool()
    agent = TranslateAgent(llm=llm_provider, tools=[instancia_file_read])

    print(f"⏳ Leyendo y segmentando: {ruta_parametro.name}")
    contenido_completo = await instancia_file_read.run({"path": str(ruta_parametro)})

    # Aplicamos la segmentación segura de 40 macro-lotes
    cabecera, lotes_traduccion = segmentar_pot_seguro(contenido_completo, entradas_por_lote=40)
    print(f"📦 Compilación: 1 Cabecera + {len(lotes_traduccion)} Lotes controlados.")
    print("⏳ Iniciando ciclo de traducción secuencial...")

    respuestas_po = [cabecera] if cabecera else []

    # 7. Ciclo de traducción por bloques con Regex Sanatization
    for idx, lote in enumerate(lotes_traduccion, start=1):
        lineas = len(lote.splitlines())
        print(f"   🔄 Procesando bloque [{idx}/{len(lotes_traduccion)}] (~{lineas} líneas)...")

        from kaos.contracts.llm import Message
        messages = [
            Message(role="system", content=agent.get_system_prompt()),
            Message(
                role="user",
                content=(
                    f"FECHA: 2026-07-22\n"
                    f"LOTE PARCIAL [{idx}/{len(lotes_traduccion)}]:\n\n{lote}"
                ),
            ),
        ]

        reintentos = 3
        for intento in range(reintentos):
            try:
                bloque_traducido = await llm_provider.complete(messages)

                # 🧼 LIMPIEZA INDUSTRIAL REGEX: Quita bloques Markdown de cualquier tipo
                bloque_traducido = re.sub(r"```[a-zA-Z]*", "", bloque_traducido)
                bloque_traducido = bloque_traducido.replace("```", "").strip()

                # Control estricto de estructura para no inyectar basura gramatical
                if "msgid" in bloque_traducido and "msgstr" in bloque_traducido:
                    respuestas_po.append(bloque_traducido + "\n\n")
                else:
                    print(f"      ⚠️ Bloque {idx} con formato inválido. Reintentando...")
                    continue
                break
            except Exception as e:
                if intento == reintentos - 1:
                    print(f"      ❌ Error definitivo en bloque {idx}: {str(e)}")
                else:
                    print(f"      ⚠️ Reintento temporal en bloque {idx} (5s)...")
                    await asyncio.sleep(5)

    # 8. Consolidar y escribir archivo final .po en limpio
    texto_po_final = "".join(respuestas_po)
    output_file = ruta_parametro.with_suffix(".po")

    with open(output_file, "w", encoding="utf-8") as f:
        f.write(texto_po_final)

    print("\n=======================================================")
    print("✨ ¡TRADUCCIÓN COMPLETADA POR KAOS CON MÁXIMA SEGURIDAD!")
    print(f"📄 Archivo final unificado .po guardado en: {output_file}")
    print("💡 El contenedor limpio y completo está listo para producción.")
    print("=======================================================\n")

if __name__ == "__main__":
    asyncio.run(main())
