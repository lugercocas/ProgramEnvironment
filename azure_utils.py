import uuid
from pydantic import BaseModel
from datetime import datetime, timedelta, timezone
from azure.identity import DefaultAzureCredential
from azure.mgmt.automation import AutomationClient
from azure.mgmt.automation.models import ScheduleCreateOrUpdateParameters, JobScheduleCreateParameters

# Configuración de variables
SUBSCRIPTION_ID = ""
RESOURCE_GROUP = ""
AUTOMATION_ACCOUNT = ""
RUNBOOK_NAME = ""

# 1. Autenticación (Asegúrate de haber hecho 'az login')
credential = DefaultAzureCredential()
client = AutomationClient(credential, SUBSCRIPTION_ID)

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
    program_type:str 

def get_continuo() -> InputModel:
    return InputModel(
        accountid= RESOURCE_GROUP,
        aws_region= "eastus1",
        begin_monthdays= 17,
        begin_time="10:00",
        begin_year= 2026,
        desired_capacity= 1,
        end_monthdays= 17,
        end_time= "10:15",
        end_year= 2026,
        label= "Caso Ejemplo",
        months= "feb",
        num_case= "RF-0008",
        program_type= "continuo"
    )

def get_fijo() -> InputModel:
    return InputModel(
        accountid= RESOURCE_GROUP,
        aws_region= "eastus1",
        begin_monthdays= 16,
        begin_time="18:00",
        begin_year= 2026,
        desired_capacity= 0,
        end_monthdays= 17,
        end_time= "22:00",
        end_year= 2026,
        label= "Caso Ejemplo",
        months= "feb",
        num_case= "RF-0008",
        program_type= "fijo"
    )
    
def create_schedule(name: str, caso: str, inicio, fin):
    
    SCHEDULE_NAME = name
    print(f"Iniciando proceso para: {RUNBOOK_NAME}...")

    # 2. Definir y Crear el Schedule (Ejemplo: Ejecución diaria)
    if caso == "una_vez":
        # Configuración para ejecución única (One-Time)
        schedule_params = ScheduleCreateOrUpdateParameters(
            name=SCHEDULE_NAME,
            # Asegúrate de que start_time sea al menos 5-10 min en el futuro respecto al momento de ejecución
            start_time=inicio, #"2026-02-15T10:00:00+00:00", 
            time_zone="America/Bogota",
            frequency="OneTime",
            description="Schedule creado vía API. Este se eliminará una vez caducado o deshabilitado en la siguiente programación."
        )
    elif caso == "diario":
        schedule_params = ScheduleCreateOrUpdateParameters(
            name=SCHEDULE_NAME,
            start_time=inicio, #"2026-02-15T09:00:00+00:00", # Formato ISO 8601
            expiry_time=fin, #"2027-02-15T09:00:00+00:00",
            time_zone="America/Bogota",
            interval=1,     # Cada 1 día
            frequency="Day",
            description="Schedule creado vía API. Este se eliminará una vez caducado o deshabilitado en la siguiente programación."
        )

    schedule = client.schedule.create_or_update(
        RESOURCE_GROUP,
        AUTOMATION_ACCOUNT,
        SCHEDULE_NAME,
        schedule_params
    )
    print(f"✅ Schedule '{SCHEDULE_NAME}' creado exitosamente.")

def create_job_schedule(name: str, accion: str):
    SCHEDULE_NAME = name
    # 3. Asociar el Schedule al Runbook (Crear Job Schedule)
    # Azure requiere un GUID único para cada asociación (Job Schedule)
    job_schedule_id = str(uuid.uuid4())

    job_schedule_params = JobScheduleCreateParameters(
        schedule={"name": SCHEDULE_NAME},  # Referencia directa por nombre
        runbook={"name": RUNBOOK_NAME},
        parameters={"accion": accion, "AutomationAccountName":"automation-sch", "ResourceGroupName":"DefaultResourceGroup-EUS"},
    )

    client.job_schedule.create(
        RESOURCE_GROUP,
        AUTOMATION_ACCOUNT,
        job_schedule_id,
        job_schedule_params
    )
    
    print(f"🔗 Runbook '{RUNBOOK_NAME}' asociado al schedule correctamente.")
    print(f"ID de la asociación: {job_schedule_id}")

def delete_disabled_schedules(resource_group, automation_account):
    print(f"--- Escaneando Schedules deshabilitados en {automation_account} ---")
    
    # 1. Obtener todos los schedules
    all_schedules = client.schedule.list_by_automation_account(resource_group, automation_account)
    
    # 2. Pre-cargar los Job Schedules para no llamar a la API múltiples veces dentro del bucle
    # Esto evita errores de sesión y mejora la velocidad
    all_job_links = list(client.job_schedule.list_by_automation_account(resource_group, automation_account))
    
    count_deleted = 0

    for schedule in all_schedules:
        # Verificamos si NO está habilitado
        is_rf = schedule.name.startswith("RF-")
        if is_rf and (not schedule.is_enabled or is_expired(schedule)):
            current_name = schedule.name
            print(f"📌 Procesando schedule deshabilitado: '{current_name}'")

            # 3. Buscar y eliminar JobSchedules vinculados
            for link in all_job_links:
                # Comprobamos que el vínculo pertenezca a este schedule
                if link.schedule and link.schedule.name == current_name:
                    try:
                        # IMPORTANTE: Usamos el ID del Job Schedule (el GUID)
                        # Algunos SDKs lo tienen en 'job_schedule_id' o al final de 'id'
                        js_id = link.name  # En JobSchedules, .name suele ser el GUID
                        
                        print(f"   🗑️ Eliminando vínculo (ID: {js_id})...")
                        client.job_schedule.delete(resource_group, automation_account, js_id)
                    except Exception as e:
                        print(f"   ⚠️ No se pudo eliminar el vínculo {js_id}: {e}")

            # 4. Eliminar el Schedule principal
            try:
                print(f"   🗑️ Eliminando el Schedule: {current_name}...")
                client.schedule.delete(resource_group, automation_account, current_name)
                print(f"   ✅ '{current_name}' eliminado.")
                count_deleted += 1
            except Exception as e:
                print(f"   ❌ Error al eliminar el schedule: {e}")

    print(f"\n--- Limpieza completada. Total eliminados: {count_deleted} ---")

def is_expired(schedule):
    """
    Evalúa si un objeto schedule de Azure ha caducado.
    """
    # Obtenemos la hora actual con información de zona horaria UTC
    ahora_utc = datetime.now(timezone.utc)

    # Caso 1: Tiene una fecha de expiración definida (común en recurrentes)
    if schedule.expiry_time:
        if schedule.expiry_time < ahora_utc:
            return True

    # Caso 2: Es de ejecución única (OneTime)
    # Si la hora de inicio ya pasó, se considera expirado/completado
    if schedule.frequency == "OneTime":
        if schedule.start_time < ahora_utc:
            return True

    # Si no cumple ninguna, sigue vigente
    return False

def programacion_fija(rf: str, fecha_inicio, fecha_fin):
    name_start = f"{rf}-Fijo-Start"
    name_stop = f"{rf}-Fijo-Stop"
    # Para Start
    create_schedule(name_start, "diario", fecha_inicio.isoformat(), fecha_fin.isoformat())
    create_job_schedule(name_start, "start")
    # Para Stop
    tz_colombia = timezone(timedelta(hours=-5))
    fecha_stop_inicio = datetime(
        fecha_inicio.year,
        fecha_inicio.month,
        fecha_inicio.day,
        fecha_fin.hour,
        fecha_fin.minute,
        0,
        tzinfo=tz_colombia
    ).isoformat()
    fecha_stop_fin = fecha_fin.isoformat()
    create_schedule(name_stop, "diario", fecha_stop_inicio, fecha_stop_fin)
    create_job_schedule(name_stop, "stop")

def programacion_continua(rf: str, fecha_inicio, fecha_fin):
    name_start = f"{rf}-Continuo-Start"
    name_stop = f"{rf}-Continuo-Stop"
    # Para Start
    start_iso = fecha_inicio.isoformat()
    end_iso = fecha_fin.isoformat()
    create_schedule(name_start, "una_vez", start_iso, start_iso)
    create_job_schedule(name_start, "start")
    # Para Stop
    create_schedule(name_stop, "una_vez", end_iso, end_iso)
    create_job_schedule(name_stop, "stop")

def procesar_fechas_modelo(model: InputModel):
    """
    Recibe un InputModel y retorna una lista [inicio_iso, fin_iso]
    con zona horaria de Colombia (UTC-5).
    """
    
    # 1. Mapeo de meses (ajusta según si tus inputs vienen en español o inglés)
    mapa_meses = {
        "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
        "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
        # Variantes en español por seguridad
        "ene": 1, "abr": 4, "ago": 8, "dic": 12
    }
    
    # 2. Definir Zona Horaria Colombia (UTC-5)
    tz_colombia = timezone(timedelta(hours=-5))

    # 3. Obtener el número del mes de inicio
    # Tomamos las primeras 3 letras y pasamos a minúsculas para buscar en el mapa
    mes_key = model.months.lower()[:3]
    mes_num = mapa_meses.get(mes_key)
    
    if not mes_num:
        raise ValueError(f"Mes no válido: {model.months}")

    # 4. Parsear las horas (formato "HH:MM")
    hora_ini, min_ini = map(int, model.begin_time.split(':'))
    hora_fin, min_fin = map(int, model.end_time.split(':'))

    # 5. Construir el Datetime de INICIO
    dt_inicio = datetime(
        year=model.begin_year,
        month=mes_num,
        day=model.begin_monthdays,
        hour=hora_ini,
        minute=min_ini,
        second=0,
        tzinfo=tz_colombia  # <--- Clave: Zona horaria explícita
    )

    # 6. Construir el Datetime de FIN
    # Lógica para detectar cambio de mes:
    # Si el día de fin es MENOR al día de inicio (ej: empieza el 31 y termina el 1),
    # asumimos que pasamos al mes siguiente.
    mes_fin = mes_num
    anio_fin_calc = model.end_year # Usamos el año que viene en el modelo
    
    if model.end_monthdays < model.begin_monthdays:
        if mes_fin == 12:
            mes_fin = 1
            anio_fin_calc += 1 # Cambio de año si pasamos de Dic a Ene
        else:
            mes_fin += 1

    dt_fin = datetime(
        year=anio_fin_calc,
        month=mes_fin,
        day=model.end_monthdays,
        hour=hora_fin,
        minute=min_fin,
        second=0,
        tzinfo=tz_colombia
    )
    # 7. Retornar formato ISO 8601
    return [dt_inicio, dt_fin]
    # --- Ejemplo de uso ---
    # Supongamos que 'mi_modelo' es lo que obtienes de get_continuo()
    # rango_fechas = procesar_fechas_modelo(mi_modelo)
    # print(rango_fechas)
    # Salida esperada:
    # ['2026-02-15T18:00:00-05:00', '2026-02-16T06:00:00-05:00']

if __name__ == "__main__":
    # 1. Elimino los shceduler vencidos.
    delete_disabled_schedules(RESOURCE_GROUP, AUTOMATION_ACCOUNT)
    # 2. Programación Continua
    input_c = get_continuo()
    inicioc_iso, finc_iso = procesar_fechas_modelo(input_c)
    programacion_continua(input_c.num_case, inicioc_iso, finc_iso)
    # 3. Programación Fija
    input_f = get_fijo()
    iniciof_iso, finf_iso = procesar_fechas_modelo(input_f)
    # programacion_fija(input_f.num_case, iniciof_iso, finf_iso)
