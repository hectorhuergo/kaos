# scripts/translate_all.py
import asyncio
import re
import sys
from pathlib import Path

from kaos.bootstrap.factory import Settings, build_llm, load_settings

# Importaciones oficiales de KAOS
from kaos.plugins.agents.translate_agent import TranslateAgent

# Modelo local por defecto (override con ``--model <nombre>``).
DEFAULT_MODEL = "DeepSeek-Coder-V2-Lite-Instruct-Q4_K_M-GGUF-Q4_K_M"

# Directorio de trabajo por defecto (relativo al cwd, override con ``--dir``).
DEFAULT_TARGET_DIR = Path("uploads/proyecto-g/Translate")

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

def segmentar_pot_maximo(contenido_pot, entradas_por_lote=180):
    """
    Divide el .pot optimizando el tamaño al límite de los 4096 tokens.
    180 entradas msgid equivalen a ~3300 tokens, ideal para el contexto local.
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

async def procesar_archivo(ruta_file, llm_provider, agent, instancia_file_read):
    output_file = ruta_file.with_suffix(".po")

    if output_file.exists():
        print(f"skip: {ruta_file.name} ya cuenta con traducción.")
        return

    print("\n=======================================================")
    print(f"⏳ MAX-BATCH PROCESANDO: {ruta_file.name}")
    print("=======================================================")

    contenido_completo = await instancia_file_read.run({"path": str(ruta_file)})

    # 🚀 Segmentación optimizada a 180 entradas por bloque para exprimir el contexto
    cabecera, lotes_traduccion = segmentar_pot_maximo(contenido_completo, entradas_por_lote=60)

    print(f"📦 Compilación optimizada: 1 Cabecera + {len(lotes_traduccion)} Macro-lotes.")

    respuestas_po = [cabecera] if cabecera else []

    for idx, lote in enumerate(lotes_traduccion, start=1):
        lineas_bloque = len(lote.splitlines())
        print(
            f"   ↳ Inferencia macro-bloque [{idx}/{len(lotes_traduccion)}] "
            f"(~{lineas_bloque} líneas)..."
        )

        from kaos.contracts.llm import Message
        messages = [
            Message(role="system", content=agent.get_system_prompt()),
            Message(role="user", content=f"FECHA: 2026-07-22\nLOTE:\n\n{lote}")
        ]

        reintentos = 3
        for intento in range(reintentos):
            try:
                bloque_traducido = await llm_provider.complete(messages)

                # LIMPIEZA: elimina cualquier bloque Markdown (```...```)
                bloque_traducido = re.sub(r"```[a-zA-Z]*", "", bloque_traducido)
                bloque_traducido = bloque_traducido.replace("```", "").strip()

                # Asegurar que no concatene textos explicativos genéricos del modelo
                if "msgid" in bloque_traducido and "msgstr" in bloque_traducido:
                    respuestas_po.append(bloque_traducido + "\n\n")
                else:
                    print(
                        f"   ⚠️ Advertencia en bloque {idx}: el modelo devolvió "
                        "texto plano en vez de Gettext. Reintentando..."
                    )
                break
            except Exception as e:
                if intento == reintentos - 1:
                    print(f"   ❌ Error en macro-bloque {idx}: {str(e)}.")
                else:
                    print(f"   ⚠️ Reintentando macro-bloque {idx} por latencia en 5s...")
                    await asyncio.sleep(5)

    with open(output_file, "w", encoding="utf-8") as f:
        f.write("".join(respuestas_po))
    print(f"✅ TRADUCCIÓN MASIVA GENERADA: {output_file.name}")

async def main():
    args = sys.argv[1:]
    forzar_ollama = "--ollama" in args
    override_model = (
        args[args.index("--model") + 1] if "--model" in args else DEFAULT_MODEL
    )

    print("\n=======================================================")
    print("🚀 PIPELINE INDUSTRIAL DE LOCALIZACIÓN ODOO (KAOS-CORE)")
    print("=======================================================")

    # Load .env and read env vars (KAOS_LLM_NUM_CTX, etc.) so the script honours
    # the same configuration as the CLI. ``Settings()`` alone ignores the .env.
    from kaos.core.config import load_dotenv

    load_dotenv()
    base_settings = Settings.from_env()
    config_resuelta = await load_settings(
        base_settings,
        provider="ollama" if forzar_ollama else None,
        model=override_model,
    )
    llm_provider = build_llm(config_resuelta)
    print(f"🧠 CONTEXTO (num_ctx): {config_resuelta.llm_num_ctx or 'default del servidor'}")
    instancia_file_read = FileReadTool()
    agent = TranslateAgent(llm=llm_provider, tools=[instancia_file_read])

    target_dir = Path(args[args.index("--dir") + 1]) if "--dir" in args else DEFAULT_TARGET_DIR

    if not target_dir.exists():
        print(f"❌ Error en ADR de almacenamiento: {target_dir}")
        return

    archivos_pot = list(target_dir.glob("**/*.pot"))
    print(f"📂 En cola de producción: {len(archivos_pot)} módulos detectados.")

    for path_pot in archivos_pot:
        try:
            await procesar_archivo(path_pot, llm_provider, agent, instancia_file_read)
        except Exception as e:
            print(f"💥 Error en {path_pot.name}: {str(e)}")
            continue

    print("\n=======================================================")
    print("🎉 PIPELINE FINALIZADO. TODOS LOS ARCHIVOS .PO LISTOS EN DISCO.")
    print("=======================================================\n")

if __name__ == "__main__":
    asyncio.run(main())
