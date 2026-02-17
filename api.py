from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
import uvicorn
import azure_utils

# --- Importa aquí tus funciones del otro archivo ---
# from mi_modulo_azure import programacion_fija, programacion_continua

app = FastAPI(title="Azure Scheduler API")

# Modelo de datos según tu especificación
class InputModel(BaseModel): 
    accountid: str
    aws_region: str
    begin_monthdays: int
    begin_time: str
    begin_year: int
    desired_capacity: int
    end_monthdays: int
    end_time: str
    end_year: int
    label: str
    months: str
    num_case: str
    program_type: str  # 'fijo' o 'continuo'

# --- Funciones Mock (Reemplazar con tus funciones reales) ---
def fija(model: InputModel):
    # Aquí iría tu lógica de creación de schedules diarios
    print(f"Ejecutando lógica FIJA para el caso: {model.num_case}")
    # Lógica de procesamiento de fechas y llamadas a Azure...
    iniciof_iso, finf_iso = azure_utils.procesar_fechas_modelo(model)
    azure_utils.programacion_fija(model.num_case, iniciof_iso, finf_iso)
    return True

def continua(model: InputModel):
    # Depurando programaciones antiguas.
    azure_utils.delete_disabled_schedules(model.accountid, "automation-sch")
    # Aquí iría tu lógica de creación de schedules de una sola vez
    print(f"Ejecutando lógica CONTINUA para el caso: {model.num_case}")
    # Lógica de procesamiento de fechas y llamadas a Azure...
    inicioc_iso, finc_iso = azure_utils.procesar_fechas_modelo(model)
    azure_utils.programacion_continua(model.num_case, inicioc_iso, finc_iso)
    return True

# --- Endpoint Principal ---
@app.post("/api/v1/sm/environment_reschedule", description="Permite la programación de un ambiente en Azure por API.")
async def crear_programacion(data: InputModel):
    """
    Recibe el request, extrae los datos y enruta según el program_type.
    """
    
    # 1. Validación del tipo de programa
    p_type = data.program_type.lower()
    
    try:
        if p_type == "fijo":
            # 2. Llamada a función de programación fija
            fija(data)
            return {"status": "success", "message": f"Programación fija creada para {data.num_case}"}
        
        elif p_type == "continuo":
            # 3. Llamada a función de programación continua
            continua(data)
            return {"status": "success", "message": f"Programación continua creada para {data.num_case}"}
        
        else:
            # Error si el tipo no es reconocido
            raise HTTPException(
                status_code=400, 
                detail=f"Tipo de programa '{data.program_type}' no soportado. Use 'fijo' o 'continuo'."
            )
            
    except Exception as e:
        # Captura errores de las funciones de ejecución (Azure, fechas, etc)
        raise HTTPException(status_code=500, detail=f"Error interno: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)