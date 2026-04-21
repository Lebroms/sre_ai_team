import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import uvicorn
from crewai import Agent, Task, Crew, Process, LLM
from crewai.mcp import MCPServerStdio

# ==========================================
# SETUP MCP SERVER (Kubernetes)
# ==========================================
# Copiamo le variabili d'ambiente di Windows in modo che "uvx" e "kubectl" funzionino
mcp_env = os.environ.copy()
# SOSTITUISCI CON IL PATH CORRETTO DI WINDOWS (usa i doppi slash per evitare escape di python)
mcp_env["KUBECONFIG"] = "C:\\Users\\emagi\\.kube\\config"

# Inizializziamo la connessione Stdio verso il server MCP ufficiale di K8s
kubernetes_mcp = MCPServerStdio(
    command="uvx",
    args=["kubernetes-mcp-server@latest"],
    env=mcp_env
)

# ==========================================
# 1. INIZIALIZZAZIONE FASTAPI E CONFIGURAZIONE
# ==========================================
app = FastAPI(
    title="AIOps SRE Brain API",
    description="Microservizio AI per l'analisi Zero-Touch degli allarmi K3s e remediation GitOps",
    version="1.0.0"
)

'''# Setup LLM Locale (Ollama)
# Nota: La GPU NVIDIA GTX 1660 Ti gestirà l'inferenza localmente
local_llm = LLM(
    model="ollama/qwen2.5-coder:7b",
    base_url="http://localhost:11434",
    temperature=0.1 # Temperatura bassa per risposte tecniche e deterministiche
)'''

# ==========================================
# TRUCCO SRE: FORZARE IL TOOL CALLING (OPENAI EMULATION)
# ==========================================
# LiteLLM (usato da CrewAI) richiede una chiave fittizia per i provider OpenAI-compatibili
os.environ["OPENAI_API_KEY"] = "ollama-local"

local_llm = LLM(
    # Cambiamo il prefisso da "ollama/" a "openai/"
    model="openai/qwen2.5-coder:7b",
    # Puntiamo all'endpoint /v1 di Ollama che gestisce il function calling standard
    base_url="http://localhost:11434/v1",
    temperature=0.1
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

    def k8s_action_callback(step_output):
        """
        Intercetta i passaggi intermedi dell'agente. 
        Stampa a schermo quando sta per eseguire un tool MCP.
        """
        # CrewAI restituisce una tupla quando esegue un tool: (ToolName, ToolInput)
        if isinstance(step_output, tuple) and len(step_output) == 2:
            tool_name, tool_input = step_output
            print("\n⚙️ [MCP EXECUTION] L'agente sta eseguendo il comando K8s!")
            print(f"   🛠️ Tool: {tool_name}")
            print(f"   📦 Payload: {tool_input}\n")
        else:
            print(f"\n🧠 [Agent Thinking] {step_output}\n")

    # 2. L'Analista (Cloud Architect)
    analysis_agent = Agent(
        role='Senior Cloud Architect',
        goal='Determine the exact root cause of the Kubernetes failure by actively interrogating the cluster using your MCP tools.',
        backstory=(
            "You are a deeply technical Kubernetes expert. "
            "CRITICAL INSTRUCTION: You MUST use your Kubernetes MCP tools to fetch live data. "
            "Do NOT output raw JSON as your final answer. You must execute the tool to get the real data back. "
            "Base your analysis STRICTLY on the actual output returned by the MCP tool, not your assumptions."
        ),
        llm=local_llm,
        mcps=[kubernetes_mcp], 
        step_callback=k8s_action_callback, # <--- IL NOSTRO SISTEMA DI MONITORAGGIO
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
        description=(
            f"Review this incident brief: Namespace: {alert.namespace}, Pod: {alert.pod}. "
            "1. Use the Kubernetes MCP tool to get the events or resources for this pod. "
            "2. WAIT for the tool to return the data. "
            "3. Read the data returned by the tool. "
            "4. Detail the exact root cause based ONLY on that live data."
        ),
        expected_output="A technical explanation of the actual root cause based strictly on the MCP output.",
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