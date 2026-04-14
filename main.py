import os
from dotenv import load_dotenv
from crewai import Agent, Task, Crew, Process, LLM

# Carica le variabili d'ambiente
load_dotenv()

# ==========================================
# 1. SETUP DEI MODELLI AI
# ==========================================
# Provider Principale: Gemini
gemini_llm =LLM(                 # Sostituisci con gemini-3.1-flash-lite, gemini-2.5-flash, gemini-1.5-flash se preferisci
    model="gemini/gemini-2.5-flash", # Sintassi LiteLLM: provider/nome-modello
    api_key=os.environ.get("GEMINI_API_KEY"),
    temperature=0.1 # Bassa temperatura per ragionamenti SRE analitici e deterministici
)

sre_llm_engine = gemini_llm


# ==========================================
# 2. DEFINIZIONE DEL CONTRATTO DATI (Il JSON catturato da n8n)
# ==========================================
alert_payload = """
{
  "alertname": "PodCrashLooping",
  "namespace": "cloudops-shoes",
  "pod": "chaos-crashloop",
  "reason": "CrashLoopBackOff",
  "severity": "critical",
  "description": "Il pod sta crashando ripetutamente da oltre 1 minuto."
}
"""

# ==========================================
# 3. GLI AGENTI (Il tuo Team)
# ==========================================
investigatore_sre = Agent(
    role='Senior SRE Incident Responder',
    goal='Analizzare gli alert di Kubernetes e stilare un piano di investigazione iniziale chiaro e tecnico.',
    backstory=(
        "Sei un ingegnere SRE veterano. Quando ricevi un alert su un pod in crash, "
        "non vai nel panico. Analizzi i dati a disposizione, identifichi il namespace e il pod, "
        "e prepari una lista di comandi kubectl che un junior dovrebbe lanciare per capire il problema. "
        "Sei diretto, preciso e usi un linguaggio tecnico adeguato a un ambiente Cloud Native."
    ),
    llm=sre_llm_engine, # <-- Iniezione del motore ad Alta Affidabilità
    verbose=True,
    allow_delegation=False
)

# ==========================================
# 4. I TASK (I Ticket di lavoro)
# ==========================================
analisi_iniziale_task = Task(
    description=(
        f"È appena scattato il seguente alert da Prometheus/Alertmanager:\n\n"
        f"{alert_payload}\n\n"
        f"Il tuo compito è:\n"
        f"1. Estrarre i dettagli critici dell'allarme.\n"
        f"2. Spiegare brevemente cosa significa lo stato segnalato in ambito Kubernetes.\n"
        f"3. Scrivere i 3 comandi 'kubectl' esatti che eseguiresti per fare troubleshooting su questo specifico pod nel suo namespace."
    ),
    expected_output="Un report Markdown con l'analisi dell'alert e i comandi kubectl pronti da lanciare.",
    agent=investigatore_sre
)

# ==========================================
# 5. LA CREW (L'esecuzione)
# ==========================================
sre_crew = Crew(
    agents=[investigatore_sre],
    tasks=[analisi_iniziale_task],
    process=Process.sequential
)

if __name__ == "__main__":
    print("🚀 Inizio investigazione AIOps...")
    print("🧠 Motore: Gemini (con fallback su Groq Llama-3)")
    print("----------------------------------------------\n")
    
    risultato = sre_crew.kickoff()
    
    print("\n==============================================")
    print("📋 REPORT DELL'AGENTE SRE:")
    print("==============================================")
    print(risultato)



'''

# Importiamo le classi per l'High Availability dei modelli
from langchain_openai import ChatOpenAI
# from langchain_groq import ChatGroq

# ==========================================
# 1. SETUP DEI MODELLI AI (Architettura HA / Fallback)
# ==========================================
# Provider Principale: Gemini tramite endpoint compatibile OpenAI
gemini_llm = ChatOpenAI(
    api_key=os.environ.get("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    model="gemini-2.5-flash", # Sostituisci con gemini-3.1-flash-lite se preferisci
    temperature=0.1 # Bassa temperatura per ragionamenti SRE analitici e deterministici
)

# Provider di Fallback: Llama-3 su Groq
groq_llm = ChatGroq(
    api_key=os.environ.get("GROQ_API_KEY"),
    model_name="llama3-70b-8192",
    temperature=0.1
)

# Creazione della catena di affidabilità: se Gemini fallisce, subentra Groq
#sre_llm_engine = gemini_llm.with_fallbacks([groq_llm])
# 
# 
# Provider Principale: Gemini
gemini_llm = LLM(
    api_key=os.environ.get("GEMINI_API_KEY"),
    base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
    model="gemini-2.5-flash", # Sostituisci con gemini-3.1-flash-lite se preferisci
    provider="gemini",
    temperature=0.1 # Bassa temperatura per ragionamenti SRE analitici e deterministici
)

sre_llm_engine = gemini_llm'''