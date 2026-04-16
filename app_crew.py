from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from crewai import Agent, Task, Crew, Process, LLM

# ==========================================
# 1. INIZIALIZZAZIONE FASTAPI E CONFIGURAZIONE
# ==========================================
app = FastAPI(
    title="AIOps SRE Brain API",
    description="Microservizio AI per l'analisi Zero-Touch degli allarmi K3s e remediation GitOps",
    version="1.0.0"
)

# Setup LLM Locale (Ollama)
# Nota: La GPU NVIDIA GTX 1660 Ti gestirà l'inferenza localmente
local_llm = LLM(
    model="ollama/qwen2.5-coder:7b",
    base_url="http://localhost:11434",
    temperature=0.1 # Temperatura bassa per risposte tecniche e deterministiche
)

# ==========================================
# 2. DATA CONTRACT DEFINITION (PYDANTIC)
# ==========================================
# Questa classe definisce e valida il payload in ingresso da n8n
class AlertPayload(BaseModel):
    alertname: str
    namespace: str
    pod: str
    reason: str
    severity: str
    description: str

# ==========================================
# 3. ENDPOINT REST
# ==========================================
@app.post("/api/v1/alerts/analyze")
def analyze_alert(alert: AlertPayload):
    """
    Riceve un webhook da n8n/Alertmanager, inietta i dati nella CrewAI 
    e restituisce un report Markdown di investigazione iniziale.
    """
    print(f"🚀 [AIOps] Ricevuto allarme {alert.severity.upper()}: {alert.alertname} sul pod '{alert.pod}'")

    # Estrazione e formattazione dinamica del payload per il prompt dell'agente
    alert_context = (
        f"Alert Name: {alert.alertname}\n"
        f"Namespace: {alert.namespace}\n"
        f"Pod: {alert.pod}\n"
        f"Reason: {alert.reason}\n"
        f"Severity: {alert.severity}\n"
        f"Description: {alert.description}"
    )

    # ==========================================
    # DEFINIZIONE Architettura Multi-Agente
    # ==========================================

    # 1. L'Investigatore (Triage)
    triage_agent = Agent(
        role='L1 SRE Triage Responder',
        goal='Analyze incoming Prometheus alerts, identify the scope of the issue, and prepare a preliminary incident brief.',
        backstory=(
            "You are the first line of defense for an AWS EC2 (eu-west-1) K3s cluster. "
            "You receive raw monitoring alerts, filter out the noise, and structure the problem "
            "so the senior architects can understand exactly what system is failing."
        ),
        llm=local_llm,
        verbose=True
    )

    # 2. L'Analista (Cloud Architect)
    analysis_agent = Agent(
        role='Senior Cloud Architect',
        goal='Determine the potential root causes of the Kubernetes failure based on the Triage brief.',
        backstory=(
            "You are a deeply technical Kubernetes expert. You receive an incident brief about a failing pod. "
            "Since you cannot run commands yet, you list the top 3 most likely infrastructural root causes "
            "(e.g., OOMKilled, misconfigured Readiness Probe, missing ConfigMap) based on the alert 'reason'."
        ),
        llm=local_llm,
        verbose=True
    )

    # 3. Il Risolutore (DevOps Engineer)
    remediation_agent = Agent(
        role='DevOps Automation Engineer',
        goal='Draft the GitOps infrastructure fix to resolve the root cause.',
        backstory=(
            "You are a strict DevOps engineer who follows GitOps principles. You never run imperative commands like 'kubectl edit'. "
            "Based on the Architect's analysis, you draft the exact YAML patch (e.g., resources limits, env vars) "
            "that needs to be committed to the GitHub repository to permanently fix the issue."
        ),
        llm=local_llm,
        verbose=True
    )

    # ==========================================
    # DEFINIZIONE DEI TASK (Workflow Sequenziale)
    # ==========================================

    triage_task = Task(
        description=f"Analyze this alert: {alert_context}. Extract Namespace, Pod, and Reason. Summarize the business impact.",
        expected_output="A short incident brief outlining the affected K8s resources and severity.",
        agent=triage_agent
    )

    analysis_task = Task(
        description="Review the incident brief. Detail the 3 most probable root causes for this specific failure in a K3s environment.",
        expected_output="A technical list of probable root causes and what 'kubectl' commands would prove them.",
        agent=analysis_agent
    )

    remediation_task = Task(
        description="Based on the analysis, write the exact YAML snippet that needs to be updated in the Git repository to fix the most likely root cause. Format it as a GitOps Pull Request proposal.",
        expected_output="A final Markdown report combining the Triage, Analysis, and the proposed YAML patch for the GitOps PR.",
        agent=remediation_agent
    )

    # ==========================================
    # ORCHESTRAZIONE DELLA CREW
    # ==========================================
    sre_crew = Crew(
        agents=[triage_agent, analysis_agent, remediation_agent],
        tasks=[triage_task, analysis_task, remediation_task],
        process=Process.sequential # L'output di un task diventa il contesto del successivo
    )

    try:
        print("🧠 [AIOps] Avvio motore AI: Qwen 2.5 Coder 7B (via Ollama)...")
        # L'esecuzione è sincrona, ma FastAPI usa un threadpool per non bloccare il server
        risultato = sre_crew.kickoff()
        print("✅ [AIOps] Analisi completata con successo.")
        
        # Restituiamo il JSON a n8n. CrewAI restituisce un oggetto, usiamo .raw per il testo puro.
        return {
            "status": "success", 
            "pod_target": alert.pod,
            "report": risultato.raw
        }
    except Exception as e:
        print(f"❌ [AIOps] Errore critico durante l'esecuzione della Crew: {str(e)}")
        raise HTTPException(status_code=500, detail="Errore interno del motore AI durante l'analisi.")

# ==========================================
# 4. AVVIO DEL SERVER
# ==========================================
if __name__ == "__main__":
    print("🌐 Avvio del server FastAPI sulla porta 8000...")
    # Avvia il server in ascolto su tutte le interfacce di rete (0.0.0.0)
    uvicorn.run(app, host="0.0.0.0", port=8000)